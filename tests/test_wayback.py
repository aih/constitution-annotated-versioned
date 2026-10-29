import json
import tempfile
import unittest
from pathlib import Path

from cav.store import Store
from cav.wayback import Capture, import_wayback, to_capture, version_times

PAGE = b"""<html><head><link rel="stylesheet" href="/css/site.css"></head>
<body><a href="/browse/essay/x/A/">x</a><p>%s</p></body></html>"""


class FakeResponse:
    def __init__(self, status, body=b"", ctype="text/html", data=None):
        self.status_code = status
        self.content = body
        self.headers = {"Content-Type": ctype}
        self._data = data

    def json(self):
        return self._data


class FakeSession:
    """Serves a CDX listing and id_ fetches for two captures of one essay."""

    def __init__(self):
        self.headers = {}
        self.fetched = []

    def get(self, url, params=None, timeout=None):
        if "/cdx/" in url:
            if params["url"].endswith("/browse/*"):
                return FakeResponse(200, data=[
                    ["timestamp", "original", "statuscode", "mimetype"],
                    ["20240110000000", "https://constitution.congress.gov/browse/essay/x/A/", "200", "text/html"],
                    ["20240120000000", "http://constitution.congress.gov:80/browse/essay/x/A/", "200", "text/html"],
                    ["20240301000000", "https://constitution.congress.gov/browse/essay/x/A/", "200", "text/html"],
                    ["20240301000000", "https://constitution.congress.gov/browse/essay/x/B/", "200", "text/html"],
                    ["20240401000000", "https://constitution.congress.gov/browse/essay/x/B/", "404", "text/html"],
                    ["20240401000000", "https://constitution.congress.gov/browse/?q=1", "200", "text/html"],
                ])
            return FakeResponse(200, data=[])
        self.fetched.append(url)
        if url.endswith("/css/site.css"):
            return FakeResponse(200, b"body{}", "text/css")
        ts = url.split("/web/")[1][:14]
        return FakeResponse(200, PAGE % ts.encode())


class WaybackTests(unittest.TestCase):
    def test_to_capture(self):
        c = to_capture("20240101000000", "http://constitution.congress.gov:80/browse/article-1", "200", "text/html")
        self.assertEqual(c, Capture("20240101000000", "/browse/article-1/", 200, "text/html"))
        self.assertIsNone(to_capture("1", "https://constitution.congress.gov/browse/?q=1", "200", "text/html"))
        self.assertIsNone(to_capture("1", "https://constitution.congress.gov/about/", "200", "text/html"))
        self.assertIsNone(to_capture("1", "https://example.com/browse/", "200", "text/html"))

    def test_version_times(self):
        caps = [Capture(ts, "/browse/", 200, "text/html")
                for ts in ("20240110000000", "20240120000000", "20240301000000")]
        self.assertEqual(version_times(caps, "month"), ["20240120000000", "20240301000000"])
        self.assertEqual(version_times(caps, "year"), ["20240301000000"])
        self.assertEqual(version_times(caps, "month", since="20240201000000"), ["20240301000000"])

    def test_import(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d))
            fake = FakeSession()
            made = import_wayback(store, delay=0, session=fake)
            self.assertEqual(made, ["20240120T000000Z", "20240301T000000Z", "20240401T000000Z"])
            jan = store.manifest("20240120T000000Z")["files"]
            self.assertEqual(sorted(jan), ["/browse/essay/x/A/", "/css/site.css"])
            self.assertIn(b"20240120000000", store.get_blob(jan["/browse/essay/x/A/"]["sha256"]))
            mar = store.manifest("20240301T000000Z")["files"]
            self.assertIn("/browse/essay/x/B/", mar)
            apr = store.manifest("20240401T000000Z")["files"]
            self.assertNotIn("/browse/essay/x/B/", apr)  # 404 capture removes it
            # A capture shared by two versions is fetched once.
            page_fetches = [u for u in fake.fetched if "/essay/x/A/" in u]
            self.assertEqual(len(page_fetches), len(set(page_fetches)))
            # Rerun resumes: no new versions, no page refetches.
            self.assertEqual(import_wayback(store, delay=0, session=fake), [])
            self.assertTrue(json.loads((Path(d) / "wayback-cache.json").read_text()))


if __name__ == "__main__":
    unittest.main()
