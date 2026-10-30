import asyncio
import base64
import hashlib
import hmac
import html
import httpx
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import urlparse

from downloader import (
    COMPLETE_STATES,
    ERROR_STATES,
    VIDEO_EXTENSIONS,
    DownloadAuthError,
    DownloadError,
    QBittorrentClient,
    import_video,
    pick_video_file,
    resolve_torrent_file,
    torrent_eta,
    torrent_progress,
    torrent_speed,
)
from search import (
    SearchError,
    SearchService,
    SearchSessions,
    needs_translation,
    parse_magnet_hash,
)
from webui import search_page


RUNTIME_SETTINGS: dict[str, str] = {}


def setting(name: str, default: str = "") -> str:
    return RUNTIME_SETTINGS.get(name, os.getenv(name, default)).strip()


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
            return {str(key): str(value) for key, value in data.items() if value is not None}
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self, values: dict[str, str]) -> None:
        with self._lock:
            temp_path = self.path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(self.path)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass


def apply_settings(values: dict[str, str]) -> None:
    RUNTIME_SETTINGS.update({key: value.strip() for key, value in values.items() if value is not None})


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    print(f"[{now_iso()}] {message}", flush=True)


def normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def format_srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def choose_input_file(folder: Path, job_id: str, auto_match_latest: bool) -> Path | None:
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS]
    exact = [p for p in files if job_id in p.name]
    if exact:
        return max(exact, key=lambda p: p.stat().st_mtime)
    if auto_match_latest and len(files) == 1:
        return files[0]
    return None


class JobStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._jobs = {item["id"]: item for item in data if "id" in item}
        except (OSError, json.JSONDecodeError):
            self._jobs = {}

    def _save(self) -> None:
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(list(self._jobs.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)

    def create(
        self, title: str, chat_id: int | None = None, **extra: Any
    ) -> dict[str, Any]:
        job_id = f"job-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        job = {
            "id": job_id,
            "title": normalize_title(title),
            "chat_id": chat_id,
            "status": "awaiting_source",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "error": None,
            "input_file": None,
            "subtitle_file": None,
            "output_file": None,
            "group_id": None,
            "source": None,
            "torrent_hash": None,
            "download": None,
            "download_failures": 0,
        }
        for key, value in extra.items():
            if key not in {"id", "created_at", "updated_at"}:
                job[key] = value
        with self._lock:
            self._jobs[job_id] = job
            self._save()
        return job

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(job) for job in sorted(self._jobs.values(), key=lambda item: item["created_at"], reverse=True)]

    def update(self, job_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock:
            if job_id not in self._jobs:
                return None
            self._jobs[job_id].update(changes, updated_at=now_iso())
            self._save()
            return dict(self._jobs[job_id])

    def delete(self, job_id: str) -> bool:
        with self._lock:
            if job_id not in self._jobs:
                return False
            del self._jobs[job_id]
            self._save()
            return True


class TranslationClient:
    def __init__(self):
        self.base_url = setting("TRANSLATION_BASE_URL").rstrip("/")
        self.api_key = setting("TRANSLATION_API_KEY")
        self.model = setting("TRANSLATION_MODEL")
        self.usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "calls": 0,
        }
        self.cost = 0.0
        self._usage_lock = threading.Lock()

    def reset_usage(self) -> None:
        with self._usage_lock:
            for key in self.usage:
                self.usage[key] = 0
            self.cost = 0.0

    @staticmethod
    def _price(name: str) -> float:
        try:
            return float(setting(name, "0") or 0)
        except ValueError:
            return 0.0

    def _record_usage(self, payload: dict[str, Any]) -> None:
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if not isinstance(usage, dict):
            return
        with self._usage_lock:
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                try:
                    value = int(usage.get(key) or 0)
                except (TypeError, ValueError):
                    value = 0
                self.usage[key] += max(0, value)
            try:
                prompt = int(usage.get("prompt_tokens") or 0)
            except (TypeError, ValueError):
                prompt = 0
            try:
                completion = int(usage.get("completion_tokens") or 0)
            except (TypeError, ValueError):
                completion = 0
            cached = 0
            details = usage.get("prompt_tokens_details")
            if isinstance(details, dict):
                try:
                    cached = int(details.get("cached_tokens") or 0)
                except (TypeError, ValueError):
                    cached = 0
            if not cached:
                try:
                    cached = int(usage.get("prompt_cache_hit_tokens") or 0)
                except (TypeError, ValueError):
                    cached = 0
            cached = max(0, min(prompt, cached))
            self.usage["cached_tokens"] += cached
            self.usage["calls"] += 1
            price_in, price_out, price_cache = translation_prices(prompt)
            self.cost += (
                (prompt - cached) / 1_000_000 * price_in
                + cached / 1_000_000 * price_cache
                + completion / 1_000_000 * price_out
            )

    def translate(
        self,
        texts: list[str],
        context: list[dict[str, str]] | None = None,
        glossary: list[tuple[str, str]] | None = None,
    ) -> list[str]:
        """整批翻译；某批返回条数不对就二分重试，实在翻不了的保留原文。

        context 是上文字幕的原文/译文对，传给下一批做连贯性参考，
        避免每批独立翻译导致人称、称呼、语气前后不一致。
        """
        if not self.base_url or not self.api_key or not self.model:
            raise RuntimeError("未配置 TRANSLATION_BASE_URL、TRANSLATION_API_KEY 或 TRANSLATION_MODEL")
        polish = setting("TRANSLATION_POLISH", "true").lower() == "true"
        results: list[str] = []
        history: list[dict[str, str]] = list(context or [])[-8:]
        for start in range(0, len(texts), 50):
            batch = texts[start:start + 50]
            translated = self._translate_batch(batch, history, glossary)
            if polish:
                translated = self._polish_batch(batch, translated, history)
            results.extend(translated)
            for source, target in zip(batch, translated):
                history.append({"ja": source, "zh": target})
            history = history[-8:]
        return results

    def _polish_batch(
        self, batch: list[str], draft: list[str], context: list[dict[str, str]] | None = None
    ) -> list[str]:
        """第二遍润色：草稿 + 原文一起给模型，产出更像字幕组成品的译文。"""
        try:
            polished = self._request_polish(batch, draft, context)
            if len(polished) == len(batch):
                return polished
            log(f"润色返回 {len(polished)} 条，期望 {len(batch)} 条，保留草稿")
        except RuntimeError as exc:
            log(f"润色失败，保留草稿：{exc}")
        return draft

    def _request_polish(
        self,
        texts: list[str],
        draft: list[str],
        context: list[dict[str, str]] | None = None,
    ) -> list[str]:
        parts = [
            "下面是一段日文字幕和它的中文草稿，请逐条润色成专业字幕组的成品译文。",
            "要求：口语自然、短句、贴合人物语气；称呼和术语前后一致；不要改变条目数量和顺序。",
        ]
        if context:
            parts.append("上文参考：")
            parts.append(json.dumps(context, ensure_ascii=False))
        parts.append("原文：")
        parts.append(json.dumps(texts, ensure_ascii=False))
        parts.append("草稿：")
        parts.append(json.dumps(draft, ensure_ascii=False))
        parts.append("只输出润色后的 JSON 字符串数组。")
        return self._chat(parts, temperature=0.3, retries=1)

    def _translate_batch(
        self,
        batch: list[str],
        context: list[dict[str, str]] | None = None,
        glossary: list[tuple[str, str]] | None = None,
    ) -> list[str]:
        try:
            translated = self._request_translations(batch, context, glossary)
            if len(translated) == len(batch):
                return translated
            log(f"翻译返回 {len(translated)} 条，期望 {len(batch)} 条")
        except RuntimeError as exc:
            log(f"翻译失败：{exc}")
        if len(batch) == 1:
            log(f"这一段保留原文：{batch[0][:40]}")
            return [batch[0]]
        middle = len(batch) // 2
        return self._translate_batch(batch[:middle], context, glossary) + self._translate_batch(
            batch[middle:], context, glossary
        )

    def _build_prompt(
        self,
        texts: list[str],
        context: list[dict[str, str]] | None,
        glossary: list[tuple[str, str]] | None = None,
    ) -> list[str]:
        parts = [
            "你是资深日译中字幕翻译，长期给影视作品做字幕。把下面 JSON 数组里的日文台词逐条翻译成简体中文。",
            "要求：",
            "1. 严格一一对应：条目数量和顺序与输入完全一致，不许合并、拆分或省略任何一条；",
            "2. 像专业字幕组：口语化、短句，贴合人物性别、年龄和关系，保留撒娇/冷淡/催促/抱怨等语气；",
            "3. 不要逐字直译，按中文语序重组；除专有名词外不要留日文假名或罗马字；",
            "4. 人称、称呼、术语前后统一（例如「你/您」「前辈/哥哥」全程用同一种说法）；",
            "5. 单条尽量控制在 20 个汉字以内，能短则短；语气词保留但不滥用；",
            "6. 只输出 JSON 字符串数组，不要解释。",
        ]
        if context:
            parts.append("上文参考（已经翻译过，仅供理解语气和称呼，不要重复翻译）：")
            parts.append(json.dumps(context, ensure_ascii=False))
        if glossary:
            joined = "\n".join(texts)
            matched = [f"{source} → {target}" for source, target in glossary if source in joined]
            if matched:
                parts.append("术语/称呼表（必须照此翻译，保持一致）：")
                parts.append("\n".join(matched[:40]))
        parts.append("待翻译：")
        parts.append(json.dumps(texts, ensure_ascii=False))
        return parts

    def _post(self, payload: dict[str, Any], retries: int = 0) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        attempt = 0
        while True:
            request = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    body = json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < retries:
                    attempt += 1
                    log(f"翻译请求失败，重试第 {attempt} 次：{exc}")
                    continue
                raise RuntimeError(f"翻译服务不可用: {exc}") from exc
            self._record_usage(body)
            return body

    def _chat(self, parts: list[str], temperature: float = 0.35, retries: int = 0) -> list[str]:
        """发一次对话请求并解析 JSON 数组；retries 是整批重试次数。"""
        body = self._post(
            {
                "model": self.model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": "你是精通日语的资深影视字幕翻译，译文口语化、连贯、贴合语境。"},
                    {"role": "user", "content": "\n".join(parts)},
                ],
            },
            retries,
        )
        content = body["choices"][0]["message"]["content"]
        match = re.search(r"\[[\s\S]*\]", content)
        if not match:
            raise RuntimeError("翻译服务没有返回 JSON 数组")
        return [str(item).strip() for item in json.loads(match.group(0))]

    def read_frame_text(self, input_file: Path, timestamp: float) -> str:
        """抽一帧让模型检查画面里有没有日文台词（没有对白只有字卡的场景用）。"""
        frame = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, timestamp):.2f}",
                "-i", str(input_file), "-frames:v", "1", "-vf", "scale=760:-2",
                "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "4", "pipe:1",
            ],
            capture_output=True,
        )
        if frame.returncode != 0 or not frame.stdout:
            return ""
        image = base64.b64encode(frame.stdout).decode("ascii")
        body = self._post({
            "model": self.model,
            "max_tokens": 200,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "这是视频的一帧。如果画面里有日文字幕、台词或字卡，只输出那段日文原文（多行用 / 分隔）；没有文字就只输出一个「无」。不要描述画面。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
                ],
            }],
        }, retries=1)
        content = str(body["choices"][0]["message"].get("content") or "").strip()
        cleaned = content.strip().strip("「」\"'").replace("\n", "/").strip()
        if not cleaned or cleaned in {"无", "無", "没有", "沒有"}:
            return ""
        if not re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", cleaned):
            return ""
        if len(cleaned) > 120:
            return ""
        return cleaned

    def _request_translations(
        self,
        texts: list[str],
        context: list[dict[str, str]] | None = None,
        glossary: list[tuple[str, str]] | None = None,
    ) -> list[str]:
        result = self._chat(self._build_prompt(texts, context, glossary), temperature=0.35)
        if len(result) != len(texts):
            raise RuntimeError("翻译结果数量与字幕分段数量不一致")
        return result


def _noop_report(stage: str, percent: float, detail: str = "") -> None:
    """默认的进度回调：没有订阅者时什么也不做。"""
    return None


def media_duration(path: Path) -> float:
    """用 PyAV 读时长（秒），读不到就返回 0，让进度条退回不确定状态。"""
    try:
        import av

        with av.open(str(path)) as container:
            return float(container.duration or 0) / 1_000_000
    except Exception:
        return 0.0


def parse_glossary(raw: str) -> list[tuple[str, str]]:
    """把「原文=译文」的多行文本解析成术语表。"""
    entries: list[tuple[str, str]] = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        source, _, target = line.partition("=")
        source, target = source.strip(), target.strip()
        if source and target:
            entries.append((source[:40], target[:40]))
    return entries[:200]


def translation_prices(prompt_tokens: int) -> tuple[float, float, float]:
    """按上下文长度选价格档：≤272K 用基础价，>272K 用高价档。

    价格单位是「每百万 token」。没单独填高价档时，退回基础价的 2 倍。
    """

    def price(name: str) -> float:
        try:
            return float(setting(name, "0") or 0)
        except ValueError:
            return 0.0

    if prompt_tokens > 272_000:
        price_in = price("TRANSLATION_PRICE_INPUT_HIGH") or price("TRANSLATION_PRICE_INPUT") * 2
        price_out = price("TRANSLATION_PRICE_OUTPUT_HIGH") or price("TRANSLATION_PRICE_OUTPUT") * 2
        price_cache = (
            price("TRANSLATION_PRICE_CACHE_HIGH")
            or price("TRANSLATION_PRICE_CACHE")
            or price_in
        )
    else:
        price_in = price("TRANSLATION_PRICE_INPUT")
        price_out = price("TRANSLATION_PRICE_OUTPUT")
        price_cache = price("TRANSLATION_PRICE_CACHE") or price_in
    return price_in, price_out, price_cache


