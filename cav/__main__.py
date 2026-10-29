"""Command line: cav {scrape,import,import-wayback,build,resolve,serve}, plus cav-scrape,
cav-wayback, cav-build, cav-serve."""

from __future__ import annotations

import argparse
import functools
import http.server
import logging
from datetime import datetime, timezone

from .build import Builder
from .scrape import Blocked, crawl, import_mirror
from .store import Store
from .versions import parse_query, resolve, version_id
from .wayback import PERIODS, import_wayback


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="cav")
    ap.add_argument("--data", default="data", help="snapshot store directory (default: data)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scrape", help="crawl the source site into a new snapshot")
    s.add_argument("--limit", type=int, help="stop after this many pages")
    s.add_argument("--delay", type=float, default=2.0, help="seconds between requests")

    i = sub.add_parser("import", help="snapshot a directory mirror (<host>/<path> layout)")
    i.add_argument("directory")
    i.add_argument("--at", help="snapshot datetime (default: now)")

    w = sub.add_parser("import-wayback", help="build versions from Wayback Machine captures")
    w.add_argument("--every", choices=list(PERIODS), default="month",
                   help="one version per period that has captures (default: month)")
    w.add_argument("--since", help="ignore captures before this datetime")
    w.add_argument("--until", help="ignore captures after this datetime")
    w.add_argument("--delay", type=float, default=1.0, help="seconds between requests")

    b = sub.add_parser("build", help="generate the static site")
    b.add_argument("--out", default="dist")
    b.add_argument("--base", default="", help="URL path prefix when hosted below the domain root")

    r = sub.add_parser("resolve", help="print the version a ?date= value resolves to")
    r.add_argument("date")

    v = sub.add_parser("serve", help="serve the built site locally")
    v.add_argument("--out", default="dist")
    v.add_argument("--port", type=int, default=8000)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    store = Store(args.data)

    if args.cmd == "scrape":
        try:
            print(crawl(store, limit=args.limit, delay=args.delay))
        except Blocked as e:
            raise SystemExit(f"error: {e}")
    elif args.cmd == "import":
        at = parse_query(args.at) if args.at else datetime.now(timezone.utc)
        print(import_mirror(store, args.directory, at))
    elif args.cmd == "import-wayback":
        made = import_wayback(
            store, every=args.every, delay=args.delay,
            since=_start(args.since) if args.since else None,
            until=parse_query(args.until) if args.until else None,
        )
        print("\n".join(made) or "no new versions")
    elif args.cmd == "build":
        Builder(store, args.out, args.base).build()
        print(f"built {len(store.versions())} versions into {args.out}")
    elif args.cmd == "resolve":
        print(resolve(store.versions(), args.date) or "no version at or before " + version_id(parse_query(args.date)))
    elif args.cmd == "serve":
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=args.out)
        print(f"http://localhost:{args.port}/")
        http.server.ThreadingHTTPServer(("", args.port), handler).serve_forever()


def _start(q: str) -> datetime:
    """Earliest instant a partial datetime covers, e.g. '2024' -> 2024-01-01T00:00:00Z."""
    from .versions import _QUERY_RE
    g = _QUERY_RE.match(q.strip()).groupdict()
    pad = {"mo": "01", "d": "01", "h": "00", "mi": "00", "s": "00"}
    vals = {k: g[k] or pad[k] for k in pad}
    return datetime(int(g["y"]), *(int(vals[k]) for k in ("mo", "d", "h", "mi", "s")), tzinfo=timezone.utc)


def _sub(cmd: str):
    def run() -> None:
        import sys
        # Global options (--data) go before the subcommand.
        args = sys.argv[1:]
        pre = []
        while args and args[0] == "--data":
            pre += args[:2]
            args = args[2:]
        main(pre + [cmd] + args)
    return run


scrape = _sub("scrape")
wayback = _sub("import-wayback")
build = _sub("build")
serve = _sub("serve")


if __name__ == "__main__":
    main()
