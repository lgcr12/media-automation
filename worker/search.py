"""Magnet/torrent search through Prowlarr, plus short-lived search sessions."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import json
import ipaddress
import re
import secrets
from urllib.parse import quote
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import httpx


MAGNET_PREFIX = "magnet:?"
BTIH_RE = re.compile(r"xt=urn:btih:([a-zA-Z0-9]+)", re.I)
HTTP_RE = re.compile(r"^https?://", re.I)
VIDEO_HINT_RE = re.compile(
    r"(1080p|2160p|720p|4k|uhd|bluray|blu-ray|web-?dl|webrip|hdtv|remux|x264|x265|h\.?264|h\.?265|hevc|avc)",
    re.I,
)


class SearchError(RuntimeError):
    """Raised when a search backend cannot be reached or returns bad data."""


def parse_magnet_hash(magnet: str) -> str | None:
    match = BTIH_RE.search(magnet or "")
    if not match:
        return None
    value = match.group(1)
    if re.fullmatch(r"[0-9a-fA-F]{40}", value):
        return value.lower()
    if len(value) == 32:
        try:
            return base64.b32decode(value.upper()).hex()
        except (ValueError, TypeError):
            return None
    return None


def human_size(size: int | float) -> str:
    value = float(size or 0)
    if value < 1024:
        return f"{int(value)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TB"


def query_tokens(query: str) -> list[str]:
    lowered = (query or "").lower()
    latin = re.findall(r"[a-z0-9]{2,}", lowered)
    cjk = re.findall(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]+", lowered)
    return latin + cjk


def is_relevant_title(title: str, tokens: list[str]) -> bool:
    if not tokens:
        return True
    lowered = (title or "").lower()
    return any(token in lowered for token in tokens)


DECOR_RE = re.compile(
    r"(\+{2,}|\bFHD\b|\bUHD\b|\b4K\b|\b8K\b|2160p|1080p|720p|480p|HEVC|H\.?26[45]|x26[45]|"
    r"AAC|DDP?\s?\d\.\d|\[中文字幕\]|\[无码高清\]|\[Reducing Mosaic\]|\[有碼高清中文字幕\])",
    re.I,
)
BRACKET_RE = re.compile(r"[\[【(（][^\]】)）]{0,40}[\]】)）]")


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def content_key(title: str, size: int) -> str:
    """同一部片在不同站/不同重发里标题带各种修饰，去掉后再比一次。"""
    text = BRACKET_RE.sub(" ", str(title or ""))
    text = DECOR_RE.sub(" ", text)
    text = re.sub(r"[^0-9A-Za-z\u3040-\u30ff\u4e00-\u9fff]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    bucket = int(int(size or 0) // (50 * 1024 * 1024))
    return f"{text}|{bucket}"


def result_key(item: dict[str, Any]) -> str:
    info_hash = str(item.get("info_hash") or "").strip().lower()
    if info_hash:
        return info_hash
    raw = f"{item.get('title', '')}|{item.get('indexer', '')}|{item.get('size', 0)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def normalize_result(item: dict[str, Any], base_url: str = "") -> dict[str, Any] | None:
    """Convert one Prowlarr search item into the shape the UI/API expects."""
    if not isinstance(item, dict):
        return None

    title = str(item.get("title") or "").strip()
    title = re.sub(r"\s+", " ", title)
    if not title:
        return None

    raw_magnet = str(item.get("magnetUrl") or item.get("magnet") or "").strip()
    guid = str(item.get("guid") or "").strip()
    download_url = str(item.get("downloadUrl") or "").strip()

    magnet = ""
    if guid.lower().startswith(MAGNET_PREFIX):
        magnet = guid
    elif raw_magnet.lower().startswith(MAGNET_PREFIX):
        magnet = raw_magnet

    # 有些站（Kickass 等）magnetUrl 指向的是 Prowlarr 自己的下载地址，
    # 真正的磁力藏在 guid 里；两者都拿不到时用 info_hash 现拼一个。
    if not download_url and raw_magnet.lower().startswith(("http://", "https://")):
        download_url = raw_magnet
    if not download_url and guid.lower().startswith(("http://", "https://")):
        download_url = guid
    if not magnet and not download_url:
        info_hash = str(item.get("infoHash") or "").strip()
        if re.fullmatch(r"[0-9a-fA-F]{40}", info_hash):
            magnet = f"magnet:?xt=urn:btih:{info_hash}&dn={quote(title)}"

    # Prowlarr is normally configured with a reachable public URL; if the
    # download URL is relative, make it usable from the worker.
    if download_url.startswith("/") and base_url:
        download_url = base_url.rstrip("/") + download_url

    if not magnet and not download_url:
        return None
    if magnet and not magnet.lower().startswith(MAGNET_PREFIX):
        magnet = ""
    if download_url and not download_url.lower().startswith(("http://", "https://")):
        download_url = ""

    info_hash = str(item.get("infoHash") or "").strip().lower()
    if not info_hash and magnet:
        info_hash = parse_magnet_hash(magnet) or ""

    try:
        size = int(item.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    try:
        seeders = int(item.get("seeders") or 0)
    except (TypeError, ValueError):
        seeders = 0
    try:
        leechers = int(item.get("leechers") or 0)
    except (TypeError, ValueError):
        leechers = 0

    indexer = str(item.get("indexer") or item.get("indexerName") or "").strip()
    # Mikan/Anibt search feeds do not expose seeder counts; Prowlarr fills 1.
    # Mark them as unknown instead of pretending every release has one seeder.
    seeders_unknown = indexer.strip().lower() in {"mikan", "anibt"}
    result: dict[str, Any] = {
        "title": title[:300],
        "size": size,
        "size_text": human_size(size),
        "seeders": seeders,
        "seeders_unknown": seeders_unknown,
        "leechers": leechers,
        "indexer": indexer[:80],
        "magnet": magnet[:8000],
        "download_url": download_url[:4000],
        "info_hash": info_hash,
        "publish_date": str(item.get("publishDate") or "")[:40],
    }
    result["key"] = result_key(result)
    return result


def merge_results(
    primary: list[dict[str, Any]], extra: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """按 key 去重合并两组结果，保留原顺序。"""
    seen = {item.get("key") for item in primary}
    merged = list(primary)
    for item in extra:
        key = item.get("key")
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def is_manual_link(query: str) -> bool:
    lowered = query.strip().lower()
    if lowered.startswith(MAGNET_PREFIX):
        return True
    if HTTP_RE.match(lowered):
        return urlparse(lowered).path.lower().endswith(".torrent")
    return False


def same_origin(url: str, base_url: str) -> bool:
    try:
        left = urlparse(url)
        right = urlparse(base_url)
    except ValueError:
        return False
    return (
        left.scheme == right.scheme
        and left.netloc.lower() == right.netloc.lower()
    )


def is_safe_torrent_url(url: str) -> bool:
    """Reject obvious SSRF targets for manually pasted .torrent URLs."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return False
    if host.endswith(".localhost") or host.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
    )


