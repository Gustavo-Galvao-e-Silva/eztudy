"""Per-user preferences that outlive a notebook, e.g. the last TUI theme picked (`~/.config/eztudy/prefs.json`)."""

from __future__ import annotations

import json
import os
from pathlib import Path


def path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "eztudy" / "prefs.json"


def load() -> dict:
    try:
        data = json.loads(path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(**values) -> None:
    """Merge `values` into the prefs file; best effort (a read-only home must not break the caller)."""
    data = {**load(), **values}
    try:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.replace(p)
    except OSError:
        pass


def tui_theme(config: dict) -> str | None:
    """The theme to start with: the one last picked in the TUI, else `[ui] tui_theme` from the notebook config."""
    return load().get("tui_theme") or (config.get("ui") or {}).get("tui_theme")
