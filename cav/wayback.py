"""Build snapshots from Internet Archive Wayback Machine captures of the source.

The CDX API lists every capture of a page with its timestamp and status. Each
version is the state of the site as of a chosen instant T: for every page, the
latest capture at or before T (a 404 capture drops the page). By default there
is one version per calendar month that has captures, at the month's latest
capture time. Page bodies come from `id_` URLs, which return the archived bytes
without the Wayback toolbar; assets are fetched at T and resolved by the
Archive to their nearest capture.

The capture listing is saved in <data>/wayback-cdx/ and fetched captures in
<data>/wayback-cache.json, so an interrupted import resumes without repeating
requests. A 429 response slows all later requests.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests

from . import PAGE_PREFIXES, SOURCE_HOST
from .paths import normalize
from .scrape import USER_AGENT, discover, is_page_path
from .store import Store

log = logging.getLogger(__name__)

CDX = "https://web.archive.org/cdx/search/cdx"
RAW = "https://web.archive.org/web/{ts}id_/https://" + SOURCE_HOST + "{path}"
PERIODS = {"year": 4, "month": 6, "day": 8, "capture": 14}
CDX_PAGE = 5000      # rows per CDX request
CDX_DELAY = 5.0      # minimum seconds between CDX requests
MAX_DELAY = 60.0     # ceiling for the delay after repeated 429s
MAX_ATTEMPTS = 8


@dataclass(frozen=True)
class Capture:
    ts: str  # 14-digit Wayback timestamp, UTC
    path: str
    status: int
    mimetype: str


def ts_version(ts: str) -> str:
    return f"{ts[:8]}T{ts[8:14]}Z"


class Wayback:
    def __init__(self, store: Store, *, delay: float = 1.0, session: requests.Session | None = None):
        self.store = store
        self.delay = delay
        self.s = session or requests.Session()
        self.s.headers.setdefault("User-Agent", USER_AGENT)
        self.sleep = time.sleep
        self.cache_file = store.root / "wayback-cache.json"
        self.cache: dict[str, dict] = (
            json.loads(self.cache_file.read_text()) if self.cache_file.exists() else {}
        )

    def get(self, url: str, *, delay: float | None = None, **kw) -> requests.Response:
        """GET with retries. A 429 doubles the delay between all later requests
        (up to MAX_DELAY) and waits Retry-After, or 60 s doubling to 15 min."""
        for attempt in range(MAX_ATTEMPTS):
            wait = min(900, 60 * 2 ** attempt)
            try:
                r = self.s.get(url, timeout=120, **kw)
            except requests.RequestException as e:
                log.warning("%s: %s; retrying in %d s", url, e, wait)
            else:
                if r.status_code not in (429, 502, 503, 504):
                    self.sleep(max(self.delay, delay or 0))
                    return r
                if r.status_code == 429:
                    self.delay = min(MAX_DELAY, max(1.0, self.delay * 2))
                    retry_after = r.headers.get("Retry-After", "")
                    if retry_after.isdigit():
                        wait = int(retry_after)
                    log.warning("rate limited (429); waiting %d s, then %.0f s between requests",
                                wait, self.delay)
                else:
                    log.warning("%s %s; retrying in %d s", r.status_code, url, wait)
            self.sleep(wait)
        raise RuntimeError(f"giving up on {url} after {MAX_ATTEMPTS} attempts; rerun to resume")

    # -- listing -----------------------------------------------------------

    def captures(self, prefixes=PAGE_PREFIXES) -> list[Capture]:
        """All page captures under the prefixes.

        collapse=digest drops consecutive captures of a URL with unchanged
        content. Each listed page of results is appended to
        <data>/wayback-cdx/<prefix>.jsonl and the resume key saved beside it,
        so an interrupted listing continues where it stopped.
        """
        out: list[Capture] = []
        for prefix in prefixes:
            d = self.store.root / "wayback-cdx"
            d.mkdir(parents=True, exist_ok=True)
            name = prefix.strip("/").replace("/", "_") or "root"
            rows_file, state_file = d / f"{name}.jsonl", d / f"{name}.state.json"
            state = json.loads(state_file.read_text()) if state_file.exists() else {}
            params = {
                "url": SOURCE_HOST + prefix + "*",
                "output": "json",
                "fl": "timestamp,original,statuscode,mimetype",
                "filter": "statuscode:(200|404)",
                "collapse": "digest",
                "showResumeKey": "true",
                "limit": str(CDX_PAGE),
            }
            if state.get("resume"):
                params["resumeKey"] = state["resume"]
            while not state.get("done"):
                rows = self.get(CDX, params=params, delay=CDX_DELAY).json()
                resume = None
                if len(rows) >= 2 and rows[-2] == []:
                    resume = rows[-1][0]
                    rows = rows[:-2]
                with rows_file.open("a") as f:
                    for row in rows[1:]:
                        f.write(json.dumps(row) + "\n")
                state = {"resume": resume, "done": not resume}
                write_atomic(state_file, json.dumps(state))
                log.info("%s: listed through %s", prefix, rows[-1][1] if len(rows) > 1 else "end")
                if resume:
                    params["resumeKey"] = resume
            n = 0
            if rows_file.exists():
                with rows_file.open() as f:
                    for line in f:
                        c = to_capture(*json.loads(line))
                        if c:
                            out.append(c)
                            n += 1
            log.info("%s: %d captures", prefix, n)
        return sorted(set(out), key=lambda c: (c.ts, c.path))

    # -- fetching ----------------------------------------------------------

    def page(self, c: Capture) -> dict | None:
        key = f"{c.ts} {c.path}"
        if key not in self.cache:
            r = self.get(RAW.format(ts=c.ts, path=c.path))
            if r.status_code != 200:
                log.warning("%s fetching capture %s", r.status_code, key)
                return None
            ctype = r.headers.get("Content-Type") or c.mimetype
            self.cache[key] = {"sha256": self.store.put_blob(r.content), "content_type": ctype}
            self.save_cache()
        return self.cache[key]

    def asset(self, path: str, ts: str) -> dict | None:
        r = self.get(RAW.format(ts=ts, path=path))
        if r.status_code != 200:
            log.warning("%s fetching asset %s at %s", r.status_code, path, ts)
            return None
        ctype = r.headers.get("Content-Type") or mimetypes.guess_type(path)[0] or "application/octet-stream"
        return {"sha256": self.store.put_blob(r.content), "content_type": ctype}

    def save_cache(self) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(self.cache_file, json.dumps(self.cache))

    # -- snapshots ---------------------------------------------------------

    def snapshot(self, captures: list[Capture], ts: str) -> str:
        latest: dict[str, Capture] = {}
        for c in captures:
            if c.ts <= ts:
                latest[c.path] = c
        files: dict[str, dict] = {}
        assets: set[str] = set()
        for path, c in sorted(latest.items()):
            if c.status != 200:
                continue
            meta = self.page(c)
            if meta is None:
                continue
            files[path] = meta
            _, found = discover(path, self.store.get_blob(meta["sha256"]), meta["content_type"])
            assets |= found
        done: set[str] = set()
        while assets:
            a = assets.pop()
            done.add(a)
            meta = self.asset(a, ts)
            if meta is None:
                continue
            files[a] = meta
            _, found = discover(a, self.store.get_blob(meta["sha256"]), meta["content_type"])
            assets |= found - done
        v = ts_version(ts)
        self.store.write_manifest(v, files, source=f"wayback:{ts}")
        log.info("version %s: %d files", v, len(files))
        return v


def write_atomic(path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def to_capture(ts: str, original: str, status: str, mime: str) -> Capture | None:
    parts = urlsplit(original)
    if (parts.hostname or "").lower() != SOURCE_HOST or parts.query or not status.isdigit():
        return None
    path = normalize(parts.path or "/")
    if not is_page_path(path) or not (mime.startswith("text/html") or status == "404"):
        return None
    return Capture(ts, path, int(status), mime)


def version_times(captures: list[Capture], every: str = "month",
                  since: str | None = None, until: str | None = None) -> list[str]:
    """Latest capture timestamp in each period that has captures."""
    n = PERIODS[every]
    by_period: dict[str, str] = {}
    for c in captures:
        if (since and c.ts < since) or (until and c.ts > until):
            continue
        k = c.ts[:n]
        by_period[k] = max(by_period.get(k, ""), c.ts)
    return sorted(by_period.values())


def import_wayback(store: Store, *, every: str = "month", since: datetime | None = None,
                   until: datetime | None = None, delay: float = 1.0, refresh: bool = False,
                   session: requests.Session | None = None) -> list[str]:
    if refresh:
        for f in (store.root / "wayback-cdx").glob("*"):
            f.unlink()
    wb = Wayback(store, delay=delay, session=session)
    caps = wb.captures()
    fmt = lambda d: d.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S") if d else None
    times = version_times(caps, every, fmt(since), fmt(until))
    existing = set(store.versions())
    made = []
    for ts in times:
        if ts_version(ts) in existing:
            log.info("version %s exists; skipping", ts_version(ts))
            continue
        made.append(wb.snapshot(caps, ts))
    return made
