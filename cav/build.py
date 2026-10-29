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
            f'See <a href="{official}">constitution.congress.gov</a>.</span>'
            f'{v}<span id="cav-query" hidden></span></div>'
        )

    def footer_line(self, version: str, path: str) -> str:
        b = self.base
        return (
            '<div id="cav-footer">'
            f'Archived version <a href="{b}{versioned(path, version)}">{version}</a> '
            f'({display(version)}) · <a href="{b}{path}">Latest</a> · '
            f'<a href="{b}/_cav/versions.html">All versions</a> · '
            'Demonstration site, not the official Constitution Annotated.</div>'
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
            "</body></html>"
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
            f"<ul>{rows}</ul></main></body></html>"
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
        (self.out / "404.html").write_text(self.stub("/browse/", latest_for.get("/browse/", self.latest), not_found=True))
        (self.out / ".nojekyll").write_text("")
