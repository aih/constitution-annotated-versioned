import json
import tempfile
import unittest
from pathlib import Path

from cav.build import Builder
from cav.links import parse
from cav.paths import normalize, unversioned, versioned
from cav.scrape import discover, import_mirror
from cav.store import Store
from cav.versions import parse_query, resolve, version_id

FIXTURES = Path(__file__).parent / "fixtures"
V1, V2 = "20260115T120000Z", "20260601T083000Z"


class VersionTests(unittest.TestCase):
    def test_partial_dates_cover_whole_period(self):
        self.assertEqual(version_id(parse_query("2026")), "20261231T235959Z")
        self.assertEqual(version_id(parse_query("2026-02")), "20260228T235959Z")
        self.assertEqual(version_id(parse_query("2026-03-01")), "20260301T235959Z")
        self.assertEqual(version_id(parse_query("2026-03-01T10")), "20260301T105959Z")
        self.assertEqual(version_id(parse_query("2026-03-01T10:15:30Z")), "20260301T101530Z")
        self.assertEqual(version_id(parse_query("20260301T101530Z")), "20260301T101530Z")

    def test_offsets_convert_to_utc(self):
        self.assertEqual(version_id(parse_query("2026-03-01T05:15:30-05:00")), "20260301T101530Z")

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            parse_query("yesterday")

    def test_resolve(self):
        vs = [V1, V2]
        self.assertIsNone(resolve(vs, "2026-01-14"))
        self.assertEqual(resolve(vs, "2026-01-15"), V1)
        self.assertEqual(resolve(vs, "2026-06-01T08:29:59Z"), V1)
        self.assertEqual(resolve(vs, "2026-06-01T08:30:00Z"), V2)
        self.assertEqual(resolve(vs, "2030"), V2)


class PathTests(unittest.TestCase):
    def test_versioned_roundtrip(self):
        for p, want in [
            ("/browse/essay/artII-S1-C1-3/ALDE_00013792/", f"/browse/{V1}/essay/artII-S1-C1-3/ALDE_00013792/"),
            ("/browse/", f"/browse/{V1}/"),
            ("/css/site.css", f"/css/{V1}/site.css"),
            ("/favicon.ico", f"/{V1}/favicon.ico"),
            ("/", f"/{V1}/"),
        ]:
            self.assertEqual(versioned(p, V1), want)
            self.assertEqual(unversioned(want), (p, V1))

    def test_normalize(self):
        self.assertEqual(normalize("/browse/article-2"), "/browse/article-2/")
        self.assertEqual(normalize("/browse/a/../b/"), "/browse/b/")
        self.assertEqual(normalize("/css/site.css"), "/css/site.css")


class ScrapeTests(unittest.TestCase):
    def test_discover_pages_and_assets(self):
        html = (FIXTURES / "v1/constitution.congress.gov/browse/article-2/section-1/clause-1/index.html").read_bytes()
        pages, assets = discover("/browse/article-2/section-1/clause-1/", html, "text/html")
        self.assertIn("/browse/essay/artII-S1-C1-3/ALDE_00013792/", pages)
        self.assertIn("/resources/", pages)
        self.assertNotIn("/about/", pages)  # outside captured sections
        self.assertNotIn("/search/", pages)
        self.assertIn("/css/site.css", assets)
        self.assertIn("/img/logo.svg", assets)


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        store = Store(root / "data")
        import_mirror(store, FIXTURES / "v1/constitution.congress.gov", parse_query("2026-01-15T12:00:00Z"))
        import_mirror(store, FIXTURES / "v2/constitution.congress.gov", parse_query("2026-06-01T08:30:00Z"))
        cls.out = root / "dist"
        Builder(store, cls.out).build()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def read(self, rel):
        return (self.out / rel).read_text()

    def test_each_version_has_its_own_copy(self):
        essay = "essay/artII-S1-C1-3/ALDE_00013792/index.html"
        self.assertIn("VERSION ONE", self.read(f"browse/{V1}/{essay}"))
        self.assertIn("VERSION TWO", self.read(f"browse/{V2}/{essay}"))

    def test_links_stay_in_version(self):
        soup = parse(self.read(f"browse/{V1}/article-2/section-1/clause-1/index.html"))
        hrefs = {a["href"] for a in soup.find_all("a")}
        self.assertIn(f"/browse/{V1}/essay/artII-S1-C1-3/ALDE_00013792/#ALDF_1", hrefs)
        self.assertIn("https://constitution.congress.gov/about/", hrefs)
        self.assertEqual(soup.find("link", rel="stylesheet")["href"], f"/css/{V1}/site.css")
        self.assertIn(f"/img/{V1}/logo.svg", self.read(f"css/{V1}/site.css"))

    def test_banner_and_footer(self):
        soup = parse(self.read(f"browse/{V2}/index.html"))
        banner = soup.body.contents[0]
        self.assertEqual(banner["id"], "cav-banner")
        self.assertIn("Demonstration site", banner.get_text())
        self.assertIn("2026-06-01 08:30:00 UTC", banner.get_text())
        footer = soup.find("footer").find(id="cav-footer")
        self.assertIn(V2, footer.get_text())

    def test_stubs_and_versions_json(self):
        stub = self.read("browse/essay/artII-S1-C1-4/ALDE_00099999/index.html")
        self.assertIn(f"/browse/{V2}/essay/artII-S1-C1-4/ALDE_00099999/", stub)
        self.assertEqual(json.loads(self.read("_cav/versions.json")), {"versions": [V1, V2]})


if __name__ == "__main__":
    unittest.main()
