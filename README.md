# Constitution Annotated, versioned

A static mirror of the [Constitution Annotated](https://constitution.congress.gov/)
(`/browse/` and `/resources/`) that keeps every captured version at a permanent
address and resolves `?date=` queries to the version in force at that time.
It is a demonstration, not the official site.

## Addresses

| Address | Serves |
| --- | --- |
| `/browse/20260601T083000Z/essay/artII-S1-C1-3/ALDE_00013792/` | that page as captured at 2026-06-01 08:30:00 UTC |
| `/browse/essay/artII-S1-C1-3/ALDE_00013792/` | redirects to the latest version of the page |
| `/browse/essay/artII-S1-C1-3/ALDE_00013792/?date=2026-03-01` | redirects to the latest version at or before the date, keeping `?date=` in the address |
| `/browse/20260601T083000Z/...?date=2026-03-01` | same resolution; a versioned address with a different `?date=` is redirected |
| `/_cav/versions.html` | list of all versions |

Version ids are UTC timestamps in ISO 8601 basic format (`YYYYMMDDTHHMMSSZ`).
The version id goes after the first path segment, so `/resources/x/` becomes
`/resources/<version>/x/` and assets such as `/css/site.css` become
`/css/<version>/site.css`.

`?date=` accepts `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, `YYYY-MM-DDTHH`,
`YYYY-MM-DDTHH:MM`, `YYYY-MM-DDTHH:MM:SS`, or the basic forms without
separators, with an optional `Z` or `±HH:MM` offset (UTC when absent). A partial
value covers its whole period: `2026-03-01` resolves to the latest version
captured on or before 2026-03-01 23:59:59 UTC. Queries that precede the first
version, or name a page that did not exist yet, show a notice instead of
redirecting.

Each archived page is the source HTML with these additions:

- a banner at the top marking the site as a demonstration, linking to the same
  page on the official site, and showing the version datetime (and the queried
  datetime when `?date=` is present)
- a line in the footer with the version id, links to the latest version and
  the version list
- `noindex` robots meta
- links and asset URLs rewritten to the same version; links to pages outside
  the captured sections (`/about/`, search) point to the official site

## Date resolution

Resolution runs in the browser (`cav/static/cav.js`), since the output is
plain static files. It reads `/_cav/versions.json`, picks the newest version at
or before the query, confirms that version has the page with a `HEAD` request
(falling back to older versions), and calls `location.replace`. Without
JavaScript, unversioned addresses fall back to a meta refresh to the latest
version and `?date=` is ignored. A host with edge functions (Cloudflare Pages,
Netlify) could do the same resolution server-side as a 302 using
`cav/versions.py` logic and `versions.json`.

## Usage

Requires [uv](https://docs.astral.sh/uv/). `uv sync` installs Python 3.12
(from `.python-version`) and the dependencies into `.venv/`.

```sh
uv sync

uv run cav-scrape --limit 5          # quick check that the source serves your network
uv run cav-scrape                    # crawl the source into data/ as a new version
uv run cav-build                     # generate the site into dist/
uv run cav-serve                     # http://localhost:8000/browse/

uv run cav-build --base /repo-name   # URLs prefixed for hosting below the domain root
uv run cav import <dir> --at 2026-06-01T08:30:00Z   # snapshot an existing mirror directory
uv run cav resolve 2026-03-01        # print the version a date resolves to
```

`cav-scrape`, `cav-build` and `cav-serve` are shorthand for `cav scrape`,
`cav build` and `cav serve`. All commands take `--data <dir>` (default `data`)
before other options to use a different snapshot store.

`scrape` starts at `/browse/` and `/resources/`, follows links within those
sections, captures every same-host stylesheet, script, image, and font they
use (including `url()` references in CSS), waits 2 seconds between requests
(the source's robots.txt `Crawl-delay`), and skips URLs with query strings
(disallowed by robots.txt). It stops with an error if the source answers with
a bot challenge.

`import` takes a directory laid out as `<path>` under the host, such as the
`constitution.congress.gov/` folder produced by `wget --mirror`.

## Storage

```
data/blobs/<sha256[:2]>/<sha256>   file bodies, deduplicated across versions
data/snapshots/<version>.json      path -> {sha256, content_type} for one version
```

`build` writes a full copy of every version, so output size grows with the
number of versions while `data/` grows only with changed files.

## Layout

| Path | Contents |
| --- | --- |
| `cav/scrape.py` | crawler and mirror import |
| `cav/store.py` | snapshot store |
| `cav/build.py` | static site generator |
| `cav/links.py` | URL discovery and rewriting in HTML and CSS |
| `cav/paths.py` | source path ↔ versioned path mapping |
| `cav/versions.py` | version ids, `?date=` parsing and resolution |
| `cav/static/` | banner CSS and resolver JS copied to `/_cav/` |
| `tests/` | unit tests, browser test, two-version synthetic fixture |
| `.github/workflows/site.yml` | tests on every push; builds and deploys to GitHub Pages from `main` when `data/snapshots/` is non-empty |

## Tests

```sh
uv run python -m unittest discover -s tests -t .

uv run cav --data /tmp/fx import tests/fixtures/v1/constitution.congress.gov --at 2026-01-15T12:00:00Z
uv run cav --data /tmp/fx import tests/fixtures/v2/constitution.congress.gov --at 2026-06-01T08:30:00Z
uv run cav --data /tmp/fx build --out /tmp/fx-dist
uv run cav serve --out /tmp/fx-dist --port 8765 &
node tests/e2e.cjs http://localhost:8765   # needs the playwright npm package
```
