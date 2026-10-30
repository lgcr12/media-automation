import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("MEDIA_AUTOMATION_TESTING", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app import (
    DownloadManager,
    JobRunner,
    JobStore,
    SettingsStore,
    SubtitlePipeline,
    TranslationClient,
    archive_outputs,
    choose_input_file,
    create_api,
    format_srt_timestamp,
    normalize_title,
    setup_page,
    start_downloads,
    translation_usage,
    parse_glossary,
)
from search import SearchService, normalize_result


INFO_HASH = "a" * 40
MAGNET = f"magnet:?xt=urn:btih:{INFO_HASH}&dn=Movie"


class TranslationClientTest(unittest.TestCase):
    @staticmethod
    def make_client() -> TranslationClient:
        client = TranslationClient.__new__(TranslationClient)
        client.base_url = "http://example.invalid/v1"
        client.api_key = "key"
        client.model = "model"
        client.usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "calls": 0,
        }
        client.cost = 0.0
        client._usage_lock = threading.Lock()
        return client

    def test_split_retry_when_count_differs(self):
        client = self.make_client()
        calls: list[int] = []

        def fake(texts, context=None, glossary=None):
            calls.append(len(texts))
            if len(texts) > 2:
                return list(texts[:-1])  # 模拟模型合并/漏掉一条
            return [f"译:{text}" for text in texts]

        client._request_translations = fake
        with patch.dict(os.environ, {"TRANSLATION_POLISH": "false"}):
            result = client.translate(["a", "b", "c", "d"])
        self.assertEqual(result, ["译:a", "译:b", "译:c", "译:d"])
        self.assertEqual(calls, [4, 2, 2])

    def test_single_line_falls_back_to_original(self):
        client = self.make_client()
        client._request_translations = lambda texts, context=None, glossary=None: []
        with patch.dict(os.environ, {"TRANSLATION_POLISH": "false"}):
            self.assertEqual(client.translate([" そのまま "]), [" そのまま "])

    def test_translation_error_is_contained(self):
        client = self.make_client()

        def boom(texts, context=None, glossary=None):
            raise RuntimeError("翻译服务不可用")

        client._request_translations = boom
        with patch.dict(os.environ, {"TRANSLATION_POLISH": "false"}):
            self.assertEqual(client.translate(["あ", "い"]), ["あ", "い"])

    def test_context_is_passed_to_next_batch(self):
        client = self.make_client()
        seen_contexts: list[list[dict[str, str]]] = []

        def fake(texts, context=None, glossary=None):
            seen_contexts.append(list(context or []))
            return [f"译:{text}" for text in texts]

        client._request_translations = fake
        lines = [f"第{i}句" for i in range(60)]
        with patch.dict(os.environ, {"TRANSLATION_POLISH": "false"}):
            result = client.translate(lines)
        self.assertEqual(len(result), 60)
        self.assertEqual(seen_contexts[0], [])
        self.assertTrue(seen_contexts[1], "第二批应带上文参考")
        self.assertEqual(seen_contexts[1][-1]["ja"], "第49句")

    def test_usage_is_accumulated(self):
        client = self.make_client()
        client._record_usage({"usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})
        client._record_usage({"usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}})
        self.assertEqual(client.usage["total_tokens"], 180)
        self.assertEqual(client.usage["calls"], 2)

    def test_high_tier_uses_explicit_prices(self):
        client = self.make_client()
        with patch.dict(
            os.environ,
            {
                "TRANSLATION_PRICE_INPUT": "0.175",
                "TRANSLATION_PRICE_OUTPUT": "1.05",
                "TRANSLATION_PRICE_CACHE": "0.0175",
                "TRANSLATION_PRICE_INPUT_HIGH": "0.35",
                "TRANSLATION_PRICE_OUTPUT_HIGH": "1.575",
                "TRANSLATION_PRICE_CACHE_HIGH": "0.035",
            },
        ):
            client._record_usage(
                {"usage": {"prompt_tokens": 300_000, "completion_tokens": 10_000, "total_tokens": 310_000}}
            )
        # 300K × $0.35/M + 10K × $1.575/M = 0.105 + 0.01575
        self.assertAlmostEqual(client.cost, 0.12075, places=6)

    def test_high_context_tier_doubles_cost(self):
        client = self.make_client()
        with patch.dict(
            os.environ,
            {
                "TRANSLATION_PRICE_INPUT": "1",
                "TRANSLATION_PRICE_OUTPUT": "10",
                "TRANSLATION_PRICE_CACHE": "1",
            },
        ):
            client._record_usage(
                {"usage": {"prompt_tokens": 300_000, "completion_tokens": 0, "total_tokens": 300_000}}
            )
        # 300K 输入 × $1/M，超过 272K 按 2 倍 → 0.6
        self.assertAlmostEqual(client.cost, 0.6, places=6)

    def test_polish_falls_back_to_draft(self):
        client = self.make_client()
        client._request_polish = lambda *args, **kwargs: ["只有一条"]
        self.assertEqual(client._polish_batch(["a", "b"], ["甲", "乙"]), ["甲", "乙"])

    def test_polish_used_when_counts_match(self):
        client = self.make_client()
        client._request_polish = lambda *args, **kwargs: ["润甲", "润乙"]
        self.assertEqual(client._polish_batch(["a", "b"], ["甲", "乙"]), ["润甲", "润乙"])


class TranscriptCacheTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "job.json"
            segments = [
                SimpleNamespace(start=0.0, end=1.5, text="こんにちは"),
                SimpleNamespace(start=1.5, end=3.0, text="さようなら"),
            ]
            SubtitlePipeline._save_transcript(path, segments)
            loaded = SubtitlePipeline._load_transcript(path)
            self.assertEqual([item["text"] for item in loaded], ["こんにちは", "さようなら"])
            self.assertEqual(loaded[1]["end"], 3.0)

    def test_missing_or_broken_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            self.assertEqual(SubtitlePipeline._load_transcript(path), [])
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(SubtitlePipeline._load_transcript(path), [])


class ArchiveTest(unittest.TestCase):
    def test_copies_outputs_into_title_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "archive"
            archive.mkdir()
            video = root / "demo.mp4"
            video.write_bytes(b"video")
            subtitle = root / "demo.srt"
            subtitle.write_text("1", encoding="utf-8")
            with patch.dict(os.environ, {"ARCHIVE_DIR": str(archive), "ARCHIVE_DISPLAY": ""}):
                result = archive_outputs({"id": "job-123456", "title": "a/b:c"}, [video, subtitle])
            self.assertIsNotNone(result)
            target = archive / "a_b_c-123456"
            self.assertTrue(target.is_dir())
            self.assertEqual(sorted(item.name for item in target.iterdir()), ["demo.mp4", "demo.srt"])

    def test_second_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "archive"
            archive.mkdir()
            video = root / "demo.mp4"
            video.write_bytes(b"video")
            job = {"id": "job-123456", "title": "标题"}
            with patch.dict(os.environ, {"ARCHIVE_DIR": str(archive), "ARCHIVE_DISPLAY": ""}):
                archive_outputs(job, [video])
                result = archive_outputs(job, [video])
            self.assertIsNotNone(result)
            self.assertEqual(len(list((archive / "标题-123456").iterdir())), 1)

    def test_missing_archive_dir_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"ARCHIVE_DIR": str(Path(tmp) / "nope")}
        ):
            self.assertIsNone(archive_outputs({"id": "job-1", "title": "x"}, []))


class TranslationUsageTest(unittest.TestCase):
    def test_cost_from_prices(self):
        with patch.dict(
            os.environ, {"TRANSLATION_PRICE_INPUT": "2", "TRANSLATION_PRICE_OUTPUT": "8"}
        ):
            usage = translation_usage(
                {
                    "prompt_tokens": 100_000,
                    "completion_tokens": 50_000,
                    "total_tokens": 150_000,
                    "calls": 3,
                },
                "demo-model",
            )
        self.assertAlmostEqual(usage["cost"], 0.6, places=6)
        self.assertTrue(usage["priced"])
        self.assertEqual(usage["model"], "demo-model")

    def test_cached_tokens_use_cache_price(self):
        with patch.dict(
            os.environ,
            {
                "TRANSLATION_PRICE_INPUT": "2",
                "TRANSLATION_PRICE_OUTPUT": "8",
                "TRANSLATION_PRICE_CACHE": "0.5",
                "TRANSLATION_PRICE_CURRENCY": "USD",
            },
        ):
            usage = translation_usage(
                {
                    "prompt_tokens": 100_000,
                    "completion_tokens": 10_000,
                    "total_tokens": 110_000,
                    "cached_tokens": 50_000,
                    "calls": 1,
                }
            )
        # 50K 未命中 * 2 + 50K 缓存 * 0.5 + 10K 输出 * 8 = 0.1 + 0.025 + 0.08
        self.assertAlmostEqual(usage["cost"], 0.205, places=6)
        self.assertEqual(usage["currency"], "USD")
        self.assertEqual(usage["cached_tokens"], 50_000)

    def test_without_price_only_tokens(self):
        with patch.dict(os.environ, {"TRANSLATION_PRICE_INPUT": "", "TRANSLATION_PRICE_OUTPUT": ""}):
            usage = translation_usage({"prompt_tokens": 10, "completion_tokens": 5})
        self.assertEqual(usage["total_tokens"], 15)
        self.assertEqual(usage["cost"], 0)
        self.assertFalse(usage["priced"])


class OnScreenScanTest(unittest.TestCase):
    def test_collects_text_cues_from_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = SubtitlePipeline(Path(tmp) / "out")
            segments = [
                SimpleNamespace(start=0.0, end=10.0, text="a"),
                SimpleNamespace(start=30.0, end=40.0, text="b"),
            ]
            seen: list[float] = []

            def fake_read(path, ts):
                seen.append(ts)
                return "テスト字幕" if len(seen) == 1 else ""

            pipeline.translation.read_frame_text = fake_read
            with patch.dict(os.environ, {"SUBTITLE_OCR": "true", "OCR_MAX_FRAMES": "10"}):
                cues = pipeline._scan_on_screen(Path("video.mp4"), segments)
            self.assertEqual(len(cues), 1)
            self.assertEqual(cues[0].text, "テスト字幕")
            self.assertEqual(cues[0].start, 10.0)

    def test_disabled_returns_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"SUBTITLE_OCR": "false"}
        ):
            pipeline = SubtitlePipeline(Path(tmp) / "out")
            self.assertEqual(pipeline._scan_on_screen(Path("v.mp4"), []), [])