def translation_usage(usage: dict[str, Any], model: str = "") -> dict[str, Any]:
    """把接口返回的 usage 换算成 token 数和预估费用。

    价格单位是「每百万 token」，货币由 TRANSLATION_PRICE_CURRENCY 决定（USD / CNY）。
    缓存命中的输入 token 按 TRANSLATION_PRICE_CACHE 单独计价，没填就按输入价算。
    """
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or 0) or (prompt + completion)
    cached = min(prompt, max(0, int(usage.get("cached_tokens") or 0)))

    price_in, price_out, price_cache = translation_prices(prompt)
    cost = float(usage.get("cost") or 0.0)
    if not cost:
        cost = (
            (prompt - cached) / 1_000_000 * price_in
            + cached / 1_000_000 * price_cache
            + completion / 1_000_000 * price_out
        )
    currency = setting("TRANSLATION_PRICE_CURRENCY", "USD").strip().upper() or "USD"
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cached_tokens": cached,
        "calls": int(usage.get("calls") or 0),
        "cost": round(cost, 6),
        "currency": currency,
        "model": model,
        "priced": bool(price_in or price_out),
    }


class SubtitlePipeline:

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.translation = TranslationClient()

    def process(
        self,
        input_file: Path,
        job_id: str,
        report: Callable[[str, float, str], None] | None = None,
    ) -> tuple[Path, Path]:
        report = report or _noop_report
        self.translation.reset_usage()
        self.last_usage = None
        sidecar = self._find_sidecar(input_file)
        if sidecar is None:
            sidecar = self._generate_subtitles(input_file, job_id, report)
        else:
            report("transcribing", 100.0, "找到现成字幕，跳过识别与翻译")
        subtitle_file = self.output_dir / f"{input_file.stem}.zh-Hans.srt"
        shutil.copy2(sidecar, subtitle_file)
        if setting("BURN_SUBTITLES", "true").lower() == "true":
            output_file = self.output_dir / f"{input_file.stem}-中文字幕.mp4"
            self._burn_subtitles(input_file, subtitle_file, output_file, report)
        else:
            output_file = self.output_dir / input_file.name
            report("copying", 0.0, "复制文件")
            shutil.copy2(input_file, output_file)
            report("copying", 100.0, "复制完成")
        return subtitle_file, output_file

    @staticmethod
    def _find_sidecar(input_file: Path) -> Path | None:
        candidates = [
            input_file.with_suffix(".zh-Hans.srt"),
            input_file.with_suffix(".zh-CN.srt"),
            input_file.with_suffix(".srt"),
        ]
        return next((path for path in candidates if path.exists()), None)

    def _transcript_cache_path(self, input_file: Path, job_id: str) -> Path:
        stats = input_file.stat()
        data_dir = Path(os.getenv("DATA_DIR", "/data"))
        cache_dir = data_dir / "transcripts"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{job_id}-{stats.st_size}.json"

    @staticmethod
    def _load_transcript(path: Path) -> list[dict[str, Any]]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []

    @staticmethod
    def _save_transcript(path: Path, segments: list[Any]) -> None:
        try:
            payload = [
                {"start": float(segment.start), "end": float(segment.end), "text": str(segment.text)}
                for segment in segments
            ]
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except (OSError, AttributeError) as exc:
            log(f"识别结果缓存写入失败：{exc}")

    def _translation_progress_path(self, input_file: Path, job_id: str) -> Path:
        stats = input_file.stat()
        data_dir = Path(os.getenv("DATA_DIR", "/data"))
        cache_dir = data_dir / "translations"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{job_id}-{stats.st_size}.json"

    @staticmethod
    def _load_progress(path: Path) -> dict[str, str]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(key): str(value) for key, value in data.items()}

    @staticmethod
    def _save_progress(path: Path, data: dict[str, str]) -> None:
        try:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log(f"翻译进度写入失败：{exc}")

    def _generate_subtitles(
        self,
        input_file: Path,
        job_id: str,
        report: Callable[[str, float, str], None] = _noop_report,
    ) -> Path:
        cache_path = self._transcript_cache_path(input_file, job_id)
        cached = self._load_transcript(cache_path)
        if cached:
            report("transcribing", 100.0, f"复用上次识别结果（{len(cached)} 段）")
            log(f"{job_id} 复用缓存的识别结果：{len(cached)} 段")
            segments = [
                SimpleNamespace(start=float(item["start"]), end=float(item["end"]), text=str(item["text"]))
                for item in cached
                if isinstance(item, dict) and {"start", "end", "text"} <= set(item)
            ]
            if not segments:
                cached = []
        if not cached:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError("未安装 faster-whisper，无法生成字幕") from exc
            report("transcribing", 0.0, "加载 whisper 模型")
            model = WhisperModel(
                setting("WHISPER_MODEL", "small"),
                device=setting("WHISPER_DEVICE", "cpu"),
                compute_type=setting("WHISPER_COMPUTE_TYPE", "int8"),
            )
            language = setting("WHISPER_LANGUAGE", "auto").strip()
            options = {"vad_filter": True}
            if language and language.lower() not in {"auto", ""}:
                options["language"] = language
            report("transcribing", 0.0, "开始识别")
            segments_iter, info = model.transcribe(str(input_file), **options)
            duration = float(getattr(info, "duration", 0) or 0)
            segments = []
            for segment in segments_iter:
                segments.append(segment)
                if duration > 0:
                    percent = min(99.0, float(segment.end) / duration * 100)
                    report("transcribing", percent, f"已识别 {len(segments)} 段")
            log(f"{job_id} 识别语言：{getattr(info, 'language', None) or 'unknown'}")
            if not segments:
                raise RuntimeError("Whisper 没有识别到对白")
            self._save_transcript(cache_path, segments)
        screen_cues = self._scan_on_screen(input_file, segments, report)
        if screen_cues:
            segments = sorted(list(segments) + screen_cues, key=lambda item: float(item.start))
        total = len(segments)
        translated_texts: list[str] = [""] * total
        history: list[dict[str, str]] = []
        glossary = parse_glossary(setting("TRANSLATION_GLOSSARY", ""))
        bilingual = setting("BILINGUAL_SUBTITLES", "false").lower() == "true"
        progress_path = self._translation_progress_path(input_file, job_id)
        progress = self._load_progress(progress_path)
        # 翻译接口每次调用有 4k+ token 的固定开销，批量越大越省；50 句实测最稳
        batch_size = max(1, min(100, int(setting("TRANSLATION_BATCH", "50"))))
        resumed = 0
        for start in range(0, total, batch_size):
            batch = segments[start:start + batch_size]
            indices = list(range(start, start + len(batch)))
            if all(str(i) in progress for i in indices):
                for i in indices:
                    translated_texts[i] = progress[str(i)]
                resumed += len(indices)
                done = min(total, start + len(batch))
                report("translating", done / total * 100, f"复用已翻译 {done}/{total} 句")
                continue
            source = [segment.text.strip() for segment in batch]
            translated = self.translation.translate(source, history, glossary)
            for offset, text in enumerate(translated):
                translated_texts[start + offset] = text
                progress[str(start + offset)] = text
            self._save_progress(progress_path, progress)
            history.extend(
                {"ja": text, "zh": zh} for text, zh in zip(source, translated)
            )
            history = history[-4:]
            done = min(total, start + len(batch))
            report("translating", done / total * 100, f"已翻译 {done}/{total} 句")
        if resumed:
            log(f"{job_id} 断点续翻：复用 {resumed} 句已翻译结果")
        blocks = []
        for index, (segment, text) in enumerate(zip(segments, translated_texts), start=1):
            original = str(segment.text).strip()
            body_text = f"{original}\n{text}" if bilingual and original else text
            blocks.append(f"{index}\n{format_srt_timestamp(segment.start)} --> {format_srt_timestamp(segment.end)}\n{body_text}\n")
        self.last_usage = translation_usage(
            {**self.translation.usage, "cost": self.translation.cost},
            self.translation.model,
        )
        usage = self.last_usage
        if usage["total_tokens"]:
            log(
                f"{job_id} 翻译用量：{usage['total_tokens']} tokens"
                f"（输入 {usage['prompt_tokens']} / 输出 {usage['completion_tokens']}，"
                f"{usage['calls']} 次调用），预估 ¥{usage['cost']:.4f}"
            )
        path = self.output_dir / f"{job_id}.generated.srt"
        path.write_text("\n".join(blocks), encoding="utf-8")
        try:
            progress_path.unlink()
        except OSError:
            pass
        return path

    def _scan_on_screen(
        self,
        input_file: Path,
        segments: list[Any],
        report: Callable[[str, float, str], None] = _noop_report,
    ) -> list[Any]:
        """没有对白的空档里，抽帧问模型画面里有没有日文字幕/字卡。"""
        if setting("SUBTITLE_OCR", "true").lower() != "true":
            return []
        gaps: list[tuple[float, float]] = []
        previous_end = 0.0
        for segment in segments:
            start = float(segment.start)
            if start - previous_end >= 4.0:
                gaps.append((previous_end, start))
            previous_end = max(previous_end, float(segment.end))
        if not gaps:
            return []

        max_frames = max(1, int(setting("OCR_MAX_FRAMES", "40")))
        tasks: list[tuple[int, float, float, list[float]]] = []
        for index, (start, end) in enumerate(gaps):
            span = end - start
            points = [start + 0.6] if span < 8 else [start + 0.6, end - 0.6]
            tasks.append((index, start, end, points))
        tasks = tasks[: max(1, max_frames)]

        done = 0
        failed = 0
        results: list[tuple[int, float, float, str]] = []

        def probe(task: tuple[int, float, float, list[float]]) -> tuple[int, float, float, str]:
            nonlocal done, failed
            index, start, end, points = task
            for point in points:
                try:
                    text = self.translation.read_frame_text(input_file, point)
                except Exception as exc:  # 画面识别失败不影响主流程
                    log(f"画面识别失败：{exc}")
                    failed += 1
                    text = ""
                if text:
                    return index, start, end, text
            return index, start, end, ""

        # 画面请求很慢（一帧 15~20 秒），并发几路把总时间压下来
        workers = max(1, min(4, int(setting("OCR_WORKERS", "4"))))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for item in pool.map(probe, tasks):
                done += 1
                results.append(item)
                report("on_screen", done / len(tasks) * 100, f"检查画面文字 {done}/{len(tasks)}")
                if failed >= 6 and not any(r[3] for r in results):
                    log("画面识别连续失败，跳过这个环节（可能模型不支持图片）")
                    break

        cues: list[Any] = []
        last_text = ""
        for _, start, end, text in sorted(results):
            if text and text != last_text:
                cues.append(SimpleNamespace(start=start, end=end, text=text))
                last_text = text
        if cues:
            log(f"画面文字识别到 {len(cues)} 段")
        return cues

    @staticmethod
    def _burn_subtitles(
        input_file: Path,
        subtitle_file: Path,
        output_file: Path,
        report: Callable[[str, float, str], None] = _noop_report,
    ) -> None:
        subtitle_arg = str(subtitle_file).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        style = "FontName=Noto Sans CJK SC,FontSize=20,Outline=1,Shadow=0"
        duration = media_duration(input_file)
        command = [
            "ffmpeg", "-y", "-nostats", "-loglevel", "error", "-progress", "pipe:1",
            "-i", str(input_file),
            "-vf", f"subtitles='{subtitle_arg}':fontsdir='/usr/local/share/fonts/custom':force_style='{style}'",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-movflags", "+faststart", str(output_file),
        ]
        report("burning", 0.0, "开始压制")
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            for line in process.stdout or []:
                line = line.strip()
                if not line.startswith("out_time_ms=") or duration <= 0:
                    continue
                try:
                    milliseconds = int(line.split("=", 1)[1])
                except (IndexError, ValueError):
                    continue
                report("burning", min(99.0, milliseconds / 1_000_000 / duration * 100), "")
            stderr = process.stderr.read() if process.stderr else ""
            code = process.wait()
        finally:
            if process.stdout:
                process.stdout.close()
        if code != 0:
            raise RuntimeError(f"ffmpeg 压制失败: {stderr[-2000:]}")
        report("burning", 100.0, "压制完成")


def submit_to_station(job: dict[str, Any]) -> None:
    url = setting("STATION_SUBMIT_URL")
    if not url:
        return
    payload = json.dumps({"job_id": job["id"], "title": job["title"]}).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status >= 300:
                raise RuntimeError(f"状态码 {response.status}")
    except (urllib.error.URLError, RuntimeError) as exc:
        raise RuntimeError(f"115 适配器提交失败: {exc}") from exc


def notify_telegram(job: dict[str, Any], message: str) -> None:
    token = setting("TELEGRAM_BOT_TOKEN")
    chat_id = job.get("chat_id")
    if not token or not chat_id:
        return
    payload = json.dumps({"chat_id": chat_id, "text": message, "disable_web_page_preview": True}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=20).read()
    except urllib.error.URLError:
        pass


