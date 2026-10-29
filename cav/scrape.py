"""Capture a snapshot of the source site into the store.

`crawl` fetches pages under PAGE_PREFIXES plus every same-host asset they use.
`import_mirror` builds a snapshot from a directory already mirrored by another
tool (e.g. `wget --mirror`), laid out as <host>/<path>.
"""

from __future__ import annotations

import logging
import mimetypes
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from . import PAGE_PREFIXES, SOURCE_BASE
from .links import css_urls, html_urls, parse
from .paths import is_html, normalize, source_path
from .store import Store
from .versions import version_id

log = logging.getLogger(__name__)

USER_AGENT = "constitution-annotated-versioned/0.1 (+https://github.com/aih/constitution-annotated-versioned)"
CRAWL_DELAY = 2.0  # seconds; matches the source's robots.txt Crawl-delay


class Blocked(RuntimeError):
    """The source answered with a bot challenge instead of content."""


def is_page_path(path: str) -> bool:
    return any(path.startswith(p) for p in PAGE_PREFIXES)


def discover(path: str, body: bytes, content_type: str) -> tuple[set[str], set[str]]:
    """(page paths, asset paths) referenced by a captured file."""
    base = SOURCE_BASE + path
    pages: set[str] = set()
    assets: set[str] = set()
    if is_html(content_type):
        soup = parse(body)
        b = soup.find("base", href=True)
        if b:
            base = urljoin(base, b["href"])
        for url, is_nav in html_urls(soup):
            _classify(urljoin(base, url), is_nav, pages, assets)
    elif content_type.startswith("text/css"):
        for url in css_urls(body.decode("utf-8", "replace")):
            _classify(urljoin(base, url), False, pages, assets)
    return pages, assets


def _classify(url: str, is_nav: bool, pages: set, assets: set) -> None:
    if url.startswith("data:"):
        return
    p = source_path(url)
    if p is None:
        return
    if is_nav:
        # robots.txt disallows /*? so query URLs (search, filters) are skipped.
        if not urlsplit(url).query and is_page_path(normalize(p)):
            pages.add(normalize(p))
    else:
        assets.add(p)


def crawl(store: Store, *, seeds=PAGE_PREFIXES, limit: int | None = None,
          delay: float = CRAWL_DELAY, at: datetime | None = None,
          session: requests.Session | None = None) -> str:
    s = session or requests.Session()
    s.headers.setdefault("User-Agent", USER_AGENT)
    version = version_id(at or datetime.now(timezone.utc))
    files: dict[str, dict] = {}
    queue = deque((normalize(p), True) for p in seeds)
    seen = {p for p, _ in queue}
    pages_done = 0
    while queue:
        path, is_page = queue.popleft()
        if is_page and limit is not None and pages_done >= limit:
            continue
        r = s.get(SOURCE_BASE + path, timeout=60)
        if r.status_code in (403, 503) and (
            r.headers.get("cf-mitigated") == "challenge" or b"Just a moment" in r.content[:2000]
        ):
            raise Blocked(f"bot challenge from source at {path}; run the crawl from a network the site serves")
        if r.status_code != 200:
            log.warning("%s %s", r.status_code, path)
            time.sleep(delay)
            continue
        ctype = r.headers.get("Content-Type", "application/octet-stream")
        final = source_path(r.url) or path
        key = normalize(final, ctype) if is_page else final
        files[key] = {"sha256": store.put_blob(r.content), "content_type": ctype}
        if is_page:
            pages_done += 1
        log.info("[%d pages, %d queued] %s", pages_done, len(queue), key)
        pages, assets = discover(key, r.content, ctype)
        for p in pages:
            if p not in seen:
                seen.add(p)
                queue.append((p, True))
        for a in assets:
            if a not in seen:
                seen.add(a)
                queue.appendleft((a, False))
        time.sleep(delay)
    store.write_manifest(version, files)
    return version


def import_mirror(store: Store, directory: str | Path, at: datetime) -> str:
    """Snapshot a directory mirror. `x/index.html` becomes page `/x/`."""
    root = Path(directory)
    files: dict[str, dict] = {}
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(root).as_posix()
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if rel == "index.html" or rel.endswith("/index.html"):
            path = "/" + rel[: -len("index.html")]
        else:
            path = "/" + rel
        if is_html(ctype):
            path = normalize(path, ctype)
        files[path] = {"sha256": store.put_blob(f.read_bytes()), "content_type": ctype}
    version = version_id(at)
    store.write_manifest(version, files)
    return version
