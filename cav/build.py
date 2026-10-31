"""Generate the static site from stored snapshots.

Output layout (with base path ""):
  /<section>/<version>/<rest>   every captured file of every version
  /<section>/<rest>             stub per page that resolves ?date= (or latest)
  /_cav/                        banner CSS, resolver JS, versions.json, version list
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from . import SOURCE_BASE
from .links import parse, rewrite_css, rewrite_html
from .paths import is_html, normalize, output_file, source_path, versioned
from .store import Store
from .versions import display

STATIC = Path(__file__).parent / "static"
AUTHOR = "Ari Hershowitz"
AUTHOR_URL = "https://aih.github.io"
REPO_URL = "https://github.com/aih/constitution-annotated-versioned"
SKIP_SCHEMES = ("#", "mailto:", "tel:", "javascript:", "data:")


class Builder:
    def __init__(self, store: Store, out: str | Path, base: str = ""):
        self.store = store
        self.out = Path(out)
        self.base = base.rstrip("/")
        self.versions = store.versions()
        if not self.versions:
            raise SystemExit("no snapshots in store")
        self.latest = self.versions[-1]

    # -- URL mapping -------------------------------------------------------

    def url_mapper(self, page_path: str, version: str, files: dict):
        pages = {p for p, f in files.items() if is_html(f["content_type"])}

        def fn(url: str, is_nav: bool) -> str:
            if not url or url.startswith(SKIP_SCHEMES):
                return url
            absolute = urljoin(SOURCE_BASE + page_path, url)
            p = source_path(absolute)
            if p is None:
                return url
            parts = urlsplit(absolute)
            frag = f"#{parts.fragment}" if parts.fragment else ""
            if is_nav:
                np = normalize(p)
                if not parts.query and np in pages:
                    return self.base + versioned(np, version) + frag
            elif p in files:
                return self.base + versioned(p, version) + frag
            # Not captured: point at the official site.
            return absolute

        return fn

    # -- page decoration ---------------------------------------------------

    def head_tags(self, soup: BeautifulSoup, version: str, path: str) -> None:
        head = soup.head or soup.new_tag("head")
        if soup.head is None:
            soup.html.insert(0, head)
        b = self.base
        frag = BeautifulSoup(
            f'<meta name="robots" content="noindex">'
            f'<meta name="cav-version" content="{version}">'
            f'<meta name="cav-path" content="{html.escape(path)}">'
            f'<meta name="cav-base" content="{html.escape(b)}">'
            f'<link rel="stylesheet" href="{b}/_cav/cav.css">'
            f'<script src="{b}/_cav/cav.js" defer></script>',
            "html.parser",
        )
        for el in list(frag.contents):
            head.append(el)

    def banner(self, version: str, path: str) -> str:
        official = html.escape(SOURCE_BASE + path)
        v = (f'<span class="cav-version">Version <a href="{self.base}/_cav/versions.html" '
             f'title="{version}">{display(version)}</a></span>') if version else ""
        return (
            '<div id="cav-banner" role="note">'
            '<span class="cav-warning"><strong>Demonstration site.</strong> '
            'This is not the official Constitution Annotated. '
            f'See <a href="{official}">constitution.congress.gov</a>. '
            f'<a href="{self.base}/_cav/about.html">About</a></span>'
            f'{v}<span id="cav-query" hidden></span></div>'
        )

    def footer_line(self, version: str, path: str) -> str:
        b = self.base
        return (
            '<div id="cav-footer">'
            f'Archived version <a href="{b}{versioned(path, version)}">{version}</a> '
            f'({display(version)}) · <a href="{b}{path}">Latest</a> · '
            f'<a href="{b}/_cav/versions.html">All versions</a><br>'
            f'{self.credit()}</div>'
        )

    def credit(self) -> str:
        return (
            f'A proof of concept by <a href="{AUTHOR_URL}">{AUTHOR}</a>, '
            'not the official Constitution Annotated. '
            f'<a href="{self.base}/_cav/about.html">About this site</a>'
        )

    def site_footer(self) -> str:
        """Footer for the pages this site generates (stubs, version list, About)."""
        return f'<footer id="cav-footer">{self.credit()}</footer>'

    def about_page(self) -> str:
        b = self.base
        latest = versioned("/browse/", self.latest)
        return (
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex\"><title>About this site</title>"
            f"<link rel=\"stylesheet\" href=\"{b}/_cav/cav.css\"></head><body>"
            f"{self.banner('', '/')}"
            "<main id=\"cav-about\"><h1>About this site</h1>"
            f"<p>This site is a proof of concept by <a href=\"{AUTHOR_URL}\">{AUTHOR}</a>. "
            "It is not the official Constitution Annotated, which is published by the "
            "Library of Congress at "
            "<a href=\"https://constitution.congress.gov/\">constitution.congress.gov</a>.</p>"
            "<p>The official site updates its text in place, so a link shows whatever the text "
            "says today. This site keeps each captured version of a page at a permanent "
            f"address that includes the version's date and time, for example "
            f"<a href=\"{b}{latest}\"><code>{html.escape(latest)}</code></a>. "
            "Apart from the banner at the top and the version line in the footer, "
            "each page is the original page as captured.</p>"
            "<p>Add <code>?date=YYYY-MM-DD</code> or <code>?date=YYYY-MM-DDTHH:MM:SSZ</code> to "
            "any page address to go to the latest version at or before that time. An address "
            "without a date goes to the latest version. "
            f"<a href=\"{b}/_cav/versions.html\">All versions</a> lists every capture date.</p>"
            "<p>Versions are built from Internet Archive Wayback Machine captures of "
            "constitution.congress.gov. Pages the Archive did not capture link to the "
            f"official site. Source code: <a href=\"{REPO_URL}\">{REPO_URL.removeprefix('https://')}</a>.</p>"
            f"</main>{self.site_footer()}</body></html>"
        )

    def decorate(self, soup: BeautifulSoup, version: str, path: str) -> None:
        self.head_tags(soup, version, path)
        body = soup.body
        body.insert(0, BeautifulSoup(self.banner(version, path), "html.parser"))
        footers = body.find_all("footer")
        target = footers[-1] if footers else body
        target.append(BeautifulSoup(self.footer_line(version, path), "html.parser"))

    # -- build -------------------------------------------------------------

    def write(self, rel_path: str, data: bytes | str) -> None:
        f = self.out / output_file(rel_path)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data.encode() if isinstance(data, str) else data)

    def build_version(self, version: str) -> set[str]:
        files = self.store.manifest(version)["files"]
        pages = set()
        for path, meta in files.items():
            body = self.store.get_blob(meta["sha256"])
            ctype = meta["content_type"]
            fn = self.url_mapper(path, version, files)
            if is_html(ctype):
                pages.add(path)
                soup = parse(body)
                rewrite_html(soup, fn)
                self.decorate(soup, version, path)
                body = str(soup)
            elif ctype.startswith("text/css"):
                body = rewrite_css(body.decode("utf-8", "replace"), lambda u: fn(u, False))
            self.write(versioned(path, version), body)
        return pages

    def stub(self, path: str, latest_with_page: str, not_found: bool = False) -> str:
        b = self.base
        target = f"{b}{versioned(path, latest_with_page)}"
        noscript = "" if not_found else (
            f"<noscript><meta http-equiv=\"refresh\" content=\"0; url={target}\"></noscript>")
        status = "Page not found." if not_found else "Resolving version…"
        meta_path = "" if not_found else html.escape(path)
        return (
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex\">"
            f"<title>Constitution Annotated (versioned demo)</title>"
            f"<meta name=\"cav-version\" content=\"\">"
            f"<meta name=\"cav-path\" content=\"{meta_path}\">"
            f"<meta name=\"cav-base\" content=\"{html.escape(b)}\">"
            f"<link rel=\"stylesheet\" href=\"{b}/_cav/cav.css\">"
            f"<script src=\"{b}/_cav/cav.js\" defer></script>"
            f"{noscript}"
            "</head><body>"
            f"{self.banner('', path)}"
            f"<main id=\"cav-stub\"><p>{status} "
            f"<a href=\"{target}\">Latest version ({display(latest_with_page)})</a></p></main>"
            f"{self.site_footer()}</body></html>"
        )

    def versions_page(self, roots: dict[str, list[str]]) -> str:
        b = self.base
        rows = "".join(
            f"<li><code>{v}</code> {display(v)} — "
            + " · ".join(f'<a href="{b}{versioned(r, v)}">{html.escape(r)}</a>' for r in roots[v])
            + "</li>"
            for v in reversed(self.versions)
        )
        return (
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex\"><title>Archived versions</title>"
            f"<link rel=\"stylesheet\" href=\"{b}/_cav/cav.css\"></head><body>"
            f"{self.banner('', '/')}"
            "<main id=\"cav-versions\"><h1>Archived versions</h1>"
            "<p>Add <code>?date=YYYY-MM-DD</code> or <code>?date=YYYY-MM-DDTHH:MM:SSZ</code> "
            "to any page address to see the latest version at or before that time.</p>"
            f"<ul>{rows}</ul></main>{self.site_footer()}</body></html>"
        )

    def build(self) -> None:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        latest_for: dict[str, str] = {}
        roots: dict[str, list[str]] = {}
        for v in self.versions:
            pages = self.build_version(v)
            for p in pages:
                latest_for[p] = v
            roots[v] = [r for r in ("/browse/", "/resources/") if r in pages]
        for p, v in latest_for.items():
            self.write(p, self.stub(p, v))
        if "/" not in latest_for and "/browse/" in latest_for:
            self.write("/", self.stub("/browse/", latest_for["/browse/"]))
        cav = self.out / "_cav"
        cav.mkdir(exist_ok=True)
        for f in STATIC.iterdir():
            shutil.copy(f, cav / f.name)
        (cav / "versions.json").write_text(json.dumps({"versions": self.versions}))
        (cav / "versions.html").write_text(self.versions_page(roots))
        (cav / "about.html").write_text(self.about_page())
        (self.out / "404.html").write_text(self.stub("/browse/", latest_for.get("/browse/", self.latest), not_found=True))
        (self.out / ".nojekyll").write_text("")
