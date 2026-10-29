"""Mapping between source URL paths and versioned site paths."""

from __future__ import annotations

import posixpath
from urllib.parse import urlsplit

from . import SOURCE_HOST
from .versions import is_version_id

HTML_TYPES = ("text/html", "application/xhtml+xml")


def is_html(content_type: str) -> bool:
    return content_type.split(";")[0].strip().lower() in HTML_TYPES


def normalize(path: str, content_type: str | None = None) -> str:
    """Canonical source path: leading slash, and a trailing slash on HTML pages
    whose last segment has no file extension."""
    trailing = path.endswith("/")
    path = posixpath.normpath("/" + path.lstrip("/"))
    if trailing and path != "/":
        path += "/"
    last = path.rsplit("/", 1)[-1]
    if last and "." not in last and (content_type is None or is_html(content_type)):
        path += "/"
    return path


def source_path(url: str) -> str | None:
    """Path on the source host for an absolute or root-relative URL, else None."""
    parts = urlsplit(url)
    if parts.scheme not in ("", "http", "https"):
        return None
    if parts.netloc and parts.netloc.lower() != SOURCE_HOST:
        return None
    return parts.path or "/"


def versioned(path: str, version: str) -> str:
    """Insert the version id after the first path segment.

    /browse/essay/x/ -> /browse/<v>/essay/x/
    /css/site.css    -> /css/<v>/site.css
    /favicon.ico     -> /<v>/favicon.ico
    /                -> /<v>/
    """
    rest = path.lstrip("/")
    if "/" in rest:
        first, tail = rest.split("/", 1)
        return f"/{first}/{version}/{tail}"
    return f"/{version}/{rest}"


def unversioned(path: str) -> tuple[str, str | None]:
    """Inverse of versioned(): (source path, version or None)."""
    segs = path.lstrip("/").split("/")
    if segs and is_version_id(segs[0]):
        return "/" + "/".join(segs[1:]), segs[0]
    if len(segs) > 1 and is_version_id(segs[1]):
        return "/" + "/".join([segs[0]] + segs[2:]), segs[1]
    return path, None


def output_file(path: str) -> str:
    """Relative file name to write for a site path."""
    rel = path.lstrip("/")
    if rel == "" or rel.endswith("/"):
        rel += "index.html"
    return rel