class FeedTest(unittest.TestCase):
    def test_feed_interleaves_indexers(self):
        service = SearchService(lambda name, default="": default)
        raw = [{"indexer": "A", "title": f"a{i}", "key": f"a{i}"} for i in range(10)]
        raw += [{"indexer": "B", "title": f"b{i}", "key": f"b{i}"} for i in range(10)]
        fake = SimpleNamespace(
            search=lambda q, limit, sort="seeders", indexer_ids=None: raw,
            indexer_ids=lambda names: [],
        )
        service.client = lambda: fake
        feed = service.feed(8)
        self.assertEqual(len(feed), 8)
        self.assertEqual({item["indexer"] for item in feed}, {"A", "B"})


class JobRetryTest(unittest.TestCase):
    def test_failure_requeues_with_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = JobStore(root / "jobs.json")
            job = store.create("会失败的任务")
            store.update(job["id"], status="processing")

            class BadPipeline:
                last_usage = None

                def process(self, *args, **kwargs):
                    raise RuntimeError("boom")

            runner = JobRunner(store, root / "inbox", BadPipeline())
            with patch.dict(os.environ, {"PROCESS_RETRIES": "2", "PROCESS_RETRY_DELAY": "60"}):
                runner._process(job["id"], root / "inbox" / "x.mp4")
            updated = store.get(job["id"])
            self.assertEqual(updated["status"], "awaiting_source")
            self.assertEqual(updated["process_retries"], 1)
            self.assertGreater(updated["retry_at"], time.time())

    def test_auto_clean_removes_input_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "inbox"
            inbox.mkdir()
            video = inbox / "job-1-demo.mp4"
            video.write_bytes(b"video")
            store = JobStore(root / "jobs.json")
            job = store.create("已完成")
            store.update(job["id"], input_file=str(video))
            runner = JobRunner(store, inbox, SubtitlePipeline(root / "out"))
            with patch.dict(os.environ, {"AUTO_CLEAN": "true"}):
                runner._cleanup_after_success(store.get(job["id"]))
            self.assertFalse(video.exists())


