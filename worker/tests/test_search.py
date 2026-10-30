import base64
import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from search import (
    ProwlarrClient,
    SearchError,
    SearchService,
    SearchSessions,
    is_relevant_title,
    is_safe_torrent_url,
    needs_translation,
    normalize_result,
    parse_magnet_hash,
    query_tokens,
)


INFO_HASH = "a" * 40
MAGNET = f"magnet:?xt=urn:btih:{INFO_HASH}&dn=Movie"


class MagnetTest(unittest.TestCase):
    def test_hex_hash(self):
        self.assertEqual(parse_magnet_hash(MAGNET), INFO_HASH)

    def test_base32_hash(self):
        encoded = base64.b32encode(bytes.fromhex(INFO_HASH)).decode("ascii")
        self.assertEqual(parse_magnet_hash(f"magnet:?xt=urn:btih:{encoded}"), INFO_HASH)

    def test_invalid(self):
        self.assertIsNone(parse_magnet_hash("magnet:?dn=no-hash"))
        self.assertIsNone(parse_magnet_hash(""))


class NormalizeTest(unittest.TestCase):
    def test_magnet_item(self):
        result = normalize_result(
            {
                "title": "Movie 1080p",
                "size": 4 * 1024**3,
                "seeders": 21,
                "indexer": "Demo",
                "magnetUrl": MAGNET,
            }
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["info_hash"], INFO_HASH)
        self.assertEqual(result["seeders"], 21)
        self.assertIn("GB", result["size_text"])

    def test_guid_magnet(self):
        result = normalize_result({"title": "Movie", "guid": MAGNET, "size": 1})
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["magnet"], MAGNET)

    def test_unknown_seeders_for_mikan(self):
        item = {"title": "Movie", "size": 1, "seeders": 1, "indexer": "Mikan",
                "magnetUrl": MAGNET}
        result = normalize_result(item)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["seeders_unknown"])

        item["indexer"] = "YTS"
        result = normalize_result(item)
        assert result is not None
        self.assertFalse(result["seeders_unknown"])

    def test_requires_download_target(self):
        self.assertIsNone(normalize_result({"title": "Movie", "size": 1}))

    def test_download_url(self):
        result = normalize_result(
            {
                "title": "Movie",
                "size": 1,
                "downloadUrl": "http://prowlarr:9696/1/download",
            }
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["download_url"].startswith("http://"))


class RelevanceTest(unittest.TestCase):
    def test_chinese_query_does_not_match_english_title(self):
        tokens = query_tokens("哆啦A梦")
        self.assertTrue(tokens)
        self.assertFalse(is_relevant_title("Oprah with Meghan and Harry", tokens))
        self.assertTrue(is_relevant_title("Doraemon Nobita 2020", ["doraemon"]))

    def test_english_query(self):
        tokens = query_tokens("The Matrix")
        self.assertIn("matrix", tokens)
        self.assertTrue(is_relevant_title("The Matrix 1999 1080p", tokens))
        self.assertFalse(is_relevant_title("I Care a Lot", tokens))


class ProwlarrClientTest(unittest.TestCase):
    def test_search_and_sort(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["X-Api-Key"], "secret")
            self.assertIn("query=Movie", str(request.url))
            return httpx.Response(
                200,
                json=[
                    {
                        "title": "Movie 720p",
                        "size": 600 * 1024 * 1024,
                        "seeders": 1,
                        "magnetUrl": f"magnet:?xt=urn:btih:{'b' * 40}",
                    },
                    {
                        "title": "Movie 2160p",
                        "size": 1500 * 1024 * 1024,
                        "seeders": 9,
                        "magnetUrl": f"magnet:?xt=urn:btih:{'c' * 40}",
                    },
                ],
            )

        client = ProwlarrClient(
            "http://prowlarr:9696",
            "secret",
            transport=httpx.MockTransport(handler),
        )
        results = client.search("Movie", 10)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["seeders"], 9)

    def test_filters_unrelated_results(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {"title": "I Care a Lot (2020)", "size": 1, "seeders": 5,
                     "magnetUrl": f"magnet:?xt=urn:btih:{'d' * 40}"},
                    {"title": "Doraemon Nobita 2020 1080p", "size": 2, "seeders": 6,
                     "magnetUrl": f"magnet:?xt=urn:btih:{'e' * 40}"},
                ],
            )

        client = ProwlarrClient(
            "http://prowlarr:9696",
            "secret",
            transport=httpx.MockTransport(handler),
        )
        results = client.search("Doraemon", 10)
        self.assertEqual(len(results), 1)
        self.assertIn("Doraemon", results[0]["title"])

    def test_chinese_query_returns_empty(self):
        client = ProwlarrClient(
            "http://prowlarr:9696",
            "secret",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=[
                        {"title": "I Care a Lot (2020)", "size": 1, "seeders": 5,
                         "magnetUrl": f"magnet:?xt=urn:btih:{'f' * 40}"}
                    ],
                )
            ),
        )
        self.assertEqual(client.search("哆啦A梦", 10), [])

    def test_torrent_redirect_to_magnet(self):
        client = ProwlarrClient(
            "http://prowlarr:9696",
            "secret",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    301, headers={"location": MAGNET}
                )
            ),
        )
        self.assertEqual(
            client.fetch_torrent("http://prowlarr:9696/1/download"), MAGNET
        )

    def test_unauthorized(self):
        client = ProwlarrClient(
            "http://prowlarr:9696",
            "bad",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, json={"error": "no"})
            ),
        )
        with self.assertRaises(SearchError):
            client.search("Movie", 5)