class DownloadManager:
    """Adds selected search results to qBittorrent and imports finished files."""

    def __init__(
        self,
        store: JobStore,
        inbox: Path,
        get_setting,
        search_service: SearchService,
        client_factory=QBittorrentClient,
    ):
        self.store = store
        self.inbox = inbox
        self.get_setting = get_setting
        self.search_service = search_service
        self.client_factory = client_factory
        self.inbox.mkdir(parents=True, exist_ok=True)

    def configured(self) -> bool:
        return bool(self.get_setting("QBITTORRENT_URL", "").strip())

    def _client(self) -> QBittorrentClient:
        base_url = self.get_setting("QBITTORRENT_URL", "").strip()
        if not base_url:
            raise DownloadError("还没有配置 qBittorrent 地址，请先到 /setup 填写")
        return self.client_factory(
            base_url,
            self.get_setting("QBITTORRENT_USERNAME", "").strip(),
            self.get_setting("QBITTORRENT_PASSWORD", ""),
        )

    def add(
        self,
        job: dict[str, Any],
        item: dict[str, Any],
        client: QBittorrentClient | None = None,
    ) -> dict[str, Any]:
        magnet = str(item.get("magnet") or "").strip()
        download_url = str(item.get("download_url") or "").strip()
        if magnet and not magnet.lower().startswith("magnet:?"):
            magnet = ""
        if download_url and not download_url.lower().startswith(("http://", "https://")):
            download_url = ""
        if not magnet and not download_url:
            raise DownloadError("这个资源没有磁力链接或种子地址")

        download_dir = self.get_setting("QBITTORRENT_DOWNLOAD_DIR", "/downloads").strip()
        if not download_dir:
            download_dir = "/downloads"

        source_size = safe_int(item.get("size"))
        if source_size > 0:
            free_bytes = shutil.disk_usage(self.inbox).free
            required = source_size * 2 + 2 * 1024**3
            if free_bytes < required:
                raise DownloadError(
                    "磁盘空间不足：资源约 "
                    f"{source_size / 1024**3:.1f} GB，处理前后约需 "
                    f"{required / 1024**3:.1f} GB，当前可用 "
                    f"{free_bytes / 1024**3:.1f} GB"
                )

        owns_client = client is None
        if client is None:
            client = self._client()
        info_hash = str(item.get("info_hash") or "").lower()
        if not info_hash and magnet:
            info_hash = parse_magnet_hash(magnet) or ""
        try:
            if magnet:
                client.add_magnet(magnet, download_dir, job["id"])
            else:
                content = self.search_service.fetch_torrent(download_url)
                if isinstance(content, str):
                    if not content.lower().startswith("magnet:?"):
                        raise DownloadError("种子地址返回了无法识别的重定向")
                    info_hash = info_hash or parse_magnet_hash(content) or ""
                    client.add_magnet(content, download_dir, job["id"])
                else:
                    client.add_torrent(
                        content, f"{job['id']}.torrent", download_dir, job["id"]
                    )
        finally:
            if owns_client:
                client.close()

        source = {
            "title": str(item.get("title") or "")[:300],
            "indexer": str(item.get("indexer") or "")[:80],
            "size": safe_int(item.get("size")),
            "seeders": safe_int(item.get("seeders")),
            "magnet": magnet[:8000],
            "download_url": download_url[:4000],
            "info_hash": info_hash,
        }
        return self.store.update(
            job["id"],
            status="queued",
            source=source,
            torrent_hash=info_hash or None,
            download={"progress": 0.0, "dlspeed": 0, "eta": 0, "state": "queued"},
            download_failures=0,
            error=None,
        ) or job

    def remove(self, job: dict[str, Any], delete_files: bool = True) -> None:
        """Remove the matching qBittorrent torrent and its downloaded files."""
        if not self.configured():
            return
        try:
            client = self._client()
        except DownloadError:
            return
        with client:
            rows: list[dict[str, Any]] = []
            try:
                rows = client.torrents(tag=job["id"])
                if not rows and job.get("torrent_hash"):
                    rows = client.torrents(hashes=job["torrent_hash"])
            except DownloadError:
                return
            for row in rows:
                try:
                    client._request(
                        "POST",
                        "/api/v2/torrents/delete",
                        data={
                            "hashes": row.get("hash", ""),
                            "deleteFiles": "true" if delete_files else "false",
                        },
                    )
                except (DownloadError, OSError, ValueError):
                    continue

    def poll_all(self) -> None:
        jobs = [
            job
            for job in self.store.list()
            if job.get("status") in {"queued", "downloading"}
        ]
        if not jobs:
            return
        try:
            client = self._client()
        except DownloadError as exc:
            for job in jobs:
                self._wait_or_fail(job, exc)
            return
        with client:
            for job in jobs:
                try:
                    self._poll_one(client, job)
                except DownloadAuthError as exc:
                    failed_job = self.store.update(
                        job["id"],
                        status="failed",
                        error=str(exc),
                        download_failures=12,
                    )
                    if failed_job:
                        notify_telegram(failed_job, f"下载失败：{failed_job['title']}\n{exc}")
                except (DownloadError, OSError, ValueError) as exc:
                    self._wait_or_fail(job, exc)
                except Exception as exc:  # never let one bad torrent stop the poller
                    self._wait_or_fail(job, exc)

    def _auto_switch(self, job: dict[str, Any], info: dict[str, Any]) -> None:
        """种子长时间没速度时，自动换成同片里做种更多的版本（每个任务只换一次）。"""
        if setting("AUTO_SWITCH_SLOW", "true").lower() != "true":
            return
        title = str((job.get("source") or {}).get("title") or job.get("title") or "").strip()
        if not title:
            return
        try:
            candidates = self.search_service.search(title[:120], 20)
        except Exception as exc:
            log(f"{job['id']} 换源搜索失败：{exc}")
            return
        current_seeders = safe_int(info.get("num_complete"))
        current_size = safe_int(info.get("size"))
        current_hash = str(job.get("torrent_hash") or "")
        best: dict[str, Any] | None = None
        # AV 类公网做种本来就少，门槛放低：比当前多 2 个做种即可，
        # 并且同样做种数时优先体积小的（小体积 peer 往往更多、下得更快）
        threshold = 3 if current_seeders < 3 else current_seeders + 2
        for item in candidates:
            if str(item.get("info_hash") or "") == current_hash:
                continue
            seeders = safe_int(item.get("seeders"))
            if seeders < threshold:
                continue
            size = safe_int(item.get("size"))
            if current_size and size and not (0.25 <= size / current_size <= 1.4):
                continue
            if best is None:
                best = item
                continue
            best_seeders = safe_int(best.get("seeders"))
            if seeders > best_seeders + 2:
                best = item
            elif abs(seeders - best_seeders) <= 2 and size and safe_int(best.get("size")):
                if size < safe_int(best.get("size")):
                    best = item
        if not best:
            return
        try:
            self.remove(job, delete_files=True)
            self.add(job, best)
            self.store.update(
                job["id"],
                auto_switched=True,
                torrent_hash=str(best.get("info_hash") or "") or None,
                error=None,
                download={"progress": 0.0, "dlspeed": 0, "eta": 0, "state": "queued"},
            )
            log(f"{job['id']} 原种子太慢，已自动换成做种更多的版本：{str(best.get('title'))[:60]}")
        except Exception as exc:
            log(f"{job['id']} 自动换源失败：{exc}")

    def _poll_one(self, client: QBittorrentClient, job: dict[str, Any]) -> None:
        infos = client.torrents(tag=job["id"])
        if not infos and job.get("torrent_hash"):
            infos = client.torrents(hashes=job["torrent_hash"])
        if not infos:
            raise DownloadError("qBittorrent 中还没有出现这个下载任务")

        info = infos[0]
        torrent_hash = str(info.get("hash") or job.get("torrent_hash") or "")
        progress = torrent_progress(info)
        state = str(info.get("state") or "")
        amount_left = safe_int(info.get("amount_left"))
        speed = torrent_speed(info)
        added_on = safe_int(info.get("added_on"))
        elapsed = max(0.0, time.time() - added_on) if added_on else 0.0
        slow = progress < 0.02 and elapsed > 900 and speed < 40 * 1024
        download = {
            "progress": round(progress, 4),
            "dlspeed": speed,
            "eta": torrent_eta(info),
            "state": state,
            "size": safe_int(info.get("size")),
            "completed": safe_int(info.get("completed")),
            "seeds": safe_int(info.get("num_seeds")),
            "seeds_total": safe_int(info.get("num_complete")),
            "slow": slow,
        }
        if slow and not job.get("auto_switched"):
            self._auto_switch(job, info)

        if state in ERROR_STATES and progress < 0.999:
            raise DownloadError(f"qBittorrent 报告异常状态：{state}")

        is_complete = progress >= 0.999 or (
            state in COMPLETE_STATES and amount_left == 0
        )
        if is_complete:
            files = client.files(torrent_hash)
            video = pick_video_file(files)
            if not video:
                raise DownloadError("下载内容中没有找到视频文件")
            source = resolve_torrent_file(self.download_dir(), video)
            if not source.exists():
                # qBittorrent can report 100% while it is still moving files.
                self.store.update(
                    job["id"],
                    status="downloading",
                    torrent_hash=torrent_hash or None,
                    download={**download, "progress": 0.999, "state": "moving"},
                    error=None,
                    download_failures=0,
                )
                return
            target = import_video(source, self.inbox, job["id"])
            self.store.update(
                job["id"],
                status="awaiting_source",
                input_file=str(target),
                torrent_hash=torrent_hash or None,
                download={**download, "progress": 1.0, "state": "completed"},
                error=None,
                download_failures=0,
            )
            log(f"{job['id']} 下载完成，已导入 {target.name}")
            return

        status = "downloading" if progress > 0 or state not in {"queuedDL", "metaDL"} else "queued"
        previous = job.get("download") or {}
        # 进度按 0.01% 记录：老版本要等 0.5% 才刷新，慢速种子会长时间显示 0%。
        changed = (
            previous.get("state") != download["state"]
            or previous.get("progress") != download["progress"]
            or previous.get("completed") != download["completed"]
            or previous.get("seeds") != download["seeds"]
            or safe_int(job.get("download_failures")) != 0
        )
        if changed:
            self.store.update(
                job["id"],
                status=status,
                torrent_hash=torrent_hash or None,
                download=download,
                error=None,
                download_failures=0,
            )

    def _wait_or_fail(self, job: dict[str, Any], exc: Exception) -> None:
        failures = safe_int(job.get("download_failures")) + 1
        message = str(exc)[:500]
        if failures >= 12:
            job = self.store.update(
                job["id"],
                status="failed",
                error=message,
                download_failures=failures,
            )
            if job:
                notify_telegram(job, f"下载失败：{job['title']}\n{message}")
            return
        self.store.update(
            job["id"],
            error=message,
            download_failures=failures,
        )

    def download_dir(self) -> Path:
        value = self.get_setting("QBITTORRENT_DOWNLOAD_DIR", "/downloads").strip()
        return Path(value or "/downloads")


def start_downloads(
    store: JobStore,
    downloads: DownloadManager,
    items: list[dict[str, Any]],
    title: str,
    chat_id: int | None = None,
    group_id: str | None = None,
) -> list[dict[str, Any]]:
    """Create one job per selected search result and enqueue it in qBittorrent."""
    group_id = group_id or f"grp-{uuid.uuid4().hex[:8]}"
    jobs: list[dict[str, Any]] = []
    for item in items[:10]:
        if not isinstance(item, dict):
            continue
        source = {
            "title": str(item.get("title") or "")[:300],
            "indexer": str(item.get("indexer") or "")[:80],
            "size": safe_int(item.get("size")),
            "seeders": safe_int(item.get("seeders")),
            "magnet": str(item.get("magnet") or "")[:8000],
            "download_url": str(item.get("download_url") or "")[:4000],
            "info_hash": str(item.get("info_hash") or "").lower(),
        }
        query_title = normalize_title(title)
        if query_title.lower().startswith(("magnet:?", "http://", "https://")):
            query_title = ""
        # 优先用发布标题，这样同一次搜索选多个版本时能区分开
        release_title = normalize_title(source["title"])
        display_title = (release_title or query_title or "未命名")[:90]
        job = store.create(
            display_title,
            chat_id,
            group_id=group_id,
            source=source,
        )
        try:
            job = downloads.add(job, item) or job
        except Exception as exc:  # a bad result must not prevent the other selections
            job = store.update(job["id"], status="failed", error=str(exc)) or job
        jobs.append(store.get(job["id"]) or job)
    return jobs


def share_secret() -> str:
    """签名下载链接用的密钥；有网页密码时直接派生，否则落在 data/ 里。"""
    password = os.getenv("WEB_PASSWORD", "")
    if password:
        return "media-automation:" + password
    path = Path(os.getenv("DATA_DIR", "/data")) / "share_secret.txt"
    try:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    value = secrets.token_hex(16)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    except OSError:
        pass
    return value


def download_token(job_id: str, kind: str = "video") -> str:
    """给某个任务签一个免登录下载令牌（手机浏览器不会弹认证框）。"""
    message = f"{job_id}:{kind}".encode("utf-8")
    return hmac.new(share_secret().encode("utf-8"), message, hashlib.sha256).hexdigest()[:32]


def is_lan_client(host: str) -> bool:
    """签名/短链下载只给局域网用，避免公网扫到就能下。"""
    host = (host or "").strip()
    if not host:
        return False
    if host in {"localhost", "::1"}:
        return True
    try:
        import ipaddress as _ip

        address = _ip.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback


def short_code(job_id: str) -> str:
    """把 job-20261029-143823-c8ba23 变成 c8ba23，方便手机上手输。"""
    tail = job_id.rsplit("-", 1)[-1]
    return tail.lower() if tail else job_id[-6:].lower()


def find_job_by_short(store: "JobStore", code: str) -> dict[str, Any] | None:
    code = (code or "").strip().lower()
    if not code:
        return None
    for job in store.list():
        if short_code(str(job.get("id") or "")) == code:
            return job
    return None


