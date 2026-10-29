"""Content-addressed snapshot store.

data/
  blobs/<sha[:2]>/<sha>        file bodies, shared across snapshots
  snapshots/<version>.json     {"version", "source", "files": {path: {sha256, content_type}}}
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import SOURCE_BASE


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.blobs = self.root / "blobs"
        self.snapshots = self.root / "snapshots"

    def versions(self) -> list[str]:
        if not self.snapshots.is_dir():
            return []
        return sorted(p.stem for p in self.snapshots.glob("*.json"))

    def manifest(self, version: str) -> dict:
        return json.loads((self.snapshots / f"{version}.json").read_text())

    def put_blob(self, body: bytes) -> str:
        sha = hashlib.sha256(body).hexdigest()
        p = self.blobs / sha[:2] / sha
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(body)
        return sha

    def get_blob(self, sha: str) -> bytes:
        return (self.blobs / sha[:2] / sha).read_bytes()

    def write_manifest(self, version: str, files: dict, source: str = SOURCE_BASE) -> Path:
        self.snapshots.mkdir(parents=True, exist_ok=True)
        p = self.snapshots / f"{version}.json"
        data = {"version": version, "source": source, "files": dict(sorted(files.items()))}
        p.write_text(json.dumps(data, indent=1) + "\n")
        return p