class SuggestTest(unittest.TestCase):
    def test_local_aliases_without_translation_api(self):
        service = SearchService(lambda name, default="": default)
        suggestions = service.suggest_keywords("魔镜号")
        self.assertIn("マジックミラー号", suggestions)
        self.assertIn("MAGIC MIRROR", suggestions)
        self.assertNotIn("魔镜号", suggestions)

    def test_non_chinese_returns_empty(self):
        service = SearchService(lambda name, default="": default)
        self.assertEqual(service.suggest_keywords("inception"), [])


class SessionTest(unittest.TestCase):
    def test_toggle_and_drop(self):
        sessions = SearchSessions(ttl_seconds=60)
        results = [{"title": "A"}, {"title": "B"}]
        sid = sessions.create("query", results)
        self.assertEqual(sessions.selected_results(sid), [])
        session = sessions.toggle(sid, 1)
        self.assertIsNotNone(session)
        self.assertEqual(sessions.selected_results(sid), [{"title": "B"}])
        sessions.toggle(sid, 1)
        self.assertEqual(sessions.selected_results(sid), [])
        sessions.drop(sid)
        self.assertIsNone(sessions.get(sid))

    def test_expired(self):
        sessions = SearchSessions(ttl_seconds=-1)
        sid = sessions.create("query", [{"title": "A"}])
        self.assertIsNone(sessions.get(sid))


class TranslationTest(unittest.TestCase):
    def test_needs_translation(self):
        self.assertTrue(needs_translation("SDMM-239 マジックミラー号 保健体育の課外授業"))
        self.assertTrue(needs_translation("Frieren S01E03 1080p WEB-DL"))
        self.assertFalse(needs_translation("葬送的芙莉莲 第3集"))
        self.assertFalse(needs_translation("[喵萌奶茶屋] 葬送的芙莉莲 - 32 [1080p]"))
        self.assertFalse(needs_translation(""))
        self.assertFalse(needs_translation("   "))

    def test_decorate_adds_chinese_only_for_non_chinese(self):
        service = SearchService(lambda name, default="": default)
        results = [{"title": "SDMM-239 マジックミラー号"}, {"title": "葬送的芙莉莲 第3集"}]
        seen = {}

        def fake_translate(titles):
            seen["titles"] = list(titles)
            return {"SDMM-239 マジックミラー号": "SDMM-239 魔镜号"}

        with mock.patch.object(service, "translate_titles", side_effect=fake_translate):
            out = service.decorate(results)
        self.assertEqual(out[0]["title_zh"], "SDMM-239 魔镜号")
        self.assertNotIn("title_zh", out[1])
        self.assertEqual(seen["titles"], ["SDMM-239 マジックミラー号"])

    def test_decorate_skips_chinese_titles_entirely(self):
        service = SearchService(lambda name, default="": default)
        with mock.patch.object(service, "translate_titles") as translate:
            out = service.decorate([{"title": "葬送的芙莉莲"}])
        translate.assert_not_called()
        self.assertNotIn("title_zh", out[0])

    def test_decorate_survives_translation_errors(self):
        service = SearchService(lambda name, default="": default)
        results = [{"title": "Frieren 1080p"}]
        with mock.patch.object(service, "translate_titles", side_effect=RuntimeError("boom")):
            out = service.decorate(results)
        self.assertEqual(out, [{"title": "Frieren 1080p"}])

    def test_translate_titles_uses_cache(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        old = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = holder.name
        if old is None:
            self.addCleanup(os.environ.pop, "DATA_DIR", None)
        else:
            self.addCleanup(os.environ.__setitem__, "DATA_DIR", old)
        service = SearchService(lambda name, default="": default)
        calls = []

        def fake_request(titles):
            calls.append(list(titles))
            return [f"{title}-中文" for title in titles]

        service._request_translations = fake_request
        first = service.translate_titles(["A title", "B title"])
        second = service.translate_titles(["A title", "C title"])
        self.assertEqual(first["A title"], "A title-中文")
        self.assertEqual(second["A title"], "A title-中文")
        self.assertEqual(second["C title"], "C title-中文")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1], ["C title"])

    def test_translate_without_config_returns_nothing(self):
        service = SearchService(lambda name, default="": default)
        self.assertEqual(service._request_translations(["A title"]), [])

    def test_refusals_are_dropped(self):
        service = SearchService(lambda name, default="": default)
        service._request_translations = lambda titles: [
            "无法翻译：标题包含违规内容" for _ in titles
        ]
        self.assertEqual(service.translate_titles(["SDMM-239 マジックミラー号"]), {})

    def test_unchanged_text_is_dropped(self):
        service = SearchService(lambda name, default="": default)
        service._request_translations = lambda titles: list(titles)
        self.assertEqual(service.translate_titles(["SDMM-239 マジックミラー号"]), {})


class UrlSafetyTest(unittest.TestCase):
    def test_public(self):
        self.assertTrue(is_safe_torrent_url("https://example.com/a.torrent"))

    def test_private(self):
        self.assertFalse(is_safe_torrent_url("http://127.0.0.1/a.torrent"))
        self.assertFalse(is_safe_torrent_url("http://10.0.0.1/a.torrent"))
        self.assertFalse(is_safe_torrent_url("http://localhost/a.torrent"))
        self.assertFalse(is_safe_torrent_url("file:///etc/passwd"))


if __name__ == "__main__":
    unittest.main()