def lan_ip() -> str:
    """猜一个局域网 IP（不会真的发包），用于给手机生成访问地址。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("223.5.5.5", 80))
            return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def archive_outputs(job: dict[str, Any], files: list[Path]) -> str | None:
    """成品复制到归档目录（容器里是 /archive，宿主机默认 D:\\MediaDownloads）。"""
    root = setting("ARCHIVE_DIR", "").strip()
    if not root:
        return None
    root_path = Path(root)
    if not root_path.is_dir():
        log(f"归档目录不存在，跳过：{root}")
        return None
    raw_title = str(job.get("title") or job.get("id") or "video")
    safe_title = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", raw_title).strip(" .")[:60] or "video"
    suffix = str(job.get("id") or "")[-6:]
    target = root_path / (f"{safe_title}-{suffix}" if suffix else safe_title)
    try:
        target.mkdir(parents=True, exist_ok=True)
        for source in files:
            if not source.is_file():
                continue
            destination = target / source.name
            if destination.exists() and destination.stat().st_size == source.stat().st_size:
                continue
            shutil.copy2(source, destination)
    except OSError as exc:
        log(f"归档失败：{exc}")
        return None
    log(f"{job.get('id')} 已归档到 {target}")
    display_root = setting("ARCHIVE_DISPLAY", "").strip().rstrip("/\\") or root.rstrip("/")
    return f"{display_root}/{target.name}"


class JobRunner:
    def __init__(
        self,
        store: JobStore,
        inbox: Path,
        pipeline: SubtitlePipeline,
        downloads: DownloadManager | None = None,
    ):
        self.store = store
        self.inbox = inbox
        self.pipeline = pipeline
        self.downloads = downloads
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.auto_match = setting("AUTO_MATCH_LATEST", "false").lower() == "true"
        self.poll_seconds = max(3, int(setting("POLL_SECONDS", "15")))
        self.download_poll_seconds = max(3, int(setting("DOWNLOAD_POLL_SECONDS", "5")))
        self.executor = ThreadPoolExecutor(max_workers=1)
        self._active: set[str] = set()
        self._lock = threading.Lock()
        self._recover_interrupted()

    def _recover_interrupted(self) -> None:
        """上次关机/重启时正在处理的任务，进程已经没了，重新排队等扫描。"""
        for job in self.store.list():
            if job.get("status") != "processing":
                continue
            self.store.update(job["id"], status="awaiting_source", stage=None, error=None)
            log(f"{job['id']} 上次处理被中断，已重新排队")

    def loop(self) -> None:
        last_scan = 0.0
        while True:
            try:
                if self.downloads:
                    self.downloads.poll_all()
                now = time.monotonic()
                if now - last_scan >= self.poll_seconds:
                    self.scan_once()
                    last_scan = now
            except Exception as exc:  # keep the only scanner thread alive
                log(f"扫描异常：{exc}")
            time.sleep(self.download_poll_seconds)

    def scan_once(self) -> None:
        jobs = [job for job in self.store.list() if job["status"] == "awaiting_source"]
        now = time.time()
        jobs = [
            job for job in jobs
            if not job.get("retry_at") or float(job.get("retry_at") or 0) <= now
        ]
        for job in jobs:
            try:
                input_file = choose_input_file(self.inbox, job["id"], self.auto_match)
            except OSError as exc:
                log(f"{job['id']} 查找输入文件失败：{exc}")
                continue
            if input_file is None:
                continue
            with self._lock:
                if job["id"] in self._active:
                    continue
                self._active.add(job["id"])
            self.store.update(job["id"], status="processing", input_file=str(input_file))
            self.executor.submit(self._process, job["id"], input_file)

    def _process(self, job_id: str, input_file: Path) -> None:
        def report(stage: str, percent: float, detail: str = "") -> None:
            data = {
                "name": stage,
                "percent": round(max(0.0, min(100.0, float(percent))), 1),
                "detail": str(detail)[:80],
            }
            current = (self.store.get(job_id) or {}).get("stage") or {}
            # 每 1% 才写一次盘，避免转录时每秒都在改 jobs.json
            if current.get("name") == stage and abs(float(current.get("percent") or 0) - data["percent"]) < 1.0:
                return
            self.store.update(job_id, stage=data)

        try:
            subtitle_file, output_file = self.pipeline.process(input_file, job_id, report)
            job = self.store.update(
                job_id,
                status="completed",
                subtitle_file=str(subtitle_file),
                output_file=str(output_file),
                error=None,
                stage={"name": "done", "percent": 100.0, "detail": "完成"},
                process_retries=0,
                retry_at=None,
                translation_usage=getattr(self.pipeline, "last_usage", None),
            )
            if job:
                archived = archive_outputs(job, [subtitle_file, output_file])
                if archived:
                    job = self.store.update(job_id, archive_dir=archived) or job
                url = f"{setting('BASE_URL').rstrip('/')}/download/{job_id}"
                extra = f"\n已保存到：{archived}" if archived else ""
                notify_telegram(job, f"处理完成：{job['title']}\n下载带字幕视频：{url}{extra}")
                self._cleanup_after_success(job)
        except Exception as exc:  # the job should become inspectable instead of killing the worker
            current = self.store.get(job_id) or {}
            attempts = int(current.get("process_retries") or 0) + 1
            limit_retries = max(0, int(setting("PROCESS_RETRIES", "2")))
            if attempts <= limit_retries:
                delay = max(30, int(setting("PROCESS_RETRY_DELAY", "180")))
                job = self.store.update(
                    job_id,
                    status="awaiting_source",
                    stage=None,
                    error=f"第 {attempts} 次失败，{delay // 60} 分钟后自动重试：{exc}",
                    process_retries=attempts,
                    retry_at=time.time() + delay,
                )
                log(f"{job_id} 处理失败（{exc}），{delay} 秒后自动重试第 {attempts} 次")
            else:
                job = self.store.update(job_id, status="failed", error=str(exc), stage=None)
                if job:
                    notify_telegram(job, f"处理失败：{job['title']}\n{exc}")
        finally:
            with self._lock:
                self._active.discard(job_id)

    def _cleanup_after_success(self, job: dict[str, Any]) -> None:
        """归档成功后清掉源文件，省磁盘（AUTO_CLEAN=false 可关闭）。"""
        if setting("AUTO_CLEAN", "true").lower() != "true":
            return
        job_id = str(job.get("id") or "")
        cleaned: list[str] = []
        if self.downloads:
            try:
                self.downloads.remove(job, delete_files=True)
                cleaned.append("qBittorrent 任务")
            except Exception as exc:
                log(f"{job_id} 清理下载任务失败：{exc}")
        input_file = job.get("input_file")
        if input_file:
            path = Path(str(input_file))
            try:
                resolved = path.resolve()
                if resolved.is_file() and self.inbox.resolve() in resolved.parents:
                    resolved.unlink()
                    cleaned.append("inbox 源文件")
            except OSError as exc:
                log(f"{job_id} 删除源文件失败：{exc}")
        if cleaned:
            log(f"{job_id} 已自动清理：{'、'.join(cleaned)}")


def allowed_user(user_id: int | None) -> bool:
    raw = setting("TELEGRAM_ALLOWED_USER_IDS")
    if not raw:
        return True
    try:
        allowed = {int(value.strip()) for value in raw.split(",") if value.strip()}
    except ValueError:
        return False
    return user_id in allowed


def start_telegram(
    store: JobStore,
    search_service: SearchService,
    downloads: DownloadManager,
) -> None:
    token = setting("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    # python-telegram-bot runs its polling loop in this worker thread.
    # Python 3.12 no longer creates an event loop implicitly for new threads.
    asyncio.set_event_loop(asyncio.new_event_loop())
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
        from telegram.request import HTTPXRequest
        from telegram.ext import (
            Application,
            CallbackQueryHandler,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )
    except ImportError:
        print("python-telegram-bot 未安装，跳过 Telegram 服务")
        return

    sessions = SearchSessions()
    status_labels = {
        "queued": "排队中",
        "downloading": "下载中",
        "awaiting_source": "等待处理",
        "processing": "处理中",
        "completed": "已完成",
        "failed": "失败",
    }

    def session_text(session: dict[str, Any]) -> str:
        lines = [f"搜索「{session['query']}」："]
        for index, result in enumerate(session["results"], start=1):
            mark = "✅" if (index - 1) in session["selected"] else "⬜"
            lines.append(f"{mark} {index}. {str(result.get('title', ''))[:70]}")
            if result.get("title_zh"):
                lines.append(f"    🇨🇳 {str(result['title_zh'])[:70]}")
            lines.append(
                f"    {result.get('size_text', '大小未知')} · "
                f"{'做种未知' if result.get('seeders_unknown') else str(result.get('seeders', 0)) + '↑'} · {result.get('indexer') or '未知索引器'}"
            )
        lines.append("")
        lines.append("点击编号可多选，选好后点“开始下载”。")
        return "\n".join(lines)[:4000]

    def session_keyboard(session: dict[str, Any]) -> Any:
        rows = []
        for index, result in enumerate(session["results"]):
            mark = "✅" if index in session["selected"] else "⬜"
            seed_text = "做种未知" if result.get("seeders_unknown") else f"{result.get('seeders', 0)}↑"
            label = f"{mark} {index + 1}. {result.get('size_text', '?')} · {seed_text}"
            rows.append(
                [
                    InlineKeyboardButton(
                        label[:64],
                        callback_data=f"ts:{session['sid']}:{index}",
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    f"开始下载（{len(session['selected'])}）",
                    callback_data=f"td:{session['sid']}",
                ),
                InlineKeyboardButton("取消", callback_data=f"tx:{session['sid']}"),
            ]
        )
        return InlineKeyboardMarkup(rows)

    async def do_search(update: Update, query: str) -> None:
        if not update.effective_user or not allowed_user(update.effective_user.id):
            return
        query = normalize_title(query)
        if not query:
            await update.effective_message.reply_text("用法：/movie 影片名")
            return
        if not update.effective_message:
            return
        searching = await update.effective_message.reply_text("正在搜索…")
        try:
            results = await asyncio.to_thread(search_service.search, query, 8)
        except Exception as exc:
            await searching.edit_text(f"搜索失败：{exc}")
            return
        if results:
            results = await asyncio.to_thread(search_service.decorate, results)
        if not results:
            await searching.edit_text("没有找到匹配结果。试试英文名、日文原名或作品编号，也可以直接发送磁力链接。")
            return
        sid = sessions.create(query, results)
        session = sessions.get(sid)
        if not session:
            await searching.edit_text("搜索会话已过期，请重新搜索。")
            return
        await searching.edit_text(
            session_text(session),
            reply_markup=session_keyboard(session),
            disable_web_page_preview=True,
        )

    async def movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await do_search(update, " ".join(context.args))

    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not allowed_user(update.effective_user.id):
            return
        if update.effective_message:
            await update.effective_message.reply_text(
                "发送片名即可搜索资源，例如：魔镜号\n"
                "也可以发送 magnet 链接，或使用 /movie 魔镜号。\n"
                "选中多个结果后，下载完成会自动生成中文字幕并压制。"
            )

    async def text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not allowed_user(update.effective_user.id):
            return
        text_value = (update.effective_message.text or "").strip()
        if text_value:
            await do_search(update, text_value)

    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not allowed_user(update.effective_user.id):
            return
        lines = []
        for job in store.list()[:10]:
            status = job.get("status", "")
            label = status_labels.get(status, status)
            download = job.get("download") or {}
            if status == "downloading":
                value = float(download.get("progress") or 0) * 100
                label += f" {value:.2f}%" if value < 1 else f" {round(value)}%"
            elif status == "processing":
                stage = job.get("stage") or {}
                stage_names = {
                    "transcribing": "识别语音",
                    "on_screen": "识别画面文字",
                    "translating": "翻译字幕",
                    "burning": "压制视频",
                    "copying": "整理文件",
                    "done": "完成",
                }
                name = stage_names.get(stage.get("name"), "处理中")
                percent = stage.get("percent")
                label += f" {name}" + (f" {round(float(percent))}%" if isinstance(percent, (int, float)) else "")
            line = f"{job['id']}  {label}  {job['title']}"
            if job.get("error") and status == "failed":
                line += f"\n   {str(job['error'])[:120]}"
            lines.append(line)
        await update.effective_message.reply_text("\n".join(lines) or "暂无任务")

    async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        if not update.effective_user or not allowed_user(update.effective_user.id):
            await query.answer("没有权限", show_alert=True)
            return
        data = query.data or ""
        parts = data.split(":")
        if len(parts) < 2:
            await query.answer("无效操作")
            return
        action, sid = parts[0], parts[1]
        raw_index = parts[2] if len(parts) > 2 else ""

        if action == "ts":
            try:
                index = int(raw_index)
            except ValueError:
                await query.answer("无效操作")
                return
            session = sessions.toggle(sid, index)
            if not session:
                await query.answer("会话已过期，请重新 /movie 搜索", show_alert=True)
                return
            await query.answer("已更新选择")
            await query.edit_message_text(
                session_text(session),
                reply_markup=session_keyboard(session),
                disable_web_page_preview=True,
            )
            return

        if action == "td":
            session = sessions.get(sid)
            if not session:
                await query.answer("会话已过期，请重新 /movie 搜索", show_alert=True)
                return
            selected = sessions.selected_results(sid)
            if not selected:
                await query.answer("请先选择至少一个资源", show_alert=True)
                return
            await query.answer("正在创建下载任务…")
            await query.edit_message_text("正在创建下载任务…")
            chat_id = update.effective_chat.id if update.effective_chat else None
            try:
                jobs = await asyncio.to_thread(
                    start_downloads,
                    store,
                    downloads,
                    selected,
                    session["query"],
                    chat_id,
                    sid,
                )
            except Exception as exc:
                await query.edit_message_text(f"创建下载任务失败：{exc}")
                return
            sessions.drop(sid)
            lines = [f"已处理 {len(jobs)} 个资源："]
            for job in jobs:
                label = status_labels.get(job.get("status", ""), job.get("status", ""))
                lines.append(f"· {job['id']}  {label}")
                if job.get("error"):
                    lines.append(f"  {str(job['error'])[:160]}")
            lines.append("")
            lines.append("进度：/status")
            await query.edit_message_text("\n".join(lines)[:4000])
            return

        if action == "tx":
            sessions.drop(sid)
            await query.answer("已取消")
            await query.edit_message_text("已取消本次搜索。")
            return

        await query.answer("无效操作")

    request = HTTPXRequest(connect_timeout=30, read_timeout=60, write_timeout=30, pool_timeout=30)
    updates_request = HTTPXRequest(connect_timeout=30, read_timeout=75, write_timeout=30, pool_timeout=30)
    application = (
        Application.builder()
        .token(token)
        .request(request)
        .get_updates_request(updates_request)
        .build()
    )
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("movie", movie))
    application.add_handler(CommandHandler("search", movie))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text))
    application.run_polling(stop_signals=None)


def telegram_loop(
    store: JobStore,
    search_service: SearchService,
    downloads: DownloadManager,
) -> None:
    """Keep Telegram reconnectable without taking down the HTTP worker."""
    while True:
        try:
            start_telegram(store, search_service, downloads)
            return
        except Exception as exc:
            print(f"Telegram 暂时不可用，将在 30 秒后重试: {exc}", flush=True)
            time.sleep(30)


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    """Strip long magnet/seed URLs from job lists sent to browsers."""
    result = dict(job)
    source = result.get("source")
    if isinstance(source, dict):
        result["source"] = {
            key: source.get(key)
            for key in ("title", "indexer", "size", "seeders", "info_hash")
        }
    return result


def create_api(
    store: JobStore,
    runner: JobRunner,
    settings_store: SettingsStore,
    search_service: SearchService,
    downloads: DownloadManager,
):
    from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
    from fastapi.responses import FileResponse, HTMLResponse, Response

    app = FastAPI(title="Media Automation")

    @app.middleware("http")
    async def no_store(request, call_next):
        response = await call_next(request)
        if request.url.path in {"/", "/setup"} or request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    web_username = os.getenv("WEB_USERNAME", "admin")
    web_password = os.getenv("WEB_PASSWORD", "")
    if web_password:
        @app.middleware("http")
        async def basic_auth(request, call_next):
            if request.url.path == "/health":
                return await call_next(request)
            if request.url.path.startswith(("/s/", "/d/")):
                if is_lan_client(request.client.host if request.client else ""):
                    return await call_next(request)
                return Response("只允许局域网访问", status_code=403)
            header = request.headers.get("authorization", "")
            allowed = False
            if header.lower().startswith("basic "):
                try:
                    decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
                    user, separator, password = decoded.partition(":")
                    allowed = bool(separator) and hmac.compare_digest(
                        user.encode("utf-8"), web_username.encode("utf-8")
                    ) and hmac.compare_digest(
                        password.encode("utf-8"), web_password.encode("utf-8")
                    )
                except Exception:
                    allowed = False
            if not allowed:
                return Response(
                    "需要登录",
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="media-automation"'},
                )
            return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def home():
        return search_page()

    @app.get("/search", response_class=HTMLResponse)
    def search_home():
        return search_page()

    @app.get("/setup", response_class=HTMLResponse)
    def setup():
        return setup_page(settings_store.load())

    @app.post("/setup")
    async def save_setup(
        telegram_token: str = Form(""),
        allowed_user_ids: str = Form(""),
        base_url: str = Form(""),
        translation_provider: str = Form("ollama"),
        translation_base_url: str = Form(""),
        translation_api_key: str = Form(""),
        translation_model: str = Form(""),
        translation_price_input: str = Form(""),
        translation_price_output: str = Form(""),
        translation_price_cache: str = Form(""),
        translation_price_input_high: str = Form(""),
        translation_price_output_high: str = Form(""),
        translation_price_cache_high: str = Form(""),
        translation_price_currency: str = Form(""),
        translation_price_profile: str = Form(""),
        translation_polish: str = Form(""),
        translation_glossary: str = Form(""),
        bilingual_subtitles: str = Form(""),
        translate_titles: str = Form(""),
        burn_subtitles: str = Form(""),
        subtitle_ocr: str = Form(""),
        prowlarr_url: str = Form(""),
        prowlarr_api_key: str = Form(""),
        qbittorrent_url: str = Form(""),
        qbittorrent_username: str = Form(""),
        qbittorrent_password: str = Form(""),
    ):
        current = settings_store.load()
        if telegram_token.strip():
            current["TELEGRAM_BOT_TOKEN"] = telegram_token.strip()
        current["TELEGRAM_ALLOWED_USER_IDS"] = allowed_user_ids.strip()
        current["BURN_SUBTITLES"] = "true" if burn_subtitles == "true" else "false"
        current["SUBTITLE_OCR"] = "true" if subtitle_ocr == "true" else "false"
        if base_url.strip():
            current["BASE_URL"] = base_url.strip().rstrip("/")
        if translation_base_url.strip():
            current["TRANSLATION_BASE_URL"] = translation_base_url.strip().rstrip("/")
        if translation_model.strip():
            current["TRANSLATION_MODEL"] = translation_model.strip()
        if translation_api_key.strip():
            current["TRANSLATION_API_KEY"] = translation_api_key.strip()
        for key, raw in (
            ("TRANSLATION_PRICE_INPUT", translation_price_input),
            ("TRANSLATION_PRICE_OUTPUT", translation_price_output),
            ("TRANSLATION_PRICE_CACHE", translation_price_cache),
            ("TRANSLATION_PRICE_INPUT_HIGH", translation_price_input_high),
            ("TRANSLATION_PRICE_OUTPUT_HIGH", translation_price_output_high),
            ("TRANSLATION_PRICE_CACHE_HIGH", translation_price_cache_high),
        ):
            raw = raw.strip()
            if not raw:
                continue
            try:
                float(raw)
            except ValueError:
                continue
            current[key] = raw
        currency = translation_price_currency.strip().upper()
        if currency in {"USD", "CNY"}:
            current["TRANSLATION_PRICE_CURRENCY"] = currency
        # 常见的两档折扣价，选中后直接覆盖上面的三个价格（gpt-5.6-sol）
        presets = {
            "0.035": {
                "TRANSLATION_PRICE_INPUT": "0.175",
                "TRANSLATION_PRICE_OUTPUT": "1.05",
                "TRANSLATION_PRICE_CACHE": "0.0175",
                "TRANSLATION_PRICE_INPUT_HIGH": "0.35",
                "TRANSLATION_PRICE_OUTPUT_HIGH": "1.575",
                "TRANSLATION_PRICE_CACHE_HIGH": "0.035",
            },
            "0.06": {
                "TRANSLATION_PRICE_INPUT": "0.30",
                "TRANSLATION_PRICE_OUTPUT": "1.80",
                "TRANSLATION_PRICE_CACHE": "0.03",
                "TRANSLATION_PRICE_INPUT_HIGH": "0.60",
                "TRANSLATION_PRICE_OUTPUT_HIGH": "2.70",
                "TRANSLATION_PRICE_CACHE_HIGH": "0.06",
            },
        }
        profile = translation_price_profile.strip()
        if profile in presets:
            current.update(presets[profile])
            current["TRANSLATION_PRICE_CURRENCY"] = "USD"
        current["TRANSLATION_POLISH"] = "true" if translation_polish == "true" else "false"
        current["TRANSLATION_GLOSSARY"] = translation_glossary.strip()
        current["BILINGUAL_SUBTITLES"] = "true" if bilingual_subtitles == "true" else "false"
        current["TRANSLATE_TITLES"] = "true" if translate_titles == "true" else "false"
        if prowlarr_url.strip():
            current["PROWLARR_URL"] = prowlarr_url.strip().rstrip("/")
        if prowlarr_api_key.strip():
            current["PROWLARR_API_KEY"] = prowlarr_api_key.strip()
        if qbittorrent_url.strip():
            current["QBITTORRENT_URL"] = qbittorrent_url.strip().rstrip("/")
        if qbittorrent_username.strip():
            current["QBITTORRENT_USERNAME"] = qbittorrent_username.strip()
        if qbittorrent_password.strip():
            current["QBITTORRENT_PASSWORD"] = qbittorrent_password.strip()
        settings_store.save(current)
        apply_settings(current)
        return setup_page(current, saved=True)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config/status")
    def config_status() -> dict[str, Any]:
        return {
            "prowlarr": search_service.configured(),
            "qbittorrent": downloads.configured(),
            "qbittorrent_password": bool(setting("QBITTORRENT_PASSWORD", "").strip()),
            "telegram": bool(setting("TELEGRAM_BOT_TOKEN")),
            "web_auth": bool(os.getenv("WEB_PASSWORD")),
            "max_upload_gb": max(1, safe_int(setting("MAX_UPLOAD_GB", "8"), 8)),
        }

    @app.get("/jobs")
    def jobs() -> list[dict[str, Any]]:
        return [public_job(job) for job in store.list()]

    @app.get("/api/jobs")
    def api_jobs() -> list[dict[str, Any]]:
        return [public_job(job) for job in store.list()]

    @app.post("/api/jobs/{job_id}/retry")
    def retry_job(job_id: str) -> dict[str, Any]:
        """字幕/压制失败后重跑：文件还在 inbox 里就重新排队。"""
        job = store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        if job.get("status") in {"uploading", "downloading", "processing"}:
            raise HTTPException(status_code=409, detail="任务还在运行，等它结束再重试")

        input_file = job.get("input_file")
        if not input_file or not Path(input_file).is_file():
            try:
                found = choose_input_file(
                    runner.inbox, job_id, bool(getattr(runner, "auto_match", False))
                )
            except OSError:
                found = None
            if found is None:
                raise HTTPException(
                    status_code=400,
                    detail="找不到这个任务的视频文件（可能已删除），请重新下载或上传",
                )
            input_file = str(found)

        updated = store.update(
            job_id,
            status="awaiting_source",
            input_file=input_file,
            error=None,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="任务不存在")
        log(f"{job_id} 重试处理")
        return {"job": public_job(updated)}

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str) -> dict[str, Any]:
        job = store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        warning = None
        try:
            downloads.remove(job, delete_files=True)
        except Exception as exc:
            warning = f"qBittorrent 清理失败：{exc}"

        if job.get("status") != "processing" and job.get("input_file"):
            input_path = Path(job["input_file"])
            try:
                resolved = input_path.resolve()
                inbox = runner.inbox.resolve()
                if inbox in resolved.parents and resolved.is_file():
                    resolved.unlink()
            except OSError as exc:
                warning = (warning + "；" if warning else "") + f"输入文件删除失败：{exc}"

        store.delete(job_id)
        return {"deleted": True, "warning": warning}

    @app.get("/api/search")
    def api_search(q: str = "", limit: int = 30) -> dict[str, Any]:
        try:
            results = search_service.search(q, max(1, min(limit, 50)))
        except SearchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"query": q, "results": results}

    @app.get("/api/suggest")
    def api_suggest(q: str = "") -> dict[str, Any]:
        try:
            suggestions = search_service.suggest_keywords(q, 6)
        except Exception:
            suggestions = []
        return {"query": q, "suggestions": suggestions}

    @app.get("/api/feed")
    def api_feed(limit: int = 30, sort: str = "date", source: str = "") -> dict[str, Any]:
        """没有目标时翻一翻各站资源：sort=date 最新，sort=seeders 最热门；source=av 只看成人站。"""
        try:
            av_indexers = {"sukebei.nyaa.si", "0Magnet", "DaMagNet", "Free JAV Torrent", "PornXLab"}
            results = search_service.feed(
                max(1, min(limit, 50)), sort=sort, indexers=av_indexers if source == "av" else None
            )
        except SearchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"results": results}

    @app.get("/api/stats")
    def api_stats() -> dict[str, Any]:
        jobs = store.list()
        completed = [job for job in jobs if job.get("status") == "completed"]
        failed = [job for job in jobs if job.get("status") == "failed"]
        tokens = 0
        cost = 0.0
        for job in jobs:
            usage = job.get("translation_usage") or {}
            tokens += int(usage.get("total_tokens") or 0)
            cost += float(usage.get("cost") or 0.0)
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        week = [job for job in jobs if str(job.get("created_at") or "") >= week_ago]
        return {
            "total": len(jobs),
            "completed": len(completed),
            "failed": len(failed),
            "week": len(week),
            "tokens": tokens,
            "cost": round(cost, 4),
            "currency": setting("TRANSLATION_PRICE_CURRENCY", "USD"),
        }

    @app.get("/api/health/status")
    def api_health_status() -> dict[str, Any]:
        items: list[dict[str, Any]] = []

        base = setting("PROWLARR_URL", "").strip().rstrip("/")
        key = setting("PROWLARR_API_KEY", "").strip()
        if not (base and key):
            items.append({"name": "Prowlarr", "ok": False, "detail": "未配置地址或 API Key"})
        else:
            try:
                with httpx.Client(timeout=10) as client:
                    headers = {"X-Api-Key": key}
                    health = client.get(f"{base}/api/v1/health", headers=headers).json()
                    indexers = client.get(f"{base}/api/v1/indexer", headers=headers).json()
                errors = [item for item in health if item.get("type") == "error"] if isinstance(health, list) else []
                detail = f"{len(indexers)} 个索引器"
                if errors:
                    detail += "，" + str(errors[0].get("message") or "")[:40]
                items.append({"name": "Prowlarr", "ok": not errors, "detail": detail})
            except Exception as exc:
                items.append({"name": "Prowlarr", "ok": False, "detail": str(exc)[:60]})

        try:
            with downloads._client() as qbt:
                version = qbt.app_version()
            items.append({"name": "qBittorrent", "ok": True, "detail": version or "已连接"})
        except Exception as exc:
            items.append({"name": "qBittorrent", "ok": False, "detail": str(exc)[:60]})

        flaresolverr = os.getenv("FLARESOLVERR_URL", "http://flaresolverr:8191/")
        try:
            with httpx.Client(timeout=5) as client:
                client.get(flaresolverr)
            items.append({"name": "FlareSolverr", "ok": True, "detail": "就绪"})
        except Exception:
            items.append({"name": "FlareSolverr", "ok": False, "detail": "无响应"})

        translated = bool(setting("TRANSLATION_BASE_URL") and setting("TRANSLATION_MODEL"))
        items.append({
            "name": "翻译接口",
            "ok": translated,
            "detail": (setting("TRANSLATION_MODEL") or "未配置")[:30],
        })

        try:
            free = shutil.disk_usage(runner.inbox).free / 1024 ** 3
            items.append({"name": "磁盘", "ok": free > 20, "detail": f"剩 {free:.0f} GB"})
        except OSError:
            pass
        return {"items": items}

    @app.post("/api/translate")
    def api_translate(payload: dict[str, Any]) -> dict[str, Any]:
        """把搜索结果里的日文/英文标题翻成中文，前端渲染完列表后再补。"""
        raw = payload.get("titles") if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            return {"translations": {}}
        titles: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                continue
            title = item.strip()[:300]
            if title and needs_translation(title) and title not in titles:
                titles.append(title)
        if not titles:
            return {"translations": {}}
        try:
            translations = search_service.translate_titles(titles[:8])
        except Exception:
            translations = {}
        return {"translations": translations}

    @app.post("/api/upload")
    async def upload_video(
        request: Request,
        file: UploadFile = File(...),
        title: str = Form(""),
    ) -> dict[str, Any]:
        filename = Path(str(file.filename or "")).name
        suffix = Path(filename).suffix.lower()
        if not filename or suffix not in VIDEO_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail="只支持视频文件：" + ", ".join(sorted(VIDEO_EXTENSIONS)),
            )

        max_gb = max(1, safe_int(setting("MAX_UPLOAD_GB", "8"), 8))
        max_bytes = max_gb * 1024**3
        try:
            content_length = int(request.headers.get("content-length") or 0)
        except ValueError:
            content_length = 0
        if content_length and content_length > max_bytes:
            raise HTTPException(status_code=413, detail=f"文件超过 {max_gb}GB 限制")

        runner.inbox.mkdir(parents=True, exist_ok=True)
        if content_length and shutil.disk_usage(runner.inbox).free < content_length * 2 + 1024**3:
            raise HTTPException(
                status_code=507,
                detail="磁盘空间不足：上传和处理输出大约需要文件大小的 2 倍空间",
            )

        job_title = normalize_title(title) or Path(filename).stem
        job = store.create(job_title[:200], status="uploading")
        target = runner.inbox / f"{job['id']}-{filename}"
        written = 0
        try:
            with target.open("wb") as output:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise HTTPException(
                            status_code=413, detail=f"文件超过 {max_gb}GB 限制"
                        )
                    if shutil.disk_usage(runner.inbox).free < 1024**3:
                        raise HTTPException(status_code=507, detail="磁盘空间不足")
                    output.write(chunk)
            if written == 0:
                raise HTTPException(status_code=400, detail="上传文件为空")
        except HTTPException as exc:
            target.unlink(missing_ok=True)
            store.update(job["id"], status="failed", error=str(exc.detail))
            raise
        except Exception as exc:
            target.unlink(missing_ok=True)
            store.update(job["id"], status="failed", error=f"上传失败：{exc}")
            raise HTTPException(status_code=500, detail="上传失败") from exc
        finally:
            await file.close()

        updated = store.update(
            job["id"],
            status="awaiting_source",
            input_file=str(target),
        )
        return {"job": public_job(updated or job)}

    @app.post("/api/download")
    def api_download(payload: dict[str, Any]) -> dict[str, Any]:
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            raise HTTPException(status_code=400, detail="items 不能为空")
        if len(items) > 10:
            raise HTTPException(status_code=400, detail="一次最多选择 10 个资源")
        title = normalize_title(str(payload.get("title") or ""))[:200]
        chat_id = payload.get("chat_id")
        if not isinstance(chat_id, int):
            chat_id = None
        created = start_downloads(store, downloads, items, title, chat_id)
        return {"jobs": [public_job(job) for job in created]}

    @app.post("/jobs")
    def create_job(payload: dict[str, Any]) -> dict[str, Any]:
        title = normalize_title(str(payload.get("title", "")))
        if not title:
            raise HTTPException(status_code=400, detail="title 不能为空")
        job = store.create(title, payload.get("chat_id"))
        try:
            submit_to_station(job)
        except RuntimeError as exc:
            store.update(job["id"], status="failed", error=str(exc))
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return store.get(job["id"]) or job

    @app.post("/hooks/station")
    def station_hook(payload: dict[str, Any]) -> dict[str, Any]:
        if setting("HOOK_TOKEN") and payload.get("token") != setting("HOOK_TOKEN"):
            raise HTTPException(status_code=401, detail="invalid hook token")
        job_id = str(payload.get("job_id", ""))
        job = store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        file_name = Path(str(payload.get("file_name", ""))).name
        if not file_name or Path(file_name).suffix.lower() not in VIDEO_EXTENSIONS:
            raise HTTPException(status_code=400, detail="file_name 必须是视频文件")
        target = runner.inbox / f"{job_id}-{file_name}"
        source = Path(str(payload.get("source_path", "")))
        if not source.is_file():
            raise HTTPException(status_code=400, detail="source_path 不存在或不是文件")
        allowed_roots = [runner.inbox.parent.resolve(), Path("/downloads").resolve()]
        resolved_source = source.resolve()
        if not any(
            root == resolved_source or root in resolved_source.parents
            for root in allowed_roots
        ):
            raise HTTPException(status_code=400, detail="source_path 必须在媒体目录内")
        shutil.copy2(source, target)
        return {"accepted": True, "path": str(target)}

    @app.get("/api/share/{job_id}")
    def api_share(job_id: str, request: Request) -> dict[str, Any]:
        """给手机用的下载地址。

        优先用请求里的 Host（手机/局域网访问时天然正确）；
        从 127.0.0.1 打开时退回设置里的「手机访问地址」(BASE_URL)，
        最后才用容器自己猜的 IP（容器里的 IP 手机访问不到，只作兜底）。
        """
        job = store.get(job_id)
        if not job or job.get("status") != "completed" or not job.get("output_file"):
            raise HTTPException(status_code=404, detail="任务还没完成")

        host = request.headers.get("host", "")
        bare = host.split(":")[0].strip("[]")
        warning = ""
        configured = setting("BASE_URL", "").strip().rstrip("/")
        configured_host = urlparse(configured).netloc if configured else ""
        configured_bare = configured_host.split(":")[0]
        if not host or bare in {"127.0.0.1", "localhost", "::1"}:
            if configured_host and configured_bare not in {"127.0.0.1", "localhost"}:
                host = configured_host
            else:
                host = f"{lan_ip()}:{request.url.port or 8787}"
                warning = "「手机访问地址」还是 127.0.0.1，扫码后手机会打不开，请到 /setup 改成局域网地址"
        base = f"http://{host}"
        token = download_token(job_id)
        return {
            "url": f"{base}/s/{job_id}/{token}",
            "short": f"{base}/d/{short_code(job_id)}",
            "subtitle": f"{base}/s/{job_id}/{download_token(job_id, 'subtitle')}/subtitle",
            "host": host,
            "warning": warning,
        }

    @app.get("/api/qr/{job_id}")
    def api_qr(job_id: str, request: Request) -> Response:
        """任务完成后的下载二维码（SVG，手机扫一下就能下）。"""
        try:
            import qrcode
            import qrcode.image.svg
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="服务端缺少 qrcode 依赖") from exc
        info = api_share(job_id, request)
        image = qrcode.make(
            info["url"],
            image_factory=qrcode.image.svg.SvgPathImage,
            box_size=10,
            border=2,
        )
        buffer = io.BytesIO()
        image.save(buffer)
        return Response(
            content=buffer.getvalue(),
            media_type="image/svg+xml",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/download/{job_id}")
    def download(job_id: str):
        job = store.get(job_id)
        if not job or job["status"] != "completed" or not job.get("output_file"):
            raise HTTPException(status_code=404, detail="文件尚未完成")
        path = Path(job["output_file"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="输出文件不存在")
        return FileResponse(path, media_type="video/mp4", filename=path.name)

    @app.get("/d/{code}", response_class=HTMLResponse)
    def short_page(code: str):
        """手机上手输的短地址：/d/c8ba23，页面里点按钮就能下。"""
        job = find_job_by_short(store, code)
        if not job or job.get("status") != "completed":
            return HTMLResponse(
                "<meta charset='utf-8'><div style='font-family:system-ui;padding:40px;color:#1b2b22'>"
                "没有找到这个任务，或任务还没完成。</div>",
                status_code=404,
            )
        job_id = str(job["id"])
        title = html.escape(str(job.get("title") or job_id))
        video = f"/d/{code}/video"
        subtitle = f"/d/{code}/subtitle"
        subtitle_link = (
            f"<a class='btn ghost' href='{subtitle}'>下载字幕</a>" if job.get("subtitle_file") else ""
        )
        return HTMLResponse(f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>下载</title>
<style>
body{{margin:0;font:17px/1.6 -apple-system,"PingFang SC","Microsoft YaHei UI",sans-serif;color:#1b2b22;
background:linear-gradient(180deg,#f0f8f0,#dcefe0);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{background:#fff;border:1px solid rgba(27,58,42,.12);border-radius:18px;padding:26px 22px;max-width:520px;width:100%;
box-shadow:0 20px 50px -35px rgba(23,64,42,.6);text-align:center}}
h1{{font-size:18px;line-height:1.5;margin:0 0 6px;word-break:break-word}}
p{{color:#5f7568;font-size:14px;margin:0 0 20px}}
.btn{{display:block;padding:14px;border-radius:12px;background:linear-gradient(135deg,#4bb87c,#2f8f5b);color:#fff;
text-decoration:none;font-weight:700;margin-bottom:10px}}
.btn.ghost{{background:#f1f6f2;color:#1f6b43;border:1px solid rgba(27,58,42,.14)}}
.tip{{font-size:12.5px;color:#7c9184;margin-top:14px}}
</style></head><body><div class="card">
<h1>{title}</h1><p>{job_id}</p>
<a class="btn" href="{video}">下载视频</a>{subtitle_link}
<div class="tip">下载时请保持屏幕常亮，不要切到后台。</div>
</div></body></html>""")

    @app.api_route("/d/{code}/video", methods=["GET", "HEAD"])
    def short_download(code: str):
        job = find_job_by_short(store, code)
        if not job or job.get("status") != "completed" or not job.get("output_file"):
            raise HTTPException(status_code=404, detail="文件尚未完成")
        path = Path(job["output_file"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="输出文件不存在")
        return FileResponse(path, media_type="video/mp4", filename=path.name)

    @app.api_route("/d/{code}/subtitle", methods=["GET", "HEAD"])
    def short_subtitle(code: str):
        job = find_job_by_short(store, code)
        if not job or not job.get("subtitle_file"):
            raise HTTPException(status_code=404, detail="字幕文件不存在")
        path = Path(job["subtitle_file"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="字幕文件不存在")
        return FileResponse(path, media_type="application/x-subrip", filename=path.name)

    @app.api_route("/s/{job_id}/{token}", methods=["GET", "HEAD"])
    def signed_download(job_id: str, token: str):
        """带令牌的下载链接：手机浏览器直接下，不用输账号密码。"""
        if not hmac.compare_digest(token, download_token(job_id)):
            raise HTTPException(status_code=403, detail="链接无效或已失效")
        job = store.get(job_id)
        if not job or job.get("status") != "completed" or not job.get("output_file"):
            raise HTTPException(status_code=404, detail="文件尚未完成")
        path = Path(job["output_file"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="输出文件不存在")
        return FileResponse(path, media_type="video/mp4", filename=path.name)

    @app.api_route("/s/{job_id}/{token}/subtitle", methods=["GET", "HEAD"])
    def signed_subtitle(job_id: str, token: str):
        if not hmac.compare_digest(token, download_token(job_id, "subtitle")):
            raise HTTPException(status_code=403, detail="链接无效或已失效")
        job = store.get(job_id)
        if not job or not job.get("subtitle_file"):
            raise HTTPException(status_code=404, detail="字幕文件不存在")
        path = Path(job["subtitle_file"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="字幕文件不存在")
        return FileResponse(path, media_type="application/x-subrip", filename=path.name)

    @app.get("/subtitle/{job_id}")
    def download_subtitle(job_id: str):
        job = store.get(job_id)
        if not job or not job.get("subtitle_file"):
            raise HTTPException(status_code=404, detail="字幕文件不存在")
        path = Path(job["subtitle_file"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="字幕文件不存在")
        return FileResponse(
            path,
            media_type="application/x-subrip",
            filename=path.name,
        )

    return app


def setup_page(values: dict[str, str], saved: bool = False) -> str:
    values = {key: html.escape(str(value), quote=True) for key, value in values.items()}
    token_set = bool(values.get("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN"))
    prowlarr_set = bool(
        values.get("PROWLARR_API_KEY") or os.getenv("PROWLARR_API_KEY")
    )
    qbt_set = bool(
        values.get("QBITTORRENT_PASSWORD") or os.getenv("QBITTORRENT_PASSWORD")
    )
    provider = "ollama" if "11434" in values.get("TRANSLATION_BASE_URL", os.getenv("TRANSLATION_BASE_URL", "")) else "custom"
    message = (
        "配置已保存。搜索与下载配置会立即生效；Telegram Token 和翻译配置需要重启 worker 后生效。"
        if saved
        else ""
    )
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>影片自动化 · 设置</title><style>
:root{{
  color-scheme:dark;
  --bg:#070a11;--ink:#f4efe4;--muted:#a9a396;--line:rgba(216,180,108,.2);
  --gold:#d4af6a;--gold-2:#f4d99a;--red:#e47c7c;
  --serif:"Songti SC","STSong","Noto Serif CJK SC","Iowan Old Style",Palatino,Georgia,serif;
  --sans:"SF Pro Display",-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
}}
*{{box-sizing:border-box}}
html{{background:#060910;scroll-behavior:smooth}}
body{{margin:0;color:var(--ink);font:15px/1.65 var(--sans);min-height:100vh;background:radial-gradient(1100px 620px at 12% -12%,rgba(96,78,150,.32),transparent 62%),radial-gradient(900px 560px at 100% -4%,rgba(183,140,68,.15),transparent 58%),linear-gradient(180deg,#060910,#090d16 42%,#060910);-webkit-font-smoothing:antialiased}}
body::before{{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;opacity:.10;background-image:repeating-linear-gradient(0deg,rgba(255,255,255,.055) 0 1px,transparent 1px 4px);mix-blend-mode:soft-light}}
body::after{{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;background:radial-gradient(ellipse at 50% 20%,transparent 35%,rgba(0,0,0,.55) 100%)}}
a{{color:var(--gold-2);text-decoration:none}}
.topbar{{position:sticky;top:0;z-index:10;background:rgba(6,9,16,.78);border-bottom:1px solid rgba(216,180,108,.16);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}}
.topbar::before{{content:"";position:absolute;left:0;right:0;top:0;height:1px;background:linear-gradient(90deg,transparent,rgba(244,217,154,.85),transparent)}}
.topbar-inner{{max-width:900px;margin:0 auto;padding:14px 22px;display:flex;align-items:center;gap:18px}}
.brand{{display:flex;align-items:center;gap:12px;color:var(--ink)}}
.brand-mark{{width:40px;height:40px;border-radius:11px;display:grid;place-items:center;color:#1a1206;font-weight:800;font-size:19px;font-family:var(--serif);background:linear-gradient(135deg,#f7e2ad,#c69b4f 55%,#8f682d);box-shadow:0 0 0 1px rgba(255,235,190,.35),0 10px 28px -8px rgba(212,175,106,.55)}}
.brand-text{{display:flex;flex-direction:column;line-height:1.15}}
.brand-text b{{font-family:var(--serif);font-size:17px;letter-spacing:.12em;font-weight:600}}
.brand-text small{{font-size:8.5px;letter-spacing:.28em;color:rgba(244,217,154,.62);font-weight:700;margin-top:2px}}
.nav{{display:flex;gap:4px;margin-left:auto;font-size:13.5px}}
.nav a{{padding:9px 15px;border-radius:9px;color:rgba(244,239,228,.6);font-weight:600;letter-spacing:.04em}}
.nav a:hover{{color:var(--gold-2);background:rgba(216,180,108,.07)}}
.nav a.active{{color:#1a1206;background:linear-gradient(135deg,#f0d596,#c69b4f);box-shadow:0 6px 18px -8px rgba(212,175,106,.7)}}
.setup-main{{position:relative;z-index:1;max-width:900px;margin:0 auto;padding:38px 22px 64px}}
.hero{{padding:6px 4px 24px}}
.eyebrow{{display:inline-flex;align-items:center;gap:12px;font-size:9.5px;font-weight:800;letter-spacing:.32em;color:var(--gold);margin-bottom:14px}}
.eyebrow::before{{content:"";width:42px;height:1px;background:linear-gradient(90deg,transparent,var(--gold))}}
.hero h1{{font-family:var(--serif);font-weight:600;font-size:clamp(30px,4.6vw,46px);line-height:1.1;letter-spacing:.01em;margin:0 0 12px;background:linear-gradient(180deg,#fffdf6,#eee2cb 55%,#b99a5e);-webkit-background-clip:text;background-clip:text;color:transparent}}
.hero p{{margin:0;max-width:680px;color:var(--muted);font-size:13.5px;line-height:1.8}}
.panel{{position:relative;overflow:hidden;background:linear-gradient(160deg,rgba(23,29,45,.92),rgba(9,13,22,.94));border:1px solid var(--line);border-radius:20px;padding:26px;box-shadow:0 40px 100px -48px #000,inset 0 1px 0 rgba(255,255,255,.055)}}
.panel::before{{content:"";position:absolute;left:0;right:0;top:0;height:1px;background:linear-gradient(90deg,transparent,rgba(244,217,154,.55),transparent)}}
.step{{background:rgba(0,0,0,.2);border:1px solid rgba(255,255,255,.07);border-radius:14px;padding:18px;margin:15px 0}}
.step h2{{font-family:var(--serif);font-size:19px;letter-spacing:.04em;font-weight:600;margin:0 0 4px;color:#fbf7ee}}
label{{display:block;font-weight:650;margin:15px 0 7px;font-size:12px;letter-spacing:.03em;color:rgba(244,239,228,.82)}}
input,select{{width:100%;box-sizing:border-box;border:1px solid rgba(216,180,108,.22);border-radius:10px;padding:11px 12px;font-size:13.5px;background:rgba(0,0,0,.28);color:var(--ink);outline:0;transition:.18s}}
input:focus,select:focus{{border-color:rgba(244,217,154,.65);box-shadow:0 0 0 3px rgba(212,175,106,.09)}}
input::placeholder{{color:rgba(169,163,150,.5)}}
input[type=checkbox]{{width:auto;accent-color:var(--gold)}}
button{{width:100%;margin-top:18px;background:linear-gradient(135deg,#f4dca2,#c99d50 60%,#9e7434);color:#1b1307;border:0;border-radius:11px;padding:13px 18px;font-weight:800;font-size:13px;letter-spacing:.08em;cursor:pointer;box-shadow:0 12px 28px -14px rgba(212,175,106,.7),inset 0 1px 0 rgba(255,255,255,.4)}}
button:hover{{filter:brightness(1.05);transform:translateY(-1px)}}
.hint{{font-size:11.5px;color:var(--muted);margin-top:6px;line-height:1.65}}
code{{background:rgba(255,255,255,.055);padding:2px 5px;border-radius:4px;font-size:10.5px;color:#e8d9b8}}
.ok{{background:rgba(95,211,160,.08);border:1px solid rgba(95,211,160,.25);color:#7fe4b8;padding:12px 14px;border-radius:10px;margin:0 0 16px;font-size:12.5px}}
.setup-footer{{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;color:rgba(169,163,150,.45);font-size:10.5px;letter-spacing:.06em;padding:18px 4px 0}}
.setup-footer a{{color:rgba(212,175,106,.7);font-weight:600}}
@media(max-width:650px){{.setup-main{{padding:24px 12px 48px}}.panel{{padding:18px;border-radius:16px}}.topbar-inner{{padding:11px 14px}}.brand-text small{{display:none}}.step{{padding:15px}}}}
@media(prefers-reduced-motion:reduce){{*{{transition:none!important;scroll-behavior:auto!important}}}}

:root{{color-scheme:dark;--bg:#0a0c11;--ink:#e9ecf2;--muted:#98a1b2;--line:rgba(255,255,255,.09);--gold:#8ab4ff;--gold-2:#cfe0ff;--red:#e47c7c;
  --serif:"SF Pro Display","PingFang SC","HarmonyOS Sans SC","Microsoft YaHei UI",-apple-system,sans-serif;
  --sans:"SF Pro Display","PingFang SC","HarmonyOS Sans SC","MiSans","Microsoft YaHei UI",-apple-system,BlinkMacSystemFont,sans-serif;}}
html{{background:#0a0c11}}
body{{font:16px/1.7 var(--sans);color:#e9ecf2;letter-spacing:.01em;
  background:radial-gradient(900px 520px at 8% -10%,rgba(96,124,204,.15),transparent 60%),radial-gradient(800px 480px at 100% 0%,rgba(120,96,180,.09),transparent 58%),linear-gradient(180deg,#0a0c11,#0d1017 48%,#0a0c11)}}
body::before{{opacity:.05}}
body::after{{background:radial-gradient(ellipse at 50% 0%,transparent 45%,rgba(0,0,0,.42) 100%)}}
a{{color:var(--gold-2)}}
.topbar{{background:rgba(10,12,17,.82);border-bottom:1px solid rgba(255,255,255,.07)}}
.topbar::before{{background:linear-gradient(90deg,transparent,rgba(138,180,255,.5),transparent)}}
.brand-mark{{background:linear-gradient(135deg,#b9d0ff,#7ba0f0 55%,#4a67b8);color:#0a1020;font-family:var(--sans);box-shadow:0 0 0 1px rgba(190,214,255,.28),0 10px 26px -10px rgba(110,150,255,.45)}}
.brand-text b{{font-family:var(--sans);letter-spacing:.06em;font-weight:640}}
.brand-text small{{color:rgba(160,185,240,.7)}}
.nav a{{color:rgba(233,236,242,.62)}}
.nav a:hover{{color:var(--gold-2);background:rgba(138,180,255,.08)}}
.nav a.active{{color:#0a1020;background:linear-gradient(135deg,#c6d9ff,#86a8f5);box-shadow:none}}
.eyebrow{{color:var(--gold);letter-spacing:.26em}}
.eyebrow::before{{background:linear-gradient(90deg,transparent,var(--gold))}}
.hero h1{{font-family:var(--sans);font-weight:640;letter-spacing:-.015em;background:linear-gradient(180deg,#fff,#dbe4f5 60%,#93a4c2);-webkit-background-clip:text;background-clip:text;color:transparent}}
.hero p{{color:#98a1b2}}
.panel{{background:linear-gradient(180deg,rgba(18,21,28,.94),rgba(12,15,21,.96));border:1px solid rgba(255,255,255,.08);border-radius:18px;box-shadow:0 40px 90px -60px #000,inset 0 1px 0 rgba(255,255,255,.05)}}
.panel::before{{background:linear-gradient(90deg,transparent,rgba(138,180,255,.4),transparent)}}
.step{{background:rgba(255,255,255,.022);border:1px solid rgba(255,255,255,.07);border-radius:14px}}
.step h2{{font-family:var(--sans);font-weight:620;font-size:17px;letter-spacing:0;color:#eef1f7}}
label{{color:rgba(233,236,242,.82);font-weight:600}}
input,select{{border:1px solid rgba(255,255,255,.11);border-radius:10px;background:rgba(0,0,0,.3);color:#e9ecf2;font-size:14px}}
input:focus,select:focus{{border-color:rgba(138,180,255,.55);box-shadow:0 0 0 3px rgba(138,180,255,.1)}}
input::placeholder{{color:rgba(152,161,178,.55)}}
input[type=checkbox]{{accent-color:#8ab4ff}}
textarea{{width:100%;box-sizing:border-box;border:1px solid rgba(255,255,255,.11);border-radius:10px;padding:11px 12px;background:rgba(0,0,0,.3);color:#e9ecf2;font:inherit;font-size:13.5px;line-height:1.7;outline:0;resize:vertical}}
textarea:focus{{border-color:rgba(138,180,255,.55);box-shadow:0 0 0 3px rgba(138,180,255,.1)}}
button{{background:linear-gradient(135deg,#b9d0ff,#7ba0f0 60%,#5f86d8);color:#0a1020;border-radius:11px;box-shadow:0 12px 28px -14px rgba(110,150,255,.5)}}
button:hover{{filter:brightness(1.04)}}
.hint{{color:#98a1b2}}
code{{background:rgba(138,180,255,.1);color:#bcd4ff}}
.ok{{background:rgba(95,211,160,.08);border-color:rgba(95,211,160,.25);color:#84e0b6}}
.setup-footer{{color:rgba(150,160,180,.5)}}
.setup-footer a{{color:rgba(140,170,230,.75)}}

:root{{color-scheme:light;--bg:#eaf5ea;--ink:#1b2b22;--muted:#5f7568;--line:rgba(27,58,42,.12);--gold:#2f8f5b;--gold-2:#1f6b43;--red:#c14b4b}}
html{{background:#eaf5ea}}
body{{color:#1b2b22;background:radial-gradient(900px 520px at 8% -10%,rgba(120,200,150,.30),transparent 62%),radial-gradient(760px 480px at 100% 0%,rgba(160,215,180,.24),transparent 58%),linear-gradient(180deg,#f0f8f0,#e6f3e8 46%,#dcefe0)}}
body::before{{opacity:0}}
body::after{{background:radial-gradient(ellipse at 50% 0%,transparent 55%,rgba(120,160,135,.12) 100%)}}
a{{color:#1f6b43}}
.topbar{{background:rgba(255,255,255,.82);border-bottom:1px solid rgba(27,58,42,.12)}}
.topbar::before{{background:linear-gradient(90deg,transparent,rgba(47,143,91,.35),transparent)}}
.brand-mark{{background:linear-gradient(135deg,#5fc38b,#2f8f5b 60%,#1f6b43);color:#f4fff8;box-shadow:0 8px 20px -10px rgba(47,143,91,.6)}}
.brand-text b{{color:#1b2b22}}
.brand-text small{{color:rgba(47,143,91,.75)}}
.nav a{{color:rgba(27,43,34,.62)}}
.nav a:hover{{color:#1f6b43;background:rgba(47,143,91,.09)}}
.nav a.active{{color:#fff;background:linear-gradient(135deg,#4bb87c,#2f8f5b);box-shadow:none}}
.eyebrow{{color:#2f8f5b}}
.eyebrow::before{{background:linear-gradient(90deg,transparent,#2f8f5b)}}
.hero h1{{background:linear-gradient(180deg,#1b2b22 0%,#25402f 55%,#2f8f5b 100%);-webkit-background-clip:text;background-clip:text;color:transparent}}
.hero p{{color:#5f7568}}
.panel{{background:#fff;border:1px solid rgba(27,58,42,.1);box-shadow:0 18px 50px -34px rgba(23,64,42,.45),0 2px 6px -4px rgba(23,64,42,.2)}}
.panel::before{{background:linear-gradient(90deg,transparent,rgba(47,143,91,.3),transparent)}}
.step{{background:#f7fbf8;border:1px solid rgba(27,58,42,.09)}}
.step h2{{color:#16261d}}
label{{color:#33503f}}
input,select{{background:#fff;border:1px solid rgba(27,58,42,.16);color:#1b2b22}}
input:focus,select:focus{{border-color:rgba(47,143,91,.6);box-shadow:0 0 0 3px rgba(47,143,91,.12)}}
input::placeholder{{color:rgba(95,117,104,.6)}}
input[type=checkbox]{{accent-color:#2f8f5b}}
textarea{{background:#fff;border:1px solid rgba(27,58,42,.16);color:#1b2b22}}
textarea:focus{{border-color:rgba(47,143,91,.6);box-shadow:0 0 0 3px rgba(47,143,91,.12)}}
button{{background:linear-gradient(135deg,#4bb87c,#2f8f5b 60%,#1f6b43);color:#fff;box-shadow:0 10px 24px -14px rgba(47,143,91,.65)}}
.hint{{color:#5f7568}}
code{{background:rgba(47,143,91,.1);color:#1f6b43}}
.ok{{background:rgba(47,156,114,.1);border:1px solid rgba(47,156,114,.3);color:#1f7a4f}}
.setup-footer{{color:rgba(95,117,104,.75)}}
.setup-footer a{{color:#2f8f5b}}

.step{{padding:18px}}
.step>summary{{margin:-18px -18px 0;padding:16px 18px;cursor:pointer;list-style:none;display:flex;align-items:center;gap:10px;font-size:16px;font-weight:620;color:#16261d}}
.step[open]>summary{{border-bottom:1px solid rgba(27,58,42,.08);margin-bottom:14px}}
.step>summary h2{{margin:0;font-size:inherit;font-weight:inherit;display:inline}}
.step>summary::-webkit-details-marker{{display:none}}
.step>summary::after{{content:"展开";margin-left:auto;font-size:12px;font-weight:500;color:#2f8f5b}}
.step[open]>summary::after{{content:"收起"}}
body{{font-size:16.5px}}
label{{font-size:13px}}
.hint{{font-size:12.5px}}
input,select,textarea{{font-size:14.5px}}
</style></head><body>
<header class="topbar"><div class="topbar-inner">
<a class="brand" href="/"><span class="brand-mark">影</span><span class="brand-text"><b>影片自动化</b><small>MEDIA AUTOMATION</small></span></a>
<nav class="nav"><a href="/">搜索</a><a class="active" href="/setup">设置</a></nav>
</div></header>
<main class="setup-main">
<section class="hero"><span class="eyebrow">SETTINGS</span><h1>配置你的自动化流程</h1><p>第一次使用填一次即可。Token 和密码只保存在本机，页面不会回显已保存的密钥。</p></section>
<div class="panel">
{f'<div class="ok">{message}</div>' if message else ''}
<form method="post" action="/setup">
<details class="step"><summary><h2>1. Telegram</h2></summary><label>Bot Token</label><input name="telegram_token" type="password" placeholder="{'已保存，留空即可' if token_set else '粘贴 BotFather 返回的 Token'}" autocomplete="off"><div class="hint">在 @BotFather 用 /newbot 创建。不要把 Token 发到聊天中。</div>
<label>允许使用的 Telegram 用户 ID（可选）</label><input name="allowed_user_ids" value="{values.get('TELEGRAM_ALLOWED_USER_IDS', os.getenv('TELEGRAM_ALLOWED_USER_IDS',''))}" placeholder="留空表示不限制，例如 123456789"><div class="hint">强烈建议只填你自己的数字用户 ID，否则任何人找到机器人都能建任务。</div></details>
<details class="step" open><summary><h2>2. 搜索与下载</h2></summary><label>Prowlarr 地址</label><input name="prowlarr_url" value="{values.get('PROWLARR_URL', os.getenv('PROWLARR_URL','http://prowlarr:9696'))}" placeholder="http://prowlarr:9696">
<div class="hint">Docker 内填 <code>http://prowlarr:9696</code>；直接跑 Python 时填 <code>http://127.0.0.1:9696</code>。索引器用 <code>docker exec media-automation-worker python indexers.py add</code> 批量接入（或打开 <a href="http://127.0.0.1:9696" target="_blank" rel="noreferrer">Prowlarr</a> 手动添加），再到 Settings → General 复制 API Key。</div>
<label>Prowlarr API Key</label><input name="prowlarr_api_key" type="password" value="" placeholder="{'已保存，留空即可' if prowlarr_set else '粘贴 Prowlarr 的 API Key'}" autocomplete="off">
<label>qBittorrent 地址</label><input name="qbittorrent_url" value="{values.get('QBITTORRENT_URL', os.getenv('QBITTORRENT_URL','http://qbittorrent:8081'))}" placeholder="http://qbittorrent:8081">
<div class="hint">首次启动后打开 <a href="http://127.0.0.1:8081" target="_blank" rel="noreferrer">qBittorrent</a>，用容器日志里的临时密码登录并修改密码，然后把新密码填到这里。</div>
<label>qBittorrent 用户名</label><input name="qbittorrent_username" value="{values.get('QBITTORRENT_USERNAME', os.getenv('QBITTORRENT_USERNAME','admin'))}" placeholder="admin">
<label>qBittorrent 密码</label><input name="qbittorrent_password" type="password" value="" placeholder="{'已保存，留空即可' if qbt_set else '填写 qBittorrent 密码'}" autocomplete="off"></details>
<details class="step" open><summary><h2>3. 翻译方式</h2></summary><label>翻译服务</label><select name="translation_provider" id="provider" onchange="preset()"><option value="ollama" {'selected' if provider == 'ollama' else ''}>Ollama 本地模型</option><option value="deepseek">DeepSeek API</option><option value="custom" {'selected' if provider == 'custom' else ''}>其他 OpenAI 兼容接口</option></select>
<label>接口地址</label><input id="base" name="translation_base_url" value="{values.get('TRANSLATION_BASE_URL', os.getenv('TRANSLATION_BASE_URL',''))}" placeholder="http://host.docker.internal:11434/v1">
<label>API Key</label><input id="key" name="translation_api_key" type="password" value="" placeholder="{'已保存，留空即可' if values.get('TRANSLATION_API_KEY', os.getenv('TRANSLATION_API_KEY','')) else 'Ollama 可填 local'}" autocomplete="off">
<label>模型名</label><input id="model" name="translation_model" value="{values.get('TRANSLATION_MODEL', os.getenv('TRANSLATION_MODEL',''))}" placeholder="qwen2.5:7b">
<label>输入价格（每百万 token，可选）</label><input name="translation_price_input" value="{values.get('TRANSLATION_PRICE_INPUT', os.getenv('TRANSLATION_PRICE_INPUT',''))}" placeholder="例如 0.175，留空则只显示 token 不显示金额" inputmode="decimal">
<label>输出价格（每百万 token，可选）</label><input name="translation_price_output" value="{values.get('TRANSLATION_PRICE_OUTPUT', os.getenv('TRANSLATION_PRICE_OUTPUT',''))}" placeholder="例如 1.05，按服务商报价填" inputmode="decimal">
<label>缓存命中价格（每百万 token，可选）</label><input name="translation_price_cache" value="{values.get('TRANSLATION_PRICE_CACHE', os.getenv('TRANSLATION_PRICE_CACHE',''))}" placeholder="例如 0.0175，留空按输入价格算" inputmode="decimal">
<label>上下文 &gt;272K 时：输入 / 输出 / 缓存价（可选）</label><div style="display:flex;gap:8px;flex-wrap:wrap"><input name="translation_price_input_high" value="{values.get('TRANSLATION_PRICE_INPUT_HIGH', os.getenv('TRANSLATION_PRICE_INPUT_HIGH',''))}" placeholder="0.35" inputmode="decimal" style="flex:1"><input name="translation_price_output_high" value="{values.get('TRANSLATION_PRICE_OUTPUT_HIGH', os.getenv('TRANSLATION_PRICE_OUTPUT_HIGH',''))}" placeholder="1.575" inputmode="decimal" style="flex:1"><input name="translation_price_cache_high" value="{values.get('TRANSLATION_PRICE_CACHE_HIGH', os.getenv('TRANSLATION_PRICE_CACHE_HIGH',''))}" placeholder="0.035" inputmode="decimal" style="flex:1"></div>
<label>计价货币</label><select name="translation_price_currency"><option value="USD" {'selected' if values.get('TRANSLATION_PRICE_CURRENCY', os.getenv('TRANSLATION_PRICE_CURRENCY','USD')) != 'CNY' else ''}>USD $</option><option value="CNY" {'selected' if values.get('TRANSLATION_PRICE_CURRENCY', os.getenv('TRANSLATION_PRICE_CURRENCY','USD')) == 'CNY' else ''}>CNY ¥</option></select>
<label>价格档位</label><select name="translation_price_profile"><option value="">保持当前价格</option><option value="0.035">0.035x 档（0.175 / 1.05 / 0.035）</option><option value="0.06">0.06x 档（0.30 / 1.80 / 0.06）</option></select>
<div class="hint">不知道自己是哪档就都试一次：跑完一部片，把卡片上的「约 $x」除以 token 数，和两档报价对一下即可。超过 272K 上下文时接口按 2 倍计价，程序会自动识别并翻倍。</div>
<label><input type="checkbox" name="translate_titles" value="true" {'checked' if values.get('TRANSLATE_TITLES', os.getenv('TRANSLATE_TITLES','true')) != 'false' else ''} style="width:auto;margin-right:8px">把种子标题翻译成中文显示</label><div class="hint">关掉后搜索结果只显示原文，能省掉每次搜索的翻译等待。</div>
<label><input type="checkbox" name="translation_polish" value="true" {'checked' if values.get('TRANSLATION_POLISH', os.getenv('TRANSLATION_POLISH','true')) != 'false' else ''} style="width:auto;margin-right:8px">两遍翻译：先初译，再让模型润色一遍</label><div class="hint">更接近字幕组成品（口语化、称呼统一），但翻译耗时和 token 约翻倍；一部片通常还是几毛钱。</div>
<label>术语/称呼表（可选，每行「原文=译文」）</label><textarea name="translation_glossary" rows="4" placeholder="マジックミラー号=魔镜号&#10;お兄ちゃん=哥哥&#10;先輩=前辈">{values.get('TRANSLATION_GLOSSARY','')}</textarea><div class="hint">命中这些词的台词会强制按你的译法翻，保证全片称呼一致。</div>
<div class="hint">Ollama 不上传影片；DeepSeek/OpenAI 只接收字幕文本，不接收视频文件。填了价格后，任务完成后会显示这次翻译的 token 用量和预估费用（按输入/输出/缓存分别计价）。</div></details>
<details class="step"><summary><h2>4. 输出</h2></summary><label><input type="checkbox" name="burn_subtitles" value="true" {'checked' if values.get('BURN_SUBTITLES', os.getenv('BURN_SUBTITLES','true')) == 'true' else ''} style="width:auto;margin-right:8px">生成可保存到 iPhone 相册的压制字幕 MP4</label><div class="hint">关闭后只生成外挂字幕，节省处理时间。</div>
<label><input type="checkbox" name="subtitle_ocr" value="true" {'checked' if values.get('SUBTITLE_OCR', os.getenv('SUBTITLE_OCR','true')) != 'false' else ''} style="width:auto;margin-right:8px">没有对白的空档里，抽帧识别画面上的日文字幕</label><div class="hint">只检查 whisper 识别不到对白的空档（≥4 秒），每段抽 1~2 帧发给模型看，一部片通常几十帧、花费几分钱；会多花 1~3 分钟。需要模型支持图片输入。</div>
<label><input type="checkbox" name="bilingual_subtitles" value="true" {'checked' if values.get('BILINGUAL_SUBTITLES', os.getenv('BILINGUAL_SUBTITLES','false')) == 'true' else ''} style="width:auto;margin-right:8px">双语字幕（日文原文 + 中文两行）</label><div class="hint">外挂字幕和压制视频都会显示两行，方便对照校对。</div>
<label>手机访问地址</label><input name="base_url" value="{values.get('BASE_URL', os.getenv('BASE_URL','http://127.0.0.1:8787'))}" placeholder="http://192.168.1.20:8787"><div class="hint">填这台电脑在局域网中的 IP，Telegram 才能发送可下载链接。</div>
</details>
<button type="submit">保存配置</button>
</form>
</div>
<footer class="setup-footer"><a href="/">← 返回搜索与任务</a><span>配置保存在 data/settings.json</span></footer>
</main>
<script>
function preset(){{const p=document.getElementById('provider').value,b=document.getElementById('base'),k=document.getElementById('key'),m=document.getElementById('model');if(p==='ollama'){{b.value='http://host.docker.internal:11434/v1';k.value='local';m.value='qwen2.5:7b'}}else if(p==='deepseek'){{b.value='https://api.deepseek.com/v1';k.value='';m.value='deepseek-chat'}}}}
</script></body></html>'''



def main() -> None:
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    inbox = Path(os.getenv("INBOX_DIR", "/media/inbox"))
    output = Path(os.getenv("OUTPUT_DIR", "/media/output"))
    settings_store = SettingsStore(data_dir / "settings.json")
    apply_settings(settings_store.load())
    store = JobStore(data_dir / "jobs.json")
    search_service = SearchService(setting)
    downloads = DownloadManager(store, inbox, setting, search_service)
    runner = JobRunner(store, inbox, SubtitlePipeline(output), downloads)
    threading.Thread(target=runner.loop, name="job-scanner", daemon=True).start()
    import uvicorn
    api = create_api(store, runner, settings_store, search_service, downloads)
    if setting("TELEGRAM_BOT_TOKEN"):
        # uvicorn may install uvloop in the calling thread. Keep the Telegram
        # polling loop in the main thread and run the small HTTP API beside it.
        asyncio.set_event_loop(asyncio.new_event_loop())
        threading.Thread(
            target=lambda: uvicorn.run(api, host="0.0.0.0", port=8787, log_level="info", loop="asyncio"),
            name="http-api",
            daemon=True,
        ).start()
        telegram_loop(store, search_service, downloads)
    else:
        uvicorn.run(api, host="0.0.0.0", port=8787, log_level="info")


if __name__ == "__main__" and not os.getenv("MEDIA_AUTOMATION_TESTING"):
    main()
