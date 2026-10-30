import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from indexers import (
    ProwlarrAdmin,
    _usable_url,
    build_indexer,
    build_test_body,
    error_messages,
    resolve_config,
)


def make_schema(definition="mikan", name="Mikan"):
    return {
        "definitionName": definition,
        "name": name,
        "language": "zh-CN",
        "privacy": "public",
        "protocol": "torrent",
        "enable": True,
        "appProfileId": 0,
        "priority": 25,
        "fields": [
            {"name": "definitionFile", "value": definition},
            {"name": "baseUrl", "value": None},
            {"name": "torrentBaseSettings.preferMagnetUrl", "value": False},
        ],
    }


class FakeProwlarr:
    """记录请求并按需返回 Prowlarr 风格响应的 httpx 传输层。"""

    def __init__(self, existing=None, schemas=None, test_status=200,
                 test_payload=None, post_status=201, post_payload=None):
        self.existing = list(existing or [])
        self.schemas = list(schemas or [make_schema()])
        self.test_status = test_status
        self.test_payload = test_payload if test_payload is not None else []
        self.post_status = post_status
        self.post_payload = post_payload if post_payload is not None else {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        method = request.method
        if path == "/api/v1/indexer" and method == "GET":
            return httpx.Response(200, json=self.existing)
        if path == "/api/v1/indexer/schema":
            return httpx.Response(200, json=self.schemas)
        if path == "/api/v1/indexer/test":
            return httpx.Response(self.test_status, json=self.test_payload)
        if path == "/api/v1/indexer" and method == "POST":
            return httpx.Response(self.post_status, json=self.post_payload)
        if path.startswith("/api/v1/indexer/"):
            return httpx.Response(200, json={})
        if path == "/api/v1/health":
            return httpx.Response(200, json=[{"type": "error", "message": "no indexers"}])
        if path == "/api/v1/search":
            return httpx.Response(200, json=[
                {"title": "Demo 1080p", "indexer": "Mikan", "size": 1024 ** 3,
                 "seeders": 3, "leechers": 1},
            ])
        return httpx.Response(404, json=[])

    def admin(self, key="secret"):
        return ProwlarrAdmin("http://prowlarr:9696", key,
                             transport=httpx.MockTransport(self))


class BuildIndexerTest(unittest.TestCase):
    def test_payload_overrides(self):
        body = build_indexer(make_schema(), base_url="https://mikanani.me/")
        self.assertEqual(body["name"], "Mikan")
        self.assertTrue(body["enable"])
        self.assertEqual(body["appProfileId"], 1)
        fields = {field["name"]: field.get("value") for field in body["fields"]}
        self.assertEqual(fields["definitionFile"], "mikan")
        self.assertEqual(fields["baseUrl"], "https://mikanani.me/")
        self.assertTrue(fields["torrentBaseSettings.preferMagnetUrl"])

    def test_keeps_custom_name(self):
        body = build_indexer(make_schema(), name="动漫源")
        self.assertEqual(body["name"], "动漫源")

    def test_test_body_reuses_existing_id(self):
        body = build_test_body(make_schema(), {"id": 7, "name": "Mikan"})
        self.assertEqual(body["id"], 7)
        self.assertEqual(body["name"], "Mikan")

    def test_test_body_for_new_indexer_has_no_id(self):
        self.assertNotIn("id", build_test_body(make_schema()))


class AdminTest(unittest.TestCase):
    def test_lists_indexers_with_api_key(self):
        fake = FakeProwlarr(existing=[{"id": 1, "name": "Mikan"}])
        items = fake.admin().indexers()
        self.assertEqual(items[0]["name"], "Mikan")
        self.assertEqual(fake.requests[0].headers["X-Api-Key"], "secret")

    def test_add_creates_and_posts_schema(self):
        fake = FakeProwlarr()
        changed, message = fake.admin().add("mikan")
        self.assertTrue(changed)
        self.assertIn("Mikan", message)
        post = [request for request in fake.requests if request.method == "POST"]
        self.assertEqual(len(post), 1)
        body = json.loads(post[0].content)
        self.assertEqual(body["definitionName"], "mikan")
        self.assertEqual(body["appProfileId"], 1)
        self.assertEqual(body["fields"][0]["value"], "mikan")

    def test_add_skips_existing(self):
        fake = FakeProwlarr(existing=[{"id": 3, "name": "Mikan", "definitionName": "mikan"}])
        changed, message = fake.admin().add("mikan")
        self.assertFalse(changed)
        self.assertIn("已存在", message)
        self.assertFalse([r for r in fake.requests if r.method == "POST"])

    def test_add_unknown_definition(self):
        fake = FakeProwlarr()
        changed, message = fake.admin().add("nope")
        self.assertFalse(changed)
        self.assertIn("nope", message)

    def test_add_reports_validation_error(self):
        fake = FakeProwlarr(
            post_status=400,
            post_payload=[{"isWarning": False, "errorMessage": "Name already in use"}],
        )
        changed, message = fake.admin().add("mikan", name="Mikan 2")
        self.assertFalse(changed)
        self.assertIn("Name already in use", message)

    def test_test_success_and_failure(self):
        ok, message = FakeProwlarr().admin().test(make_schema())
        self.assertTrue(ok)
        self.assertEqual(message, "")

        fake = FakeProwlarr(
            test_status=400,
            test_payload=[{"errorMessage": "blocked by CloudFlare Protection."}],
        )
        ok, message = fake.admin().test(make_schema())
        self.assertFalse(ok)
        self.assertIn("CloudFlare", message)

    def test_search(self):
        results = FakeProwlarr().admin().search("demo", 5)
        self.assertEqual(results[0]["title"], "Demo 1080p")

    def test_remove(self):
        fake = FakeProwlarr(existing=[{"id": 7, "name": "Mikan", "definitionName": "mikan"}])
        changed, message = fake.admin().remove("mikan")
        self.assertTrue(changed)
        self.assertEqual(fake.requests[-1].method, "DELETE")
        self.assertEqual(fake.requests[-1].url.path, "/api/v1/indexer/7")


class ErrorMessageTest(unittest.TestCase):
    def test_list_and_dict(self):
        self.assertEqual(error_messages([{"errorMessage": "a"}, {"errorMessage": "b"}]), "a；b")
        self.assertEqual(error_messages({"message": "boom"}), "boom")
        self.assertEqual(error_messages("weird"), "")


class ConfigTest(unittest.TestCase):
    def test_url_rewrite_only_on_host(self):
        self.assertEqual(_usable_url("http://prowlarr:9696", False), "http://127.0.0.1:9696")
        self.assertEqual(_usable_url("http://prowlarr:9696", True), "http://prowlarr:9696")
        self.assertEqual(_usable_url("http://192.168.1.5:9696", False), "http://192.168.1.5:9696")
        self.assertEqual(_usable_url("", False), "http://127.0.0.1:9696")

    def test_env_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data" / "settings.json").write_text(
                json.dumps({"PROWLARR_URL": "http://file-host:9696",
                            "PROWLARR_API_KEY": "file-key"}),
                encoding="utf-8",
            )
            (root / ".env").write_text("PROWLARR_API_KEY=env-file-key\n", encoding="utf-8")
            env = {"PROWLARR_URL": "http://env-host:9696", "PROWLARR_API_KEY": "env-key"}
            with mock.patch.dict(os.environ, env, clear=False), \
                    mock.patch("indexers._inside_container", return_value=False):
                os.environ.pop("DATA_DIR", None)
                url, key, source = resolve_config(root)
            self.assertEqual(url, "http://env-host:9696")
            self.assertEqual(key, "env-key")
            self.assertEqual(source, "环境变量")

    def test_settings_file_then_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data" / "settings.json").write_text(
                json.dumps({"PROWLARR_URL": "http://prowlarr:9696",
                            "PROWLARR_API_KEY": "file-key"}),
                encoding="utf-8",
            )
            (root / ".env").write_text("PROWLARR_API_KEY=env-file-key\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=False), \
                    mock.patch("indexers._inside_container", return_value=False):
                for name in ("PROWLARR_URL", "PROWLARR_API_KEY", "DATA_DIR"):
                    os.environ.pop(name, None)
                url, key, source = resolve_config(root)
            self.assertEqual(key, "file-key")
            self.assertEqual(url, "http://127.0.0.1:9696")
            self.assertTrue(source.endswith("settings.json"))

            (root / "data" / "settings.json").unlink()
            with mock.patch.dict(os.environ, {}, clear=False), \
                    mock.patch("indexers._inside_container", return_value=False):
                for name in ("PROWLARR_URL", "PROWLARR_API_KEY", "DATA_DIR"):
                    os.environ.pop(name, None)
                url, key, source = resolve_config(root)
            self.assertEqual(key, "env-file-key")
            self.assertTrue(source.endswith(".env"))
            self.assertEqual(url, "http://127.0.0.1:9696")


if __name__ == "__main__":
    unittest.main()
