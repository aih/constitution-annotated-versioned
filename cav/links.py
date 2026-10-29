"""Finding and rewriting URLs in HTML and CSS."""

from __future__ import annotations

import re
from typing import Callable, Iterator

from bs4 import BeautifulSoup

# (tag, attribute) pairs that hold a single URL.
URL_ATTRS = [
    ("a", "href"), ("area", "href"), ("link", "href"), ("base", "href"),
    ("script", "src"), ("img", "src"), ("iframe", "src"), ("embed", "src"),
    ("source", "src"), ("track", "src"), ("audio", "src"), ("video", "src"),
    ("video", "poster"), ("input", "src"), ("form", "action"), ("object", "data"),
    ("img", "data-src"), ("use", "href"), ("use", "xlink:href"), ("image", "href"),
]
# Attributes that hold "url size, url size" lists.
SRCSET_ATTRS = [("img", "srcset"), ("source", "srcset")]

CSS_URL_RE = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)|@import\s+(['"])([^'"]+)\3""")

# Elements whose URLs are page navigation rather than page resources.
NAV_TAGS = {"a", "area", "form", "iframe"}


def parse(html: bytes | str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def css_urls(css: str) -> list[str]:
    return [m.group(2) or m.group(4) for m in CSS_URL_RE.finditer(css)]


def rewrite_css(css: str, fn: Callable[[str], str]) -> str:
    def sub(m: re.Match) -> str:
        if m.group(2) is not None:
            return f"url({m.group(1)}{fn(m.group(2).strip())}{m.group(1)})"
        return f"@import {m.group(3)}{fn(m.group(4))}{m.group(3)}"
    return CSS_URL_RE.sub(sub, css)


def html_urls(soup: BeautifulSoup) -> Iterator[tuple[str, bool]]:
    """Yield (url, is_navigation) for every URL in the document."""
    for tag, attr in URL_ATTRS:
        for el in soup.find_all(tag):
            v = el.get(attr)
            if v:
                is_nav = tag in NAV_TAGS or (tag == "link" and _link_is_nav(el))
                yield v.strip(), is_nav
    for tag, attr in SRCSET_ATTRS:
        for el in soup.find_all(tag):
            for item in (el.get(attr) or "").split(","):
                if item.strip():
                    yield item.strip().split()[0], False
    for el in soup.find_all(style=True):
        for u in css_urls(el["style"]):
            yield u, False
    for el in soup.find_all("style"):
        for u in css_urls(el.get_text()):
            yield u, False


def rewrite_html(soup: BeautifulSoup, fn: Callable[[str, bool], str]) -> None:
    """Rewrite every URL in place with fn(url, is_navigation)."""
    for tag, attr in URL_ATTRS:
        for el in soup.find_all(tag):
            v = el.get(attr)
            if v:
                is_nav = tag in NAV_TAGS or (tag == "link" and _link_is_nav(el))
                el[attr] = fn(v.strip(), is_nav)
    for tag, attr in SRCSET_ATTRS:
        for el in soup.find_all(tag):
            v = el.get(attr)
            if not v:
                continue
            items = []
            for item in v.split(","):
                bits = item.strip().split(None, 1)
                if bits:
                    items.append(" ".join([fn(bits[0], False)] + bits[1:]))
            el[attr] = ", ".join(items)
    for el in soup.find_all(style=True):
        el["style"] = rewrite_css(el["style"], lambda u: fn(u, False))
    for el in soup.find_all("style"):
        if el.string:
            el.string = rewrite_css(el.string, lambda u: fn(u, False))


def _link_is_nav(el) -> bool:
    rel = {r.lower() for r in (el.get("rel") or [])}
    return bool(rel & {"canonical", "alternate", "next", "prev", "prefetch", "prerender"}) \
        and not rel & {"stylesheet", "icon", "preload"}
