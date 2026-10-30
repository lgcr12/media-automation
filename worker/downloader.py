"""qBittorrent Web API client and helpers for importing finished torrents."""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path
from typing import Any

import httpx


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".m4v", ".webm", ".avi", ".ts"}

COMPLETE_STATES = {
    "uploading",
    "stalledUP",
    "queuedUP",
    "forcedUP",
    "pausedUP",
    "stoppedUP",
    "checkingUP",
}

ERROR_STATES = {"error", "missingFiles", "unknown"}


class DownloadError(RuntimeError):
    """Raised when qBittorrent cannot be reached or rejects an operation."""


class DownloadAuthError(DownloadError):
    """Raised when the configured qBittorrent credentials are rejected."""


def _add_response_ok(response: httpx.Response) -> bool:
    """qBittorrent 4.x returns "Ok."; 5.3+ returns a JSON result object."""
    text = response.text.strip()
    if text in {"", "Ok."}:
        return True
    if "Fails." in text:
        return False
    try:
        data = response.json()
    except ValueError:
        return False
    if isinstance(data, dict):
        if data.get("success_count", 0) > 0:
            return True
        if data.get("added_torrent_ids"):
            return True
        if data.get("failure_count", 0) > 0:
            return False
    return False


def pick_video_file(files: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the main video file, preferring non-sample files and larger sizes."""
    candidates: list[dict[str, Any]] = []
    for item in files:
        name = str(item.get("name") or "")
        if Path(name).suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size <= 0:
            continue
        candidates.append(
            {
                "name": name,
                "size": size,
                "progress": float(item.get("progress") or 0),
                "is_sample": "sample" in Path(name).name.lower(),
            }
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (not item["is_sample"], item["size"]), reverse=True)
    return candidates[0]


def resolve_torrent_file(download_dir: Path, file_info: dict[str, Any]) -> Path:
    """Map a qBittorrent file entry to the path visible inside the worker."""
    raw_name = str(file_info.get("name") or "").strip()
    if not raw_name:
        raise DownloadError("qBittorrent 返回了空文件名")

    candidate = Path(raw_name)
    if candidate.is_absolute():
        # Some qBittorrent versions return an absolute content path.
        resolved = candidate.resolve()
        base = download_dir.resolve()
        if resolved != base and base not in resolved.parents:
            raise DownloadError("种子文件路径超出了下载目录")
        return resolved

    base = download_dir.resolve()
    resolved = (base / candidate).resolve()
    if resolved != base and base not in resolved.parents:
        raise DownloadError("种子文件路径超出了下载目录")
    return resolved


def import_video(source: Path, inbox: Path, job_id: str) -> Path:
    """Hard-link (or copy) the finished video into the watched inbox."""
    source = Path(source)
    if not source.is_file():
        raise DownloadError(f"下载文件不存在：{source}")

    inbox.mkdir(parents=True, exist_ok=True)
    target = inbox / f"{job_id}-{source.name}"
    if target.exists():
        try:
            if target.stat().st_size == source.stat().st_size:
                return target
        except OSError:
            pass
        target.unlink()

    try:
        os.link(source, target)
    except OSError:
        # Hard links fail across filesystems (or on some Docker mounts).
        shutil.copy2(source, target)
    return target


MAGNET_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://explodie.org:6969/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://opentracker.i2p.rocks:6969/announce",
    "https://tracker.tamersunion.org:443/announce",
]


class QBittorrentClient:
    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.transport = transport
        self._client: httpx.Client | None = None
        self._logged_in = False
        self._lock = threading.Lock()

    def __enter__(self) -> "QBittorrentClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self._logged_in = False

    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                follow_redirects=True,
                transport=self.transport,
            )
        if not self._logged_in:
            self._login(self._client)
        return self._client

    def _login(self, client: httpx.Client) -> None:
        try:
            response = client.post(
                "/api/v2/auth/login",
                data={"username": self.username, "password": self.password},
            )
        except httpx.HTTPError as exc:
            raise DownloadError(f"无法连接 qBittorrent：{exc}") from exc
        if response.status_code == 403:
            raise DownloadAuthError("qBittorrent 拒绝登录，请检查是否开启了 IP 封禁")
        if response.status_code >= 400:
            raise DownloadAuthError(f"qBittorrent 登录失败：HTTP {response.status_code}")
        text = response.text.strip()
        # qBittorrent 4.x returns "Ok."; 5.x returns 204 with an empty body.
        if "Fails." in text or (response.status_code != 204 and "Ok." not in text):
            raise DownloadAuthError("qBittorrent 登录失败，请检查用户名和密码")
        self._logged_in = True

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        with self._lock:
            client = self._ensure_client()
            try:
                response = client.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                raise DownloadError(f"qBittorrent 请求失败：{exc}") from exc
            if response.status_code in (401, 403):
                self._logged_in = False
                raise DownloadError("qBittorrent 拒绝了请求，请重新登录")
            if response.status_code == 409:
                raise DownloadError("qBittorrent 中已经存在相同的种子")
            if response.status_code >= 400:
                raise DownloadError(f"qBittorrent 返回 HTTP {response.status_code}")
            return response

    def add_magnet(self, magnet: str, savepath: str, tag: str) -> None:
        # 磁力链接里如果没有 tracker，元数据常常拉不下来（卡在 metaDL），补几个公共 tracker
        if magnet and "&tr=" not in magnet:
            from urllib.parse import quote
            magnet = magnet + "".join(f"&tr={quote(item, safe='')}" for item in MAGNET_TRACKERS)
        response = self._request(
            "POST",
            "/api/v2/torrents/add",
            data={
                "urls": magnet,
                "savepath": savepath,
                "tags": tag,
                "autoTMM": "false",
                "paused": "false",
                "sequentialDownload": "false",
            },
        )
        if not _add_response_ok(response):
            raise DownloadError(f"qBittorrent 未能添加磁力：{response.text.strip()[:200]}")

    def add_torrent(self, content: bytes, filename: str, savepath: str, tag: str) -> None:
        if not content:
            raise DownloadError("种子内容为空")
        response = self._request(
            "POST",
            "/api/v2/torrents/add",
            data={
                "savepath": savepath,
                "tags": tag,
                "autoTMM": "false",
                "paused": "false",
            },
            files={
                "torrents": (
                    filename,
                    content,
                    "application/x-bittorrent",
                )
            },
        )
        if not _add_response_ok(response):
            raise DownloadError(f"qBittorrent 未能添加种子：{response.text.strip()[:200]}")

    def torrents(self, tag: str = "", hashes: str = "") -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if tag:
            params["tag"] = tag
        if hashes:
            params["hashes"] = hashes
        response = self._request("GET", "/api/v2/torrents/info", params=params)
        try:
            data = response.json()
        except ValueError as exc:
            raise DownloadError("qBittorrent 返回了无法解析的任务列表") from exc
        if not isinstance(data, list):
            raise DownloadError("qBittorrent 返回格式异常")
        return [item for item in data if isinstance(item, dict)]

    def files(self, torrent_hash: str) -> list[dict[str, Any]]:
        response = self._request(
            "GET", "/api/v2/torrents/files", params={"hash": torrent_hash}
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise DownloadError("qBittorrent 返回了无法解析的文件列表") from exc
        if not isinstance(data, list):
            raise DownloadError("qBittorrent 返回格式异常")
        return [item for item in data if isinstance(item, dict)]

    def app_version(self) -> str:
        response = self._request("GET", "/api/v2/app/version")
        return response.text.strip()


def torrent_progress(info: dict[str, Any]) -> float:
    try:
        return max(0.0, min(1.0, float(info.get("progress") or 0)))
    except (TypeError, ValueError):
        return 0.0


def torrent_speed(info: dict[str, Any]) -> int:
    try:
        return max(0, int(info.get("dlspeed") or 0))
    except (TypeError, ValueError):
        return 0


def torrent_eta(info: dict[str, Any]) -> int:
    try:
        eta = int(info.get("eta") or 0)
    except (TypeError, ValueError):
        return 0
    # qBittorrent uses 8640000 for "infinity".
    return eta if 0 <= eta < 8640000 else 0
