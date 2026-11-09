"""`eztudy add`: copy files from other folders into sources/, remembering where each came from.

`.eztudy/origins.json` maps a path in sources/ to its original file plus the hash/size/mtime it had
when copied, so `status` can say when an original has changed and re-running `add` can refresh it.
"""

from __future__ import annotations

import json
import os
import shutil
from fnmatch import fnmatch
from pathlib import Path

from .manifest import file_hash
from .workspace import IGNORED_NAMES, Workspace

VERSION = 1
DEFAULT_EXCLUDES = [
    ".*", "out", "build", "dist", "target", "bin", "obj", "node_modules", "__pycache__", "venv",
    "*.iml", "*.class", "*.o", "*.obj", "*.pyc", "*.jar", "*.war", "*.zip", "*.tar", "*.gz", "*.7z",
    "*.exe", "*.dll", "*.so", "*.dylib", "*.lock", "~$*",
]


def _path(ws: Workspace) -> Path:
    return ws.state / "origins.json"


def load(ws: Workspace) -> dict:
    p = _path(ws)
    if p.exists():
        data = json.loads(p.read_text())
        data.setdefault("files", {})
        return data
    return {"version": VERSION, "files": {}}


def save(ws: Workspace, data: dict) -> None:
    ws.ensure_state()
    data["version"] = VERSION
    data["files"] = dict(sorted(data["files"].items()))
    tmp = _path(ws).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(_path(ws))


def excluded(parts: tuple[str, ...], patterns: list[str]) -> bool:
    return any(part in IGNORED_NAMES or any(fnmatch(part, pat) for pat in patterns) for part in parts)


def plan(src: Path, dest_prefix: str, patterns: list[str]) -> list[tuple[Path, str]]:
    """(source file, path relative to sources/) for everything to copy from `src`."""
    if src.is_file():
        return [] if excluded((src.name,), patterns) else [(src, f"{dest_prefix}{src.name}")]
    out = []
    for dirpath, dirnames, filenames in os.walk(src):
        rel_dir = Path(dirpath).relative_to(src)
        dirnames[:] = sorted(d for d in dirnames if not excluded((d,), patterns))
        for name in sorted(filenames):
            rel = rel_dir / name
            if not excluded(rel.parts, patterns):
                out.append((Path(dirpath) / name, f"{dest_prefix}{rel.as_posix()}"))
    return out


def _record(origin: Path) -> dict:
    st = origin.stat()
    return {"origin": str(origin), "hash": file_hash(origin), "size": st.st_size, "mtime": st.st_mtime}


def add(ws: Workspace, srcs: list[Path], name: str | None, patterns: list[str], dry_run: bool = False) -> dict:
    data = load(ws)
    files = data["files"]
    log: dict[str, list] = {"copied": [], "updated": [], "unchanged": [], "conflicts": []}
    sources_root = ws.sources.resolve()
    for src in srcs:
        src = src.resolve()
        if not src.exists():
            raise FileNotFoundError(f"{src} does not exist")
        if src == sources_root or sources_root in src.parents:
            raise ValueError(f"{src} is already inside sources/")
        if name:
            prefix = f"{name.strip('/')}/"
        else:
            prefix = f"{src.name}/" if src.is_dir() else ""
        for origin, rel in plan(src, prefix, patterns):
            dest = ws.sources / rel
            if not dest.exists():
                log["copied"].append(rel)
                if not dry_run:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(origin, dest)
                    files[rel] = _record(origin)
                continue
            rec = files.get(rel)
            new_hash, dest_hash = file_hash(origin), file_hash(dest)
            if new_hash == dest_hash:
                log["unchanged"].append(rel)
                if not dry_run:
                    files[rel] = _record(origin)
            elif rec and rec["origin"] == str(origin) and rec["hash"] == dest_hash:
                # The copy is untouched since we made it; the original moved on: refresh it.
                log["updated"].append(rel)
                if not dry_run:
                    shutil.copy2(origin, dest)
                    files[rel] = _record(origin)
            else:
                log["conflicts"].append({"path": rel, "origin": str(origin),
                                         "reason": "a different file is already at this path in sources/"})
    if not dry_run:
        save(ws, data)
    return log


def changed(ws: Workspace) -> list[dict]:
    """Copies whose original has changed (or vanished) since it was copied. Hashes only on stat change."""
    data = load(ws)
    out, dirty = [], False
    for rel, rec in data["files"].items():
        origin = Path(rec["origin"])
        try:
            st = origin.stat()
        except OSError:
            out.append({"path": rel, "origin": rec["origin"], "state": "missing"})
            continue
        if st.st_size == rec["size"] and st.st_mtime == rec["mtime"]:
            continue
        if file_hash(origin) != rec["hash"]:
            out.append({"path": rel, "origin": rec["origin"], "state": "changed"})
        else:  # touched but identical: remember the new stat so we don't rehash next time
            rec.update(size=st.st_size, mtime=st.st_mtime)
            dirty = True
    if dirty:
        save(ws, data)
    return out


def follow_sync(ws: Workspace, moved: list[tuple[str, str]], deleted: list[str]) -> None:
    """Keep origin links attached to copies that were moved/renamed inside sources/, drop deleted ones."""
    if not _path(ws).exists() or not (moved or deleted):
        return
    data = load(ws)
    files = data["files"]
    for old, new in moved:
        if old in files:
            files[new] = files.pop(old)
    for rel in deleted:
        files.pop(rel, None)
    save(ws, data)
