import sys
import tempfile
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from downloader import (
    DownloadError,
    QBittorrentClient,
    import_video,
    pick_video_file,
    resolve_torrent_file,
    torrent_progress,
)


class FileSelectionTest(unittest.TestCase):
    def test_prefers_main_video(self):
        files = [
            {"name": "Movie/sample.mkv", "size": 100, "progress": 1},
            {"name": "Movie/Movie.mkv", "size": 5000, "progress": 1},
            {"name": "Movie/readme.txt", "size": 9999, "progress": 1},
        ]
        picked = pick_video_file(files)
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertEqual(picked["name"], "Movie/Movie.mkv")

    def test_no_video(self):
        self.assertIsNone(pick_video_file([{"name": "a.txt", "size": 1}]))


class PathTest(unittest.TestCase):
    def test_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = resolve_torrent_file(Path(tmp), {"name": "Movie/Movie.mkv"})
            self.assertEqual(path, (Path(tmp) / "Movie" / "Movie.mkv").resolve())

    def test_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DownloadError):
                resolve_torrent_file(Path(tmp), {"name": "../../etc/passwd"})


class ImportTest(unittest.TestCase):
    def test_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "download" / "Movie.mkv"
            source.parent.mkdir()
            source.write_bytes(b"video")
            target = import_video(source, root / "inbox", "job-1")
            self.assertEqual(target.name, "job-1-Movie.mkv")
            self.assertEqual(target.read_bytes(), b"video")


class QBittorrentTest(unittest.TestCase):
    def test_flow(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == "/api/v2/auth/login":
                return httpx.Response(
                    200, text="Ok.", headers={"set-cookie": "SID=abc; path=/"}
                )
            if request.url.path == "/api/v2/torrents/add":
                return httpx.Response(
                    200,
                    json={
                        "added_torrent_ids": ["a" * 40],
                        "failure_count": 0,
                        "pending_count": 0,
                        "success_count": 1,
                    },
                )
            if request.url.path == "/api/v2/torrents/info":
                self.assertEqual(request.url.params.get("tag"), "job-1")
                return httpx.Response(
                    200,
                    json=[
                        {
                            "hash": "a" * 40,
                            "progress": 0.5,
                            "state": "downloading",
                            "size": 100,
                            "dlspeed": 10,
                            "eta": 5,
                        }
                    ],
                )
            if request.url.path == "/api/v2/torrents/files":
                return httpx.Response(
                    200, json=[{"name": "Movie/Movie.mkv", "size": 100}]
                )
            return httpx.Response(404)

        client = QBittorrentClient(
            "http://qbittorrent:8081",
            "admin",
            "secret",
            transport=httpx.MockTransport(handler),
        )
        client.add_magnet("magnet:?xt=urn:btih:" + "a" * 40, "/downloads", "job-1")
        torrents = client.torrents(tag="job-1")
        self.assertEqual(len(torrents), 1)
        self.assertAlmostEqual(torrent_progress(torrents[0]), 0.5)
        files = client.files("a" * 40)
        self.assertEqual(files[0]["name"], "Movie/Movie.mkv")
        client.close()
        self.assertIn("/api/v2/auth/login", calls)

    def test_login_204_empty_body(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v2/auth/login":
                return httpx.Response(
                    204, headers={"set-cookie": "SID=abc; path=/"}
                )
            return httpx.Response(200, json=[])

        client = QBittorrentClient(
            "http://qbittorrent:8081",
            "admin",
            "secret",
            transport=httpx.MockTransport(handler),
        )
        self.assertEqual(client.torrents(tag="job-1"), [])
        client.close()

    def test_login_failure(self):
        client = QBittorrentClient(
            "http://qbittorrent:8081",
            "admin",
            "bad",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text="Fails.")
            ),
        )
        with self.assertRaises(DownloadError):
            client.torrents(tag="job-1")


if __name__ == "__main__":
    unittest.main()
