"""Command line: cav {scrape,import,build,resolve,serve}, plus cav-scrape, cav-build, cav-serve."""

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
    elif args.cmd == "build":
        Builder(store, args.out, args.base).build()
        print(f"built {len(store.versions())} versions into {args.out}")
    elif args.cmd == "resolve":
        print(resolve(store.versions(), args.date) or "no version at or before " + version_id(parse_query(args.date)))
    elif args.cmd == "serve":
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=args.out)
        print(f"http://localhost:{args.port}/")
        http.server.ThreadingHTTPServer(("", args.port), handler).serve_forever()


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
build = _sub("build")
serve = _sub("serve")


if __name__ == "__main__":
    main()
