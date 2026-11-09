"""Locate a notebook workspace (a directory containing `sources/`) and its paths."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = {
    "embedding_model": "BAAI/bge-small-en-v1.5",
    "chunk_tokens": 400,
    "chunk_overlap": 60,
    # `eztudy coverage`: share of a topic's words found in one matching chunk, and the vector
    # similarity that alone counts as partial coverage (depends on the embedding model).
    "coverage_covered": 0.6,
    "coverage_partial": 0.3,
    "coverage_min_similarity": 0.75,
}

# Files under sources/ that are never treated as sources.
IGNORED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


class WorkspaceError(RuntimeError):
    pass


@dataclass
class Workspace:
    root: Path
    config: dict = field(default_factory=dict)

    @property
    def sources(self) -> Path:
        return self.root / "sources"

    @property
    def wiki(self) -> Path:
        return self.root / "wiki"

    @property
    def study(self) -> Path:
        return self.root / "study"

    @property
    def state(self) -> Path:
        return self.root / ".eztudy"

    @property
    def text_dir(self) -> Path:
        return self.state / "text"

    @property
    def manifest_path(self) -> Path:
        return self.state / "manifest.json"

    @property
    def db_path(self) -> Path:
        return self.state / "index.db"

    @property
    def config_path(self) -> Path:
        return self.state / "config.toml"

    def ensure_state(self) -> None:
        self.text_dir.mkdir(parents=True, exist_ok=True)

    def rel(self, path: Path) -> str:
        """Path relative to sources/, posix style (the canonical source id for humans)."""
        return path.resolve().relative_to(self.sources.resolve()).as_posix()

    def iter_source_files(self):
        for dirpath, dirnames, filenames in os.walk(self.sources):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                if name.startswith(".") or name in IGNORED_NAMES or name.startswith("~$"):
                    continue
                yield Path(dirpath) / name


def find_workspace(start: str | os.PathLike | None = None) -> Workspace:
    """Walk up from `start` (default: $EZTUDY_ROOT or cwd) to a dir containing `sources/`."""
    start_path = Path(start or os.environ.get("EZTUDY_ROOT") or os.getcwd()).resolve()
    for candidate in [start_path, *start_path.parents]:
        if (candidate / "sources").is_dir():
            return Workspace(root=candidate, config=_load_config(candidate))
    raise WorkspaceError(
        f"No `sources/` directory found at or above {start_path}. "
        "Create one and put your study material in it."
    )


def _load_config(root: Path) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    path = root / ".eztudy" / "config.toml"
    if path.exists():
        with path.open("rb") as fh:
            cfg.update(tomllib.load(fh))
    return cfg
