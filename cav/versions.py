"""Version identifiers and date-query resolution.

A version id is a UTC timestamp in ISO 8601 basic format, e.g. 20261029T194658Z.
It sorts lexically in time order and is safe in URLs and file names.
"""

from __future__ import annotations

import bisect
import re
from datetime import datetime, timedelta, timezone

VERSION_RE = re.compile(r"^\d{8}T\d{6}Z$")

_QUERY_RE = re.compile(
    r"^(?P<y>\d{4})(?:-?(?P<mo>\d{2})(?:-?(?P<d>\d{2})"
    r"(?:[T ](?P<h>\d{2})(?::?(?P<mi>\d{2})(?::?(?P<s>\d{2})(?:\.\d+)?)?)?)?)?)?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)


def is_version_id(s: str) -> bool:
    return bool(VERSION_RE.match(s))


def version_id(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_version_id(v: str) -> datetime:
    return datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def display(v: str) -> str:
    """20261029T194658Z -> '2026-10-29 19:46:58 UTC'."""
    return parse_version_id(v).strftime("%Y-%m-%d %H:%M:%S UTC")


def parse_query(q: str) -> datetime:
    """Parse a ?date= value into the latest UTC instant it denotes.

    Accepts a year, year-month, date, or date-time, in extended or basic ISO 8601
    form, with an optional Z or +HH:MM offset (UTC when absent). A partial value
    covers its whole period: '2025-03-01' means through 2025-03-01T23:59:59Z.
    """
    m = _QUERY_RE.match(q.strip())
    if not m:
        raise ValueError(f"unrecognized date: {q!r}")
    g = m.groupdict()
    y = int(g["y"])
    if g["mo"] is None:
        start, end = datetime(y, 1, 1), datetime(y + 1, 1, 1)
    elif g["d"] is None:
        mo = int(g["mo"])
        start = datetime(y, mo, 1)
        end = datetime(y + (mo == 12), mo % 12 + 1, 1)
    else:
        start = datetime(y, int(g["mo"]), int(g["d"]))
        if g["h"] is None:
            end = start + timedelta(days=1)
        else:
            start = start.replace(hour=int(g["h"]))
            if g["mi"] is None:
                end = start + timedelta(hours=1)
            else:
                start = start.replace(minute=int(g["mi"]))
                if g["s"] is None:
                    end = start + timedelta(minutes=1)
                else:
                    start = start.replace(second=int(g["s"]))
                    end = start + timedelta(seconds=1)
    tz = timezone.utc
    if g["tz"] and g["tz"] != "Z":
        t = g["tz"].replace(":", "")
        sign = 1 if t[0] == "+" else -1
        tz = timezone(sign * timedelta(hours=int(t[1:3]), minutes=int(t[3:5])))
    return (end - timedelta(seconds=1)).replace(tzinfo=tz).astimezone(timezone.utc)


def resolve(versions: list[str], q: str) -> str | None:
    """Latest version at or before the instant denoted by q; None if q precedes all."""
    target = version_id(parse_query(q))
    vs = sorted(versions)
    i = bisect.bisect_right(vs, target)
    return vs[i - 1] if i else None