class GlossaryTest(unittest.TestCase):
    def test_parse_lines(self):
        raw = "マジックミラー号=魔镜号\n# 注释\n\nお兄ちゃん = 哥哥\n坏的\n"
        self.assertEqual(parse_glossary(raw), [("マジックミラー号", "魔镜号"), ("お兄ちゃん", "哥哥")])

    def test_progress_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            SubtitlePipeline._save_progress(path, {"0": "第一句", "1": "第二句"})
            self.assertEqual(SubtitlePipeline._load_progress(path), {"0": "第一句", "1": "第二句"})


class NormalizeMagnetTest(unittest.TestCase):
    def test_guid_magnet_wins_over_prowlarr_url(self):
        item = {
            "title": "Demo",
            "guid": "magnet:?xt=urn:btih:" + "a" * 40,
            "magnetUrl": "http://prowlarr:9696/26/download?apikey=x&link=y",
        }
        result = normalize_result(item, "http://prowlarr:9696")
        self.assertTrue(result["magnet"].startswith("magnet:?xt=urn:btih:aaaa"))
        self.assertTrue(result["download_url"].startswith("http://prowlarr:9696/26/download"))

    def test_infohash_fallback_builds_magnet(self):
        result = normalize_result({"title": "No Links", "infoHash": "b" * 40})
        self.assertTrue(result["magnet"].startswith("magnet:?xt=urn:btih:bbbb"))