def manual_result(query: str) -> dict[str, Any]:
    query = query.strip()
    if query.lower().startswith(MAGNET_PREFIX):
        info_hash = parse_magnet_hash(query) or ""
        title = f"手动磁力 {info_hash[:12]}" if info_hash else "手动磁力链接"
        return {
            "title": title,
            "size": 0,
            "size_text": "大小未知",
            "seeders": 0,
            "leechers": 0,
            "indexer": "手动",
            "magnet": query[:8000],
            "download_url": "",
            "info_hash": info_hash,
            "publish_date": "",
            "key": info_hash or hashlib.sha1(query.encode("utf-8")).hexdigest()[:16],
        }
    name = urlparse(query).path.rsplit("/", 1)[-1] or "手动种子"
    return {
        "title": name[:300],
        "size": 0,
        "size_text": "大小未知",
        "seeders": 0,
        "leechers": 0,
        "indexer": "手动",
        "magnet": "",
        "download_url": query[:4000],
        "info_hash": "",
        "publish_date": "",
        "key": hashlib.sha1(query.encode("utf-8")).hexdigest()[:16],
    }


def fetch_torrent_response(
    client: httpx.Client,
    url: str,
    headers: dict[str, str] | None = None,
    allowed_base: str = "",
) -> bytes | str:
    """Download a .torrent, following redirects but returning a magnet target.

    Some indexers (for example Torrent9) answer a .torrent request with a 301
    to a magnet URI. Returning that string lets qBittorrent add it directly.
    """
    current = url
    request_headers = dict(headers or {})
    for _ in range(6):
        response = client.get(current, headers=request_headers)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location", "")
            if not location:
                raise SearchError("种子下载返回了空重定向地址")
            location = urljoin(current, location)
            if location.lower().startswith(MAGNET_PREFIX):
                return location
            if not (
                (allowed_base and same_origin(location, allowed_base))
                or is_safe_torrent_url(location)
            ):
                raise SearchError("种子下载被重定向到了不安全地址")
            if not (allowed_base and same_origin(location, allowed_base)):
                request_headers = {}
            current = location
            continue
        if response.status_code >= 400:
            raise SearchError(f"下载种子失败：HTTP {response.status_code}")
        content = response.content
        if not content:
            raise SearchError("下载到的种子文件为空")
        if len(content) > 20 * 1024 * 1024:
            raise SearchError("种子文件异常偏大")
        return content
    raise SearchError("种子下载重定向次数过多")


class ProwlarrClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 90.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key, "Accept": "application/json"}

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            transport=self.transport,
        )

    def search(
        self,
        query: str,
        limit: int = 40,
        sort: str = "seeders",
        indexer_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 300))
        try:
            with self._client() as client:
                response = client.get(
                    f"{self.base_url}/api/v1/search",
                    params={
                        "query": query,
                        "type": "search",
                        "limit": limit,
                        "offset": 0,
                        **({"indexerIds": indexer_ids} if indexer_ids else {}),
                    },
                    headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            raise SearchError(f"无法连接 Prowlarr：{exc}") from exc

        if response.status_code in (401, 403):
            raise SearchError("Prowlarr API Key 无效或没有搜索权限")
        if response.status_code >= 400:
            raise SearchError(f"Prowlarr 返回 HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise SearchError("Prowlarr 返回了无法解析的数据") from exc
        if not isinstance(payload, list):
            raise SearchError("Prowlarr 返回格式异常")

        tokens = query_tokens(query)
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        by_content: dict[str, dict[str, Any]] = {}
        for item in payload:
            normalized = normalize_result(item, self.base_url)
            if not normalized or normalized["key"] in seen:
                continue
            # Some indexers (notably YTS) ignore non-Latin queries and return
            # their latest releases instead. Drop clearly unrelated results.
            if not is_relevant_title(normalized["title"], tokens):
                continue
            seen.add(normalized["key"])
            # 同一部片被多个站重发：内容相同的只留做种最多的一条，并记下来源数
            ckey = content_key(normalized["title"], _to_int(normalized.get("size")))
            kept = by_content.get(ckey)
            if kept is None:
                normalized["duplicates"] = 0
                normalized["also_from"] = []
                by_content[ckey] = normalized
                results.append(normalized)
                continue
            kept["duplicates"] = int(kept.get("duplicates") or 0) + 1
            sources = kept.setdefault("also_from", [])
            indexer = str(normalized.get("indexer") or "")
            if indexer and indexer not in sources:
                sources.append(indexer)
            if _to_int(normalized.get("seeders")) > _to_int(kept.get("seeders")):
                # 换成做种更多的那个版本，位置不变
                position = results.index(kept)
                normalized["duplicates"] = kept["duplicates"]
                normalized["also_from"] = sources + [str(kept.get("indexer") or "")]
                results[position] = normalized
                by_content[ckey] = normalized

        if sort == "date":
            results.sort(key=lambda row: row.get("publish_date") or "", reverse=True)
        else:
            # Prefer healthy releases, then video-looking ones, then larger sizes.
            results.sort(
                key=lambda row: (
                    0 if row.get("seeders_unknown") else row["seeders"],
                    1 if VIDEO_HINT_RE.search(row["title"]) else 0,
                    row["size"],
                ),
                reverse=True,
            )
        return results[:limit]

    def indexer_ids(self, names: set[str]) -> list[int]:
        """按索引器名字查出 id，用来只搜指定的站。"""
        try:
            response = httpx.get(
                f"{self.base_url}/api/v1/indexer", headers=self._headers(), timeout=15
            )
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [int(item["id"]) for item in data if item.get("name") in names]

    def fetch_torrent(self, url: str) -> bytes | str:
        if not HTTP_RE.match(url or ""):
            raise SearchError("种子地址无效")
        if not same_origin(url, self.base_url):
            raise SearchError("只允许从已配置的 Prowlarr 拉取种子")

        try:
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                return fetch_torrent_response(
                    client,
                    url,
                    headers=self._headers(),
                    allowed_base=self.base_url,
                )
        except httpx.HTTPError as exc:
            raise SearchError(f"下载种子失败：{exc}") from exc


KEYWORD_ALIASES = {
    "魔镜号": ["マジックミラー号", "MAGIC MIRROR", "MM号"],
    "魔鏡號": ["マジックミラー号", "MAGIC MIRROR", "MM号"],
    "魔镜": ["マジックミラー号", "MAGIC MIRROR"],
}

CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\uff66-\uff9f]")
HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")

TITLE_TRANSLATION_PROMPT = (
    "输入是一个影视资源（含 BT 种子）标题的 JSON 字符串数组。请把每个标题翻译成简体中文，"
    "保留番号（如 SDMM-239）、分辨率（1080p/4K）、字幕组、系列名等专有信息，"
    "不要添加解释、不要合并或拆分条目。只输出一个 JSON 字符串数组，长度和顺序与输入一致。"
)


def needs_translation(title: str) -> bool:
    """日文（含假名）和纯英文标题需要补中文；已经是中文的跳过。"""
    text = (title or "").strip()
    if not text:
        return False
    if KANA_RE.search(text):
        return True
    return not HAN_RE.search(text)


REFUSAL_RE = re.compile(
    r"(无法翻译|无法提供|不能翻译|无法协助|抱歉|对不起|cannot|can'?t|i'm sorry|unable to|as an ai)",
    re.I,
)


def _looks_refused(text: str, source: str = "") -> bool:
    """模型拒答时返回的是一句解释而不是译文，这种结果要丢掉。"""
    value = (text or "").strip()
    if not value:
        return True
    if REFUSAL_RE.search(value):
        return True
    return len(value) > max(160, len(source or "") * 2)


class SearchService:
    """Reads Prowlarr settings on every call so the setup page needs no restart."""

    TRANSLATION_TTL = 7 * 24 * 3600
    TRANSLATION_CACHE_LIMIT = 2000
    TRANSLATION_CHUNK = 16

    def __init__(self, get_setting: Callable[[str, str], str]):
        self.get_setting = get_setting
        self._suggest_cache: dict[str, tuple[float, list[str]]] = {}
        self._suggest_lock = threading.Lock()
        self._translations: dict[str, tuple[float, str]] = {}
        self._translation_lock = threading.Lock()
        self._title_cache_loaded = False
        self._title_cache_path = Path(os.getenv("DATA_DIR", "/data")) / "title_cache.json"

    def configured(self) -> bool:
        return bool(
            self.get_setting("PROWLARR_URL", "").strip()
            and self.get_setting("PROWLARR_API_KEY", "").strip()
        )

    def client(self) -> ProwlarrClient:
        base_url = self.get_setting("PROWLARR_URL", "").strip()
        api_key = self.get_setting("PROWLARR_API_KEY", "").strip()
        if not base_url or not api_key:
            raise SearchError("还没有配置 Prowlarr 地址和 API Key，请先到 /setup 填写")
        return ProwlarrClient(base_url, api_key)

    def search(self, query: str, limit: int = 40) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            raise SearchError("请输入影片名称或磁力链接")
        if is_manual_link(query):
            return [manual_result(query)]
        if len(query) > 300:
            raise SearchError("搜索内容过长")
        client = self.client()
        results = client.search(query, limit)

        # 中文关键词常常搜不到日文/英文标题的种子：结果太少时自动用别名再搜一轮
        if len(results) < 10 and CJK_RE.search(query) and len(query) <= 40:
            aliases = [alias for alias in self.suggest_keywords(query, 2) if alias]
            for alias in aliases:
                try:
                    extra = client.search(alias, limit)
                except SearchError:
                    continue
                results = merge_results(results, extra)
                if len(results) >= limit:
                    break
            if len(results) > 0:
                results = results[:limit]
        return results

    def feed(
        self, limit: int = 30, sort: str = "date", indexers: set[str] | None = None
    ) -> list[dict[str, Any]]:
        """不带关键词取各站资源：sort=date 看最新，sort=seeders 看当下最热门。"""
        limit = max(1, min(int(limit), 300))
        client = self.client()
        ids = client.indexer_ids(indexers) if indexers else []
        results = client.search("", max(limit * 8, 300), sort=sort, indexer_ids=ids)
        if not results:
            return []
        # 每个站最多 6 条轮流拼，避免单个站把列表刷满
        buckets: dict[str, list[dict[str, Any]]] = {}
        for item in results:
            buckets.setdefault(str(item.get("indexer") or "未知"), []).append(item)
        ordered: list[dict[str, Any]] = []
        index = 0
        while len(ordered) < limit:
            added = False
            for bucket in buckets.values():
                if index < len(bucket) and index < 6:
                    ordered.append(bucket[index])
                    added = True
                    if len(ordered) >= limit:
                        break
            if not added:
                break
            index += 1
        # 只有一个站有结果时，把超出 6 条的剩余部分补上
        if len(ordered) < limit:
            for bucket in buckets.values():
                for item in bucket[6:]:
                    if len(ordered) >= limit:
                        break
                    ordered.append(item)
        return ordered[:limit]

    def decorate(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """给非中文标题补一个 title_zh；翻译失败时原样返回，不影响搜索。"""
        try:
            targets = [
                str(item.get("title") or "")
                for item in results
                if needs_translation(str(item.get("title") or ""))
            ]
            if not targets:
                return results
            translations = self.translate_titles(targets)
        except Exception:  # 翻译只是附加信息，任何异常都不能让搜索失败
            return results
        for item in results:
            title = str(item.get("title") or "")
            translated = (translations.get(title) or "").strip()
            if translated and translated != title:
                item["title_zh"] = translated[:200]
        return results

    def _load_title_cache(self) -> None:
        """把上次运行时的标题翻译读进内存，重复搜索就不用再调接口。"""
        with self._translation_lock:
            if self._title_cache_loaded:
                return
            self._title_cache_loaded = True
        try:
            data = json.loads(self._title_cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        now = time.time()
        with self._translation_lock:
            for title, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                value = str(entry.get("zh") or "").strip()
                stamp = float(entry.get("ts") or 0)
                if value and now - stamp < self.TRANSLATION_TTL:
                    self._translations[str(title)] = (time.monotonic(), value)

    def _persist_title_cache(self, pairs: dict[str, str]) -> None:
        if not pairs:
            return
        try:
            try:
                data = json.loads(self._title_cache_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except (OSError, ValueError):
                data = {}
            now = time.time()
            for title, value in pairs.items():
                data[title] = {"zh": value, "ts": now}
            # 最多保留 5000 条，按时间淘汰最旧的
            if len(data) > 5000:
                ordered = sorted(data.items(), key=lambda item: float((item[1] or {}).get("ts") or 0))
                data = dict(ordered[-5000:])
            self._title_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._title_cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _cached_translation(self, title: str) -> str | None:
        self._load_title_cache()
        with self._translation_lock:
            entry = self._translations.get(title)
            if not entry:
                return None
            created, value = entry
            if time.monotonic() - created > self.TRANSLATION_TTL:
                self._translations.pop(title, None)
                return None
            return value

    def _remember_translation(self, title: str, value: str) -> None:
        with self._translation_lock:
            if len(self._translations) >= self.TRANSLATION_CACHE_LIMIT:
                self._translations.clear()
            self._translations[title] = (time.monotonic(), value)

    def translate_titles(self, titles: list[str]) -> dict[str, str]:
        """批量把种子标题翻译成中文，命中缓存的直接返回。"""
        if (self.get_setting("TRANSLATE_TITLES", "true") or "").lower() == "false":
            return {}
        titles = titles[:40]
        result: dict[str, str] = {}
        pending: list[str] = []
        seen: set[str] = set()
        for raw in titles:
            title = (raw or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            cached = self._cached_translation(title)
            if cached is not None:
                result[title] = cached
            else:
                pending.append(title)
        if not pending:
            return result

        # 翻译接口一次只处理几条最快（长标题很容易超时），分批并发发出去。
        chunks = [
            pending[start:start + self.TRANSLATION_CHUNK]
            for start in range(0, len(pending), self.TRANSLATION_CHUNK)
        ]

        def translate_chunk(chunk: list[str]) -> tuple[list[str], list[str]]:
            try:
                return chunk, self._request_translations(chunk)
            except Exception:  # 网络/解析失败：跳过这一批，其它结果照常显示
                return chunk, []

        if len(chunks) <= 1:
            pairs = [translate_chunk(chunk) for chunk in chunks]
        else:
            workers = min(4, len(chunks))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                pairs = list(pool.map(translate_chunk, chunks))

        fresh: dict[str, str] = {}
        for chunk, translated in pairs:
            for title, value in zip(chunk, translated):
                value = (value or "").strip()
                if value and not _looks_refused(value, title) and value != title:
                    result[title] = value
                    fresh[title] = value
                    self._remember_translation(title, value)
        self._persist_title_cache(fresh)
        return result

    def _request_translations(self, titles: list[str]) -> list[str]:
        base_url = self.get_setting("TRANSLATION_BASE_URL", "").strip().rstrip("/")
        api_key = self.get_setting("TRANSLATION_API_KEY", "").strip()
        model = self.get_setting("TRANSLATION_MODEL", "").strip()
        if not base_url or not api_key or not model:
            return []
        # 标题后半段基本是重复信息，截短能显著降低模型延迟。
        shortened = [(title or "").strip()[:160] for title in titles]
        payload = json.dumps(
            {
                "model": model,
                "temperature": 0.1,
                "max_tokens": 1200,
                "enable_thinking": False,
                "reasoning_effort": "low",
                "messages": [
                    {"role": "system", "content": TITLE_TRANSLATION_PROMPT},
                    {"role": "user", "content": json.dumps(shortened, ensure_ascii=False)},
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = httpx.Request(
            "POST",
            f"{base_url}/chat/completions",
            content=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        with httpx.Client(timeout=45, follow_redirects=True) as client:
            response = client.send(request)
        if response.status_code >= 400:
            return []
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        match = re.search(r"\[[\s\S]*\]", content)
        if not match:
            return []
        data = json.loads(match.group(0))
        if not isinstance(data, list):
            return []
        return [str(item).strip() for item in data]

    def _local_aliases(self, query: str) -> list[str]:
        return list(KEYWORD_ALIASES.get(query.strip(), []))

    def suggest_keywords(self, query: str, limit: int = 6) -> list[str]:
        """Suggest Japanese/English aliases for a Chinese search phrase."""
        query = (query or "").strip()
        if not query or len(query) > 80 or not CJK_RE.search(query):
            return []
        cache_key = query.casefold()
        now = time.monotonic()
        with self._suggest_lock:
            cached = self._suggest_cache.get(cache_key)
            if cached and now - cached[0] < 3600:
                return cached[1][:limit]

        suggestions = self._local_aliases(query)
        # Known aliases are instant; only ask the translation model when we
        # have nothing local to show.
        if not suggestions:
            suggestions.extend(self._remote_suggestions(query, limit))
        cleaned: list[str] = []
        seen = {query.casefold()}
        for item in suggestions:
            value = str(item).strip().strip('"').strip("'")
            if not value or len(value) > 80 or value.casefold() in seen:
                continue
            seen.add(value.casefold())
            cleaned.append(value)
            if len(cleaned) >= limit:
                break

        with self._suggest_lock:
            if len(self._suggest_cache) > 500:
                self._suggest_cache.clear()
            self._suggest_cache[cache_key] = (now, cleaned)
        return cleaned

    def _remote_suggestions(self, query: str, limit: int) -> list[str]:
        base_url = self.get_setting("TRANSLATION_BASE_URL", "").strip().rstrip("/")
        api_key = self.get_setting("TRANSLATION_API_KEY", "").strip()
        model = self.get_setting("TRANSLATION_MODEL", "").strip()
        if not base_url or not api_key or not model:
            return []
        prompt = (
            "输入是一个中文影视片名。请给出适合在 BT/磁力索引器搜索的候选关键词："
            "日文原名、英文名、常见缩写、别名、作品编号。"
            "只返回 JSON 字符串数组，最多 6 个，不要解释。\n输入："
            + query
        )
        payload = json.dumps({
            "model": model,
            "temperature": 0.2,
            "max_tokens": 200,
            "messages": [
                {"role": "system", "content": "你是影视资源搜索关键词助手，只输出 JSON 字符串数组。"},
                {"role": "user", "content": prompt},
            ],
        }).encode("utf-8")
        request = httpx.Request(
            "POST",
            f"{base_url}/chat/completions",
            content=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        try:
            with httpx.Client(timeout=25, follow_redirects=True) as client:
                response = client.send(request)
            if response.status_code >= 400:
                return []
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            match = re.search(r"\[[\s\S]*\]", content)
            if not match:
                return []
            data = json.loads(match.group(0))
            if not isinstance(data, list):
                return []
            return [str(item).strip() for item in data if str(item).strip()][:limit]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            return []

    def indexer_ids(self, names: set[str]) -> list[int]:
        """按索引器名字查出 id，用来只搜指定的站。"""
        try:
            response = httpx.get(
                f"{self.base_url}/api/v1/indexer", headers=self._headers(), timeout=15
            )
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [int(item["id"]) for item in data if item.get("name") in names]

    def fetch_torrent(self, url: str) -> bytes | str:
        base_url = self.get_setting("PROWLARR_URL", "").strip().rstrip("/")
        if base_url and same_origin(url, base_url):
            return self.client().fetch_torrent(url)
        if not is_safe_torrent_url(url):
            raise SearchError("种子地址不安全或不是公网 HTTP(S) 地址")
        try:
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                return fetch_torrent_response(client, url)
        except httpx.HTTPError as exc:
            raise SearchError(f"下载种子失败：{exc}") from exc


class SearchSessions:
    """In-memory multi-select sessions backing Telegram inline keyboards."""

    def __init__(self, ttl_seconds: int = 1800):
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [
            sid
            for sid, session in self._sessions.items()
            if now - session["created"] > self.ttl_seconds
        ]
        for sid in expired:
            self._sessions.pop(sid, None)

    def create(self, query: str, results: list[dict[str, Any]]) -> str:
        sid = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]
        with self._lock:
            self._cleanup()
            while sid in self._sessions:
                sid = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]
            self._sessions[sid] = {
                "query": query,
                "results": results,
                "selected": set(),
                "created": time.monotonic(),
            }
        return sid

    def get(self, sid: str) -> dict[str, Any] | None:
        with self._lock:
            self._cleanup()
            session = self._sessions.get(sid)
            if not session:
                return None
            return {
                "sid": sid,
                "query": session["query"],
                "results": list(session["results"]),
                "selected": set(session["selected"]),
            }

    def toggle(self, sid: str, index: int) -> dict[str, Any] | None:
        with self._lock:
            self._cleanup()
            session = self._sessions.get(sid)
            if not session or index < 0 or index >= len(session["results"]):
                return None
            if index in session["selected"]:
                session["selected"].remove(index)
            else:
                session["selected"].add(index)
            return {
                "sid": sid,
                "query": session["query"],
                "results": list(session["results"]),
                "selected": set(session["selected"]),
            }

    def selected_results(self, sid: str) -> list[dict[str, Any]]:
        with self._lock:
            self._cleanup()
            session = self._sessions.get(sid)
            if not session:
                return []
            return [session["results"][index] for index in sorted(session["selected"])]

    def drop(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)
