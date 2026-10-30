"""Prowlarr 索引器接入：查看、添加、测试索引器。

worker 本身只调用 Prowlarr 的搜索接口（见 search.py），能搜到哪些站点完全取决于
Prowlarr 里配置了哪些索引器。全新安装的 Prowlarr 一个索引器都没有，搜索会直接
返回空列表，所以这里提供一个命令行工具来批量接入可用的公开索引器：

    python indexers.py list             # 已接入的索引器
    python indexers.py add              # 添加推荐列表里还没有的索引器
    python indexers.py add mikan yts    # 只添加指定索引器
    python indexers.py test             # 逐个测试索引器连通性
    python indexers.py search "魔镜号"  # 用 Prowlarr 实际搜一次

在容器里执行：

    docker exec media-automation-worker python indexers.py add

配置读取顺序：环境变量 → data/settings.json → 项目根目录 .env。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

DEFAULT_URL = "http://127.0.0.1:9696"
CONTAINER_HOSTS = {"prowlarr", "qbittorrent", "worker", "station"}
API_PREFIX = "/api/v1"

# 推荐索引器：(Prowlarr 定义名, 说明)。全部是公网免费索引器，
# 覆盖 AV / Anime / 电影 / 综合四类，和本项目的搜索场景对应。
RECOMMENDED: list[tuple[str, str]] = [
    ("sukebeinyaasi", "成人内容（AV），磁力为主"),
    ("freejavtorrent", "成人内容（AV），番号搜索"),
    ("mypornclub", "成人内容（AV）"),
    ("pornxlab", "成人内容（AV）"),
    ("nyaasi", "动画、日剧，磁力为主"),
    ("mikan", "中文字幕动画，BT 下载"),
    ("anibt", "动画聚合，BT 下载"),
    ("acgrip", "中文字幕动画"),
    ("dmhy", "繁体中文动画"),
    ("u3c3", "中文字幕动画"),
    ("nekobt", "动画"),
    ("animetosho-xyz", "动画聚合"),
    ("bangumi-moe", "动画"),
    ("subsplease", "动画（英文组）"),
    ("magnetdownload", "通用磁力搜索"),
    ("torrentdownloads", "综合站点"),
    ("kickasstorrents-to", "普通站里做种最多的之一"),
    ("yts", "英文电影，小体积高做种"),
    ("extratorrent-st", "综合站点"),
    ("rutor", "俄站，老片做种多"),
    ("torrent-pirat", "俄站"),
]

# 常见但被 Cloudflare 拦截、需要 FlareSolverr 才能接入的站点。
# `add --all` 会尝试它们，失败时只提示不中断。
OPTIONAL: list[tuple[str, str]] = [
    ("1337x", "综合站点"),
    ("thepiratebay", "综合站点"),
    ("eztv", "美剧"),
    ("limetorrents", "综合站点"),
    ("0magnet", "中文磁力（AV 资源多）"),
    ("damagnet", "综合站点"),
    ("uindex", "综合站点"),
    ("yts", "英文电影；网络不通时会拖慢整次搜索，慎加"),
    ("knaben", "元搜索；接口常超时，会拖慢整次搜索，慎加"),
]


class IndexerError(RuntimeError):
    """Prowlarr 不可达、鉴权失败或返回了无法处理的响应。"""


def _inside_container() -> bool:
    return Path("/.dockerenv").exists()


def _usable_url(url: str, inside_container: bool | None = None) -> str:
    """把容器内部地址换成本机地址，方便在宿主机上直接运行本脚本。"""
    url = (url or "").strip().rstrip("/")
    if not url:
        return DEFAULT_URL
    if inside_container is None:
        inside_container = _inside_container()
    if inside_container:
        return url
    parts = urlsplit(url)
    if parts.hostname in CONTAINER_HOSTS:
        netloc = "127.0.0.1" + (f":{parts.port}" if parts.port else "")
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return url


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_config(project_dir: Path | None = None) -> tuple[str, str, str]:
    """返回 (Prowlarr 地址, API Key, 来源说明)。"""
    project = Path(project_dir) if project_dir else Path(__file__).resolve().parents[1]
    url = os.getenv("PROWLARR_URL", "").strip()
    key = os.getenv("PROWLARR_API_KEY", "").strip()
    source = "环境变量"

    data_dir = Path(os.getenv("DATA_DIR", "").strip() or project / "data")
    settings_path = data_dir / "settings.json"
    if not key:
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if isinstance(data, dict):
            key = str(data.get("PROWLARR_API_KEY") or "").strip()
            url = url or str(data.get("PROWLARR_URL") or "").strip()
            if key:
                source = str(settings_path)

    if not key:
        values = _read_env_file(project / ".env")
        key = values.get("PROWLARR_API_KEY", "").strip()
        url = url or values.get("PROWLARR_URL", "").strip()
        if key:
            source = str(project / ".env")

    return _usable_url(url), key, source


def error_messages(payload: Any) -> str:
    """Prowlarr 的校验错误是一个 [{errorMessage: ...}] 列表，其余情况兜底。"""
    if isinstance(payload, list):
        messages = [
            str(item.get("errorMessage"))
            for item in payload
            if isinstance(item, dict) and item.get("errorMessage")
        ]
        return "；".join(messages)
    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            if payload.get(key):
                return str(payload[key])
    return ""


def build_indexer(
    schema: dict[str, Any],
    name: str = "",
    base_url: str = "",
    prefer_magnet: bool = True,
) -> dict[str, Any]:
    """把 Prowlarr 的索引器定义模板改成可直接 POST 的索引器对象。"""
    body = copy.deepcopy(schema)
    definition = str(schema.get("definitionName") or "").strip()
    body["name"] = (name or str(schema.get("name") or definition)).strip()
    body["enable"] = True
    if not body.get("appProfileId"):
        body["appProfileId"] = 1
    body.pop("id", None)
    body["priority"] = int(body.get("priority") or 25)
    for field in body.get("fields", []):
        key = field.get("name")
        if key == "baseUrl" and base_url:
            field["value"] = base_url
        elif key == "definitionFile":
            field["value"] = definition
        elif key == "torrentBaseSettings.preferMagnetUrl" and prefer_magnet:
            field["value"] = True
    return body


def build_test_body(
    schema: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造 /indexer/test 的请求体。

    Prowlarr 会用“新建索引器”的规则校验测试请求，已存在的索引器必须带上 id，
    否则会报 "Should be unique"。
    """
    body = build_indexer(schema, name=str((existing or {}).get("name") or ""))
    if existing and existing.get("id"):
        body["id"] = existing["id"]
    return body