class HelpersTest(unittest.TestCase):


    def test_normalize_title(self):
        self.assertEqual(normalize_title("  魔镜号  "), "魔镜号")

    def test_timestamp(self):
        self.assertEqual(format_srt_timestamp(61.25), "00:01:01,250")

    def test_store_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.json")
            job = store.create("魔镜号")
            self.assertEqual(store.get(job["id"])["title"], "魔镜号")

    def test_choose_job_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            exact = folder / "job-1-video.mp4"
            exact.touch()
            self.assertEqual(choose_input_file(folder, "job-1", False), exact)

    def test_sidecar_pipeline_without_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"BURN_SUBTITLES": "false"}):
            root = Path(tmp)
            source = root / "demo.mp4"
            source.write_bytes(b"demo")
            (root / "demo.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
            subtitle, output = SubtitlePipeline(root / "output").process(source, "job-demo")
            self.assertTrue(subtitle.exists())
            self.assertEqual(output.name, "demo.mp4")

    def test_sidecar_pipeline_reports_stage_progress(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"BURN_SUBTITLES": "false"}):
            root = Path(tmp)
            source = root / "demo.mp4"
            source.write_bytes(b"demo")
            (root / "demo.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
            events: list[tuple[str, float]] = []
            SubtitlePipeline(root / "output").process(
                source, "job-demo", lambda stage, percent, detail="": events.append((stage, percent))
            )
            self.assertIn(("transcribing", 100.0), events)
            self.assertIn(("copying", 100.0), events)

    def test_interrupted_processing_jobs_are_requeued(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = JobStore(root / "jobs.json")
            job = store.create("中断的任务")
            store.update(job["id"], status="processing", stage={"name": "transcribing", "percent": 40.0})
            JobRunner(store, root / "inbox", SubtitlePipeline(root / "output"))
            recovered = store.get(job["id"])
            self.assertEqual(recovered["status"], "awaiting_source")
            self.assertIsNone(recovered["stage"])

    def test_setup_page_does_not_echo_secrets(self):
        page = setup_page(
            {
                "TELEGRAM_BOT_TOKEN": "secret-token",
                "TRANSLATION_API_KEY": "secret-key",
                "PROWLARR_API_KEY": "prowlarr-secret",
                "QBITTORRENT_PASSWORD": "qbt-secret",
            }
        )
        self.assertNotIn("secret-token", page)
        self.assertNotIn("secret-key", page)
        self.assertNotIn("prowlarr-secret", page)
        self.assertNotIn("qbt-secret", page)
        self.assertIn("已保存，留空即可", page)

    def test_settings_store_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SettingsStore(Path(tmp) / "settings.json")
            store.save({"TELEGRAM_BOT_TOKEN": "secret"})
            self.assertEqual(store.load()["TELEGRAM_BOT_TOKEN"], "secret")


class FakeQbt:
    def __init__(self):
        self.added = []
        self.closed = False

    def add_magnet(self, magnet, savepath, tag):
        self.added.append((magnet, savepath, tag))

    def add_torrent(self, content, filename, savepath, tag):
        self.added.append((filename, savepath, tag))

    def torrents(self, tag="", hashes=""):
        return [
            {
                "hash": INFO_HASH,
                "progress": 1.0,
                "state": "uploading",
                "size": 5,
                "completed": 5,
                "amount_left": 0,
                "dlspeed": 0,
                "eta": 0,
            }
        ]

    def files(self, torrent_hash):
        return [{"name": "Movie/Movie.mkv", "size": 5, "progress": 1.0}]

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class DownloadManagerTest(unittest.TestCase):
    def test_add_and_import_completed_torrent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            download_dir = root / "downloads"
            video = download_dir / "Movie" / "Movie.mkv"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"video")

            settings = {
                "QBITTORRENT_URL": "http://qbittorrent:8081",
                "QBITTORRENT_DOWNLOAD_DIR": str(download_dir),
            }

            def get_setting(name, default=""):
                return settings.get(name, default)

            store = JobStore(root / "jobs.json")
            fake = FakeQbt()
            manager = DownloadManager(
                store,
                root / "inbox",
                get_setting,
                SearchService(get_setting),
                client_factory=lambda *args, **kwargs: fake,
            )
            job = store.create("Movie")
            manager.add(job, {"magnet": MAGNET, "title": "Movie 1080p"})
            self.assertEqual(store.get(job["id"])["status"], "queued")
            self.assertEqual(fake.added[0][2], job["id"])

            manager.poll_all()
            finished = store.get(job["id"])
            self.assertEqual(finished["status"], "awaiting_source")
            self.assertTrue(Path(finished["input_file"]).exists())
            self.assertEqual(Path(finished["input_file"]).read_bytes(), b"video")

    def test_rejects_torrent_larger_than_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = JobStore(root / "jobs.json")
            fake = FakeQbt()
            manager = DownloadManager(
                store,
                root / "inbox",
                lambda name, default="": default,
                SearchService(lambda name, default="": default),
                client_factory=lambda *args, **kwargs: fake,
            )
            job = store.create("Movie")
            with patch("app.shutil.disk_usage") as usage:
                usage.return_value = SimpleNamespace(free=1024**3)
                with self.assertRaises(Exception):
                    manager.add(
                        job,
                        {"magnet": MAGNET, "title": "Huge", "size": 100 * 1024**3},
                    )
            self.assertEqual(fake.added, [])

    def test_start_downloads_creates_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = JobStore(root / "jobs.json")

            class FakeManager:
                def add(self, job, item):
                    return store.update(job["id"], status="queued")

            jobs = start_downloads(
                store,
                FakeManager(),
                [
                    {"title": "A", "magnet": MAGNET, "size": 1},
                    {"title": "B", "magnet": f"magnet:?xt=urn:btih:{'b' * 40}", "size": 2},
                ],
                "Movie",
            )
            self.assertEqual(len(jobs), 2)
            self.assertEqual({job["status"] for job in jobs}, {"queued"})
            self.assertEqual(store.get(jobs[0]["id"])["title"], "A")


class FakeSearch:
    def configured(self):
        return True

    def search(self, query, limit=30):
        return [
            {
                "title": "Movie 1080p",
                "magnet": MAGNET,
                "download_url": "",
                "info_hash": INFO_HASH,
                "size": 100,
                "size_text": "100 B",
                "seeders": 1,
                "leechers": 0,
                "indexer": "demo",
                "key": INFO_HASH,
            }
        ]

    def fetch_torrent(self, url):
        return b"torrent"

    def suggest_keywords(self, query, limit=6):
        return ["マジックミラー号"] if "魔镜" in query else []

    def translate_titles(self, titles):
        return {title: "中文 " + title for title in titles if "Frieren" in title}

    def decorate(self, results):
        return results


class FakeDownloads:
    def __init__(self, store):
        self.store = store

    def configured(self):
        return True

    def add(self, job, item):
        return self.store.update(job["id"], status="queued")

    def remove(self, job, delete_files=True):
        return None


class ApiTest(unittest.TestCase):
    def build(self, root: Path):
        settings = SettingsStore(root / "settings.json")
        store = JobStore(root / "jobs.json")
        search = FakeSearch()
        downloads = FakeDownloads(store)
        api = create_api(
            store,
            SimpleNamespace(inbox=root / "inbox"),
            settings,
            search,
            downloads,
        )
        return TestClient(api), store

    def test_search_and_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, store = self.build(Path(tmp))
            response = client.get("/api/search", params={"q": "Movie"})
            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 1)

            response = client.post(
                "/api/download",
                json={"items": results, "title": "Movie"},
            )
            self.assertEqual(response.status_code, 200)
            jobs = response.json()["jobs"]
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["title"], "Movie 1080p")
            self.assertEqual(store.list()[0]["status"], "queued")

    def test_upload_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client, store = self.build(root)
            response = client.post(
                "/api/upload",
                files={"file": ("demo.mp4", b"video-bytes", "video/mp4")},
                data={"title": "本地上传"},
            )
            self.assertEqual(response.status_code, 200)
            job = response.json()["job"]
            self.assertEqual(job["title"], "本地上传")
            self.assertEqual(job["status"], "awaiting_source")
            path = Path(job["input_file"])
            self.assertTrue(path.exists())
            self.assertEqual(path.read_bytes(), b"video-bytes")
            self.assertIn(job["id"], path.name)

    def test_upload_rejects_non_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, store = self.build(Path(tmp))
            response = client.post(
                "/api/upload",
                files={"file": ("notes.txt", b"text", "text/plain")},
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(store.list(), [])

    def test_delete_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, store = self.build(Path(tmp))
            job = store.create("待删除")
            response = client.delete("/api/jobs/" + job["id"])
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["deleted"])
            self.assertIsNone(store.get(job["id"]))

    def test_delete_missing_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, _ = self.build(Path(tmp))
            self.assertEqual(client.delete("/api/jobs/nope").status_code, 404)

    def test_retry_failed_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client, store = self.build(root)
            job = store.create("待重试")
            store.update(job["id"], status="failed", error="boom")

            self.assertEqual(client.post(f"/api/jobs/{job['id']}/retry").status_code, 400)

            inbox = root / "inbox"
            inbox.mkdir(parents=True, exist_ok=True)
            video = inbox / f"{job['id']}-demo.mp4"
            video.write_bytes(b"video")
            response = client.post(f"/api/jobs/{job['id']}/retry")
            self.assertEqual(response.status_code, 200)
            body = response.json()["job"]
            self.assertEqual(body["status"], "awaiting_source")
            self.assertEqual(Path(body["input_file"]), video)
            self.assertIsNone(body["error"])

    def test_retry_rejects_running_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, store = self.build(Path(tmp))
            job = store.create("处理中")
            store.update(job["id"], status="processing")
            self.assertEqual(client.post(f"/api/jobs/{job['id']}/retry").status_code, 409)

    def test_keyword_suggestion_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, _ = self.build(Path(tmp))
            response = client.get("/api/suggest", params={"q": "魔镜号"})
            self.assertEqual(response.status_code, 200)
            self.assertIn("マジックミラー号", response.json()["suggestions"])

    def test_translate_api_skips_chinese(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, _ = self.build(Path(tmp))
            response = client.post(
                "/api/translate",
                json={"titles": ["Frieren 1080p", "葬送的芙莉莲", 123, ""]},
            )
            self.assertEqual(response.status_code, 200)
            translations = response.json()["translations"]
            self.assertEqual(translations, {"Frieren 1080p": "中文 Frieren 1080p"})

    def test_translate_api_rejects_bad_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, _ = self.build(Path(tmp))
            response = client.post("/api/translate", json={"titles": "nope"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["translations"], {})

    def test_empty_download_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, _ = self.build(Path(tmp))
            response = client.post("/api/download", json={"items": []})
            self.assertEqual(response.status_code, 400)

    def test_share_and_qr_for_completed_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client, store = self.build(root)
            job = store.create("已完成")
            output = root / "out.mp4"
            output.write_bytes(b"video")
            store.update(job["id"], status="completed", output_file=str(output))

            share = client.get(f"/api/share/{job['id']}")
            self.assertEqual(share.status_code, 200)
            url = share.json()["url"]
            self.assertTrue(url.startswith("http://"))
            self.assertIn(f"/s/{job['id']}/", url)

            qr = client.get(f"/api/qr/{job['id']}")
            self.assertEqual(qr.status_code, 200)
            self.assertIn("svg", qr.headers["content-type"])
            self.assertIn(b"<svg", qr.content)

    def test_share_requires_completed_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, store = self.build(Path(tmp))
            job = store.create("还在处理")
            store.update(job["id"], status="processing")
            self.assertEqual(client.get(f"/api/share/{job['id']}").status_code, 404)
            self.assertEqual(client.get(f"/api/qr/{job['id']}").status_code, 404)

    def test_share_prefers_request_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client, store = self.build(root)
            job = store.create("已完成")
            output = root / "o.mp4"
            output.write_bytes(b"v")
            store.update(job["id"], status="completed", output_file=str(output))
            response = client.get(
                f"/api/share/{job['id']}", headers={"host": "192.168.137.1:8787"}
            )
            self.assertTrue(
                response.json()["url"].startswith(f"http://192.168.137.1:8787/s/{job['id']}/")
            )

    def test_share_falls_back_to_configured_base_url(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"BASE_URL": "http://192.168.137.1:8787"}
        ):
            root = Path(tmp)
            client, store = self.build(root)
            job = store.create("已完成")
            output = root / "o.mp4"
            output.write_bytes(b"v")
            store.update(job["id"], status="completed", output_file=str(output))
            response = client.get(
                f"/api/share/{job['id']}", headers={"host": "127.0.0.1:8787"}
            )
            self.assertTrue(
                response.json()["url"].startswith(f"http://192.168.137.1:8787/s/{job['id']}/")
            )
            self.assertEqual(response.json()["warning"], "")

    def test_basic_auth(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"WEB_PASSWORD": "pw", "WEB_USERNAME": "admin"}
        ):
            client, _ = self.build(Path(tmp))
            self.assertEqual(client.get("/").status_code, 401)
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/", auth=("admin", "pw")).status_code, 200)
            self.assertEqual(client.get("/", auth=("admin", "bad")).status_code, 401)


if __name__ == "__main__":
    unittest.main()
