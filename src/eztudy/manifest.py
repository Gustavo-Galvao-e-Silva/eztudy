"""Content-hash manifest of sources/.

Every source is identified by the SHA-256 of its bytes. Extracted text and vector
chunks are keyed by that hash, so agents can freely move/rename files in sources/
without triggering re-extraction or re-embedding.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .workspace import Workspace

MANIFEST_VERSION = 1


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load(ws: Workspace) -> dict:
    if ws.manifest_path.exists():
        data = json.loads(ws.manifest_path.read_text())
        data.setdefault("sources", {})
        return data
    return {"version": MANIFEST_VERSION, "sources": {}}


def save(ws: Workspace, data: dict) -> None:
    ws.ensure_state()
    data["version"] = MANIFEST_VERSION
    data["sources"] = dict(sorted(data["sources"].items()))
    tmp = ws.manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(ws.manifest_path)


@dataclass
class Diff:
    new: list[str] = field(default_factory=list)  # paths
    changed: list[str] = field(default_factory=list)  # paths whose content changed
    moved: list[tuple[str, str]] = field(default_factory=list)  # (old, new)
    deleted: list[str] = field(default_factory=list)  # paths
    unchanged: list[str] = field(default_factory=list)
    current: dict[str, dict] = field(default_factory=dict)  # path -> {hash,size,mtime}

    @property
    def dirty(self) -> bool:
        return bool(self.new or self.changed or self.moved or self.deleted)

    def to_dict(self) -> dict:
        return {
            "new": self.new,
            "changed": self.changed,
            "moved": [{"from": a, "to": b} for a, b in self.moved],
            "deleted": self.deleted,
            "unchanged": len(self.unchanged),
        }


def scan(ws: Workspace, manifest: dict) -> Diff:
    """Compare files on disk with the manifest. Uses size+mtime to skip rehashing."""
    old = manifest["sources"]
    diff = Diff()
    for path in ws.iter_source_files():
        rel = ws.rel(path)
        st = path.stat()
        prev = old.get(rel)
        if prev and prev.get("size") == st.st_size and prev.get("mtime") == st.st_mtime:
            digest = prev["hash"]
        else:
            digest = file_hash(path)
        diff.current[rel] = {"hash": digest, "size": st.st_size, "mtime": st.st_mtime}

    old_by_hash: dict[str, list[str]] = {}
    for rel, entry in old.items():
        old_by_hash.setdefault(entry["hash"], []).append(rel)

    vanished = {rel for rel in old if rel not in diff.current}
    for rel, cur in diff.current.items():
        prev = old.get(rel)
        if prev is None:
            # A new path whose content previously lived at a now-vanished path is a move.
            sources = [p for p in old_by_hash.get(cur["hash"], []) if p in vanished]
            if sources:
                src = sources[0]
                vanished.discard(src)
                diff.moved.append((src, rel))
            else:
                diff.new.append(rel)
        elif prev["hash"] != cur["hash"]:
            diff.changed.append(rel)
        else:
            diff.unchanged.append(rel)
    diff.deleted = sorted(vanished)
    return diff