class ProwlarrAdmin:
    """Prowlarr 索引器管理接口的薄封装，方便其它模块和测试复用。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = (base_url or DEFAULT_URL).rstrip("/")
        self.api_key = (api_key or "").strip()
        self.timeout = timeout
        self.transport = transport
        self._schemas: list[dict[str, Any]] | None = None

    def _request(self, method: str, path: str, *, timeout: float | None = None, **kwargs):
        headers = {"X-Api-Key": self.api_key, "Accept": "application/json"}
        try:
            with httpx.Client(
                timeout=timeout or self.timeout,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                return client.request(
                    method, f"{self.base_url}{API_PREFIX}{path}", headers=headers, **kwargs
                )
        except httpx.HTTPError as exc:
            raise IndexerError(f"无法连接 Prowlarr（{self.base_url}）：{exc}") from exc

    def indexers(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/indexer")
        if response.status_code in (401, 403):
            raise IndexerError("Prowlarr API Key 无效，请检查设置页或 .env")
        if response.status_code >= 400:
            raise IndexerError(f"读取索引器列表失败：HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise IndexerError("Prowlarr 返回了无法解析的数据") from exc
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def schemas(self) -> list[dict[str, Any]]:
        if self._schemas is None:
            response = self._request("GET", "/indexer/schema", timeout=60.0)
            if response.status_code >= 400:
                raise IndexerError(f"读取索引器定义失败：HTTP {response.status_code}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise IndexerError("Prowlarr 返回了无法解析的定义列表") from exc
            self._schemas = [
                item
                for item in payload
                if isinstance(item, dict) and item.get("definitionName")
            ] if isinstance(payload, list) else []
        return self._schemas

    def schema(self, definition: str) -> dict[str, Any] | None:
        wanted = (definition or "").strip().lower()
        for item in self.schemas():
            if str(item.get("definitionName") or "").lower() == wanted:
                return item
        return None

    def find(self, existing: list[dict[str, Any]], definition: str) -> dict[str, Any] | None:
        wanted = (definition or "").strip().lower()
        for item in existing:
            names = {
                str(item.get("definitionName") or "").lower(),
                str(item.get("name") or "").lower(),
            }
            if wanted in names:
                return item
        return None

    def test(self, body: dict[str, Any], timeout: float = 90.0) -> tuple[bool, str]:
        response = self._request("POST", "/indexer/test", json=body, timeout=timeout)
        message = ""
        try:
            message = error_messages(response.json())
        except ValueError:
            message = ""
        if response.status_code < 400:
            return True, message
        return False, message or f"测试失败：HTTP {response.status_code}"

    def add(self, definition: str, name: str = "", base_url: str = "") -> tuple[bool, str]:
        """返回 (是否新增, 说明)。已存在时返回 (False, "已存在")。"""
        schema = self.schema(definition)
        if schema is None:
            return False, f"Prowlarr 里没有 {definition} 这个索引器定义"
        existing = self.indexers()
        found = self.find(existing, definition)
        if found:
            return False, f"{found.get('name') or definition} 已存在，跳过"
        body = build_indexer(schema, name=name, base_url=base_url)
        response = self._request("POST", "/indexer", json=body, timeout=120.0)
        if response.status_code >= 400:
            try:
                message = error_messages(response.json())
            except ValueError:
                message = ""
            return False, message or f"添加失败：HTTP {response.status_code}"
        return True, f"已添加 {body['name']}"

    def remove(self, definition: str) -> tuple[bool, str]:
        found = self.find(self.indexers(), definition)
        if not found:
            return False, f"没有找到 {definition}"
        response = self._request("DELETE", f"/indexer/{found.get('id')}")
        if response.status_code >= 400:
            return False, f"删除失败：HTTP {response.status_code}"
        return True, f"已删除 {found.get('name') or definition}"

    def health(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/health")
        if response.status_code >= 400:
            return []
        try:
            payload = response.json()
        except ValueError:
            return []
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            "/search",
            params={"query": query, "type": "search", "limit": max(1, min(limit, 50)), "offset": 0},
            timeout=120.0,
        )
        if response.status_code >= 400:
            raise IndexerError(f"搜索失败：HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise IndexerError("Prowlarr 返回了无法解析的搜索结果") from exc
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _make_admin(args: argparse.Namespace) -> ProwlarrAdmin:
    url, key, source = resolve_config()
    if not key:
        raise SystemExit(
            "找不到 Prowlarr API Key：请在设置页保存，或在环境变量 / .env 里设置 PROWLARR_API_KEY"
        )
    if getattr(args, "verbose", False):
        print(f"Prowlarr: {url}（配置来源：{source}）")
    return ProwlarrAdmin(url, key)


def _print_indexers(items: list[dict[str, Any]]) -> None:
    if not items:
        print("还没有接入任何索引器。运行 `python indexers.py add` 添加推荐索引器。")
        return
    print(f"共 {len(items)} 个索引器：")
    for item in items:
        state = "启用" if item.get("enable") else "停用"
        print(
            "  {state}  {name:<22} {lang:<6} {privacy:<8} {definition}".format(
                state=state,
                name=str(item.get("name") or "")[:22],
                lang=str(item.get("language") or "")[:6],
                privacy=str(item.get("privacy") or "")[:8],
                definition=str(item.get("definitionName") or ""),
            )
        )


def cmd_list(args: argparse.Namespace) -> int:
    admin = _make_admin(args)
    _print_indexers(admin.indexers())
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    admin = _make_admin(args)
    targets = list(args.definitions)
    notes: dict[str, str] = {}
    if not targets:
        targets = [definition for definition, _ in RECOMMENDED]
        notes = dict(RECOMMENDED)
    if args.all:
        for definition, note in OPTIONAL:
            if definition not in targets:
                targets.append(definition)
                notes[definition] = note

    added = skipped = failed = 0
    for definition in targets:
        try:
            changed, message = admin.add(definition)
        except IndexerError as exc:
            print(f"  × {definition:<20} {exc}")
            failed += 1
            continue
        note = f"（{notes[definition]}）" if definition in notes else ""
        if changed:
            added += 1
            print(f"  + {definition:<20} {message}{note}")
        elif "已存在" in message:
            skipped += 1
            print(f"  = {definition:<20} {message}")
        else:
            failed += 1
            print(f"  × {definition:<20} {message}")
    print(f"完成：新增 {added}，已存在 {skipped}，失败 {failed}")
    if failed:
        print("被 Cloudflare 拦截的站点需要 FlareSolverr，参考 README「索引器」一节。")
    return 0 if not failed else 1


def cmd_test(args: argparse.Namespace) -> int:
    admin = _make_admin(args)
    existing = admin.indexers()
    if args.definitions:
        wanted = {item.lower() for item in args.definitions}
        existing = [
            item
            for item in existing
            if str(item.get("definitionName") or "").lower() in wanted
            or str(item.get("name") or "").lower() in wanted
        ]
    if not existing:
        print("没有可测试的索引器，先运行 `python indexers.py add`。")
        return 1
    failed = 0
    for item in existing:
        definition = str(item.get("definitionName") or item.get("name") or "")
        body = build_test_body(admin.schema(definition) or item, item)
        try:
            ok, message = admin.test(body)
        except IndexerError as exc:
            ok, message = False, str(exc)
        if ok:
            print(f"  ✓ {item.get('name') or definition}")
        else:
            failed += 1
            print(f"  × {item.get('name') or definition}：{message}")
    print(f"完成：{len(existing) - failed}/{len(existing)} 可用")
    return 0 if not failed else 1


def cmd_search(args: argparse.Namespace) -> int:
    admin = _make_admin(args)
    results = admin.search(args.query, args.limit)
    if not results:
        print("没有搜索结果。检查索引器是否启用，或换一个关键词。")
        return 1
    for item in results:
        size = item.get("size") or 0
        try:
            size_text = f"{int(size) / 1024 ** 3:.2f} GB" if size else "大小未知"
        except (TypeError, ValueError):
            size_text = "大小未知"
        print(
            "{title}\n    {indexer} · {size} · {seeders}↑ {leechers}↓".format(
                title=str(item.get("title") or "")[:110],
                indexer=item.get("indexer") or "未知",
                size=size_text,
                seeders=item.get("seeders") or 0,
                leechers=item.get("leechers") or 0,
            )
        )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    admin = _make_admin(args)
    items = admin.indexers()
    enabled = [item for item in items if item.get("enable")]
    print(f"索引器：{len(items)} 个，启用 {len(enabled)} 个")
    for warning in admin.health():
        if warning.get("type") == "error":
            print(f"! {warning.get('message')}")
    if not enabled:
        print("提示：没有启用的索引器时搜索一定为空，运行 `python indexers.py add`。")
        return 1
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    admin = _make_admin(args)
    failed = 0
    for definition in args.definitions:
        changed, message = admin.remove(definition)
        print(("  - " if changed else "  × ") + message)
        failed += 0 if changed else 1
    return 0 if not failed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="接入 / 检查 Prowlarr 索引器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python indexers.py add mikan yts",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="打印 Prowlarr 地址和配置来源")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list", help="列出已接入的索引器").set_defaults(func=cmd_list)

    add_parser = subparsers.add_parser("add", help="接入索引器（默认添加推荐列表）")
    add_parser.add_argument("definitions", nargs="*", help="Prowlarr 定义名，例如 mikan、yts")
    add_parser.add_argument("--all", action="store_true", help="额外尝试需要 FlareSolverr 的站点")
    add_parser.set_defaults(func=cmd_add)

    test_parser = subparsers.add_parser("test", help="测试已接入索引器的连通性")
    test_parser.add_argument("definitions", nargs="*", help="只测试指定索引器")
    test_parser.set_defaults(func=cmd_test)

    search_parser = subparsers.add_parser("search", help="通过 Prowlarr 实际搜索一次")
    search_parser.add_argument("query", help="片名或关键词")
    search_parser.add_argument("--limit", type=int, default=15, help="返回条数，默认 15")
    search_parser.set_defaults(func=cmd_search)

    status_parser = subparsers.add_parser("status", help="索引器数量与 Prowlarr 健康检查")
    status_parser.set_defaults(func=cmd_status)

    remove_parser = subparsers.add_parser("remove", help="删除索引器")
    remove_parser.add_argument("definitions", nargs="+", help="定义名或索引器名称")
    remove_parser.set_defaults(func=cmd_remove)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    try:
        return int(args.func(args))
    except IndexerError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
