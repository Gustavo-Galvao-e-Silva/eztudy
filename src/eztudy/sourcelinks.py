"""Clickable citations: map each citation in a quiz/deck to a source file and a place in it.

`links(ws, data)` returns {citation key: {"path", "type", "page"|"slide"|"line"+"end"}} where the key is what the
player looks up (`cite_key`: an object citation's `cid`, else `source#location`; a string as written) and `path` is
relative to `sources/`. The source is found by chunk-id hash (survives moves), exact path, or unique file name.
`viewer()` renders a source for `eztudy serve` with the cited page, slide or lines in view.
"""

from __future__ import annotations

import html
import re
from pathlib import PurePosixPath

from . import extract as extracting
from . import manifest as mf
from .workspace import Workspace

_PAGE = re.compile(r"\b(?:pages?|pp?\.?)\s*(\d+)", re.I)
_SLIDE = re.compile(r"\bslides?\s*(\d+)", re.I)
_LINES = re.compile(r"\blines?\s*(\d+)(?:\s*[-–]\s*(\d+))?", re.I)
_PATH_LINES = re.compile(r"^(?P<path>[^\s:()]+\.\w+)(?::(?P<a>\d+)(?:[-–](?P<b>\d+))?)?(?P<rest>.*)$")


def parse_location(text: str) -> dict:
    """"page 4", "pages 1-2", "p.4", "slide 3", "lines 340-375" -> {"page": 4} / {"slide": 3} / {"line", "end"}."""
    text = text or ""
    if m := _LINES.search(text):
        return {"line": int(m.group(1)), "end": int(m.group(2) or m.group(1))}
    if m := _SLIDE.search(text):
        return {"slide": int(m.group(1))}
    if m := _PAGE.search(text):
        return {"page": int(m.group(1))}
    return {}


def cite_key(c) -> str | None:
    """Mirrors citeKey() in templates/player/app.js."""
    if isinstance(c, str):
        return c
    if isinstance(c, dict):
        return c.get("cid") or (f"{c['source']}#{c.get('location') or ''}" if c.get("source") else None)
    return None


def _split_string(cite: str) -> tuple[str, dict]:
    """"bio/cells.pdf (pages 4-5)", "hw2/BST.java:340-375 (removeRecurse)", "cells.pdf p.4" -> (path, location)."""
    m = _PATH_LINES.match(cite.strip())
    if not m:
        return cite.strip(), {}
    if m.group("a"):
        a = int(m.group("a"))
        return m.group("path"), {"line": a, "end": int(m.group("b") or a)}
    return m.group("path"), parse_location(m.group("rest"))


class Resolver:
    def __init__(self, ws: Workspace):
        self.entries = mf.load(ws)["sources"] if ws.state.exists() else {}
        if not self.entries and ws.sources.is_dir():  # not synced yet: fall back to the files themselves
            self.entries = {p.relative_to(ws.sources).as_posix(): {} for p in ws.sources.rglob("*") if p.is_file()}
        self.by_hash = {e["hash"][:8]: p for p, e in self.entries.items() if e.get("hash")}
        names: dict[str, list[str]] = {}
        for p in self.entries:
            names.setdefault(PurePosixPath(p).name.lower(), []).append(p)
        self.by_name = {n: ps[0] for n, ps in names.items() if len(ps) == 1}

    def find(self, source: str | None, cid: str | None = None) -> str | None:
        if cid and (m := re.fullmatch(r"([0-9a-f]{8})[0-9a-f]*(?::\d+)?", cid)) and m.group(1) in self.by_hash:
            return self.by_hash[m.group(1)]
        if not source:
            return None
        rel = source.strip().removeprefix("sources/")
        if rel in self.entries:
            return rel
        return self.by_name.get(PurePosixPath(rel).name.lower())


def links(ws: Workspace, data: dict) -> dict:
    res = Resolver(ws)
    out = {}
    for it in data.get("items") or []:
        for c in (it.get("citations") or []) if isinstance(it, dict) else []:
            key = cite_key(c)
            if isinstance(c, str):
                (src, loc), cid = _split_string(c), None
            elif isinstance(c, dict):
                src, cid = c.get("source"), c.get("cid")
                loc = parse_location(str(c.get("location") or ""))
                if not loc and isinstance(src, str):  # "hw2/BST.java:340-375" as the source
                    src, loc = _split_string(src)
            else:
                continue
            if not key or key in out:
                continue
            path = res.find(src, cid)
            if path:
                out[key] = {"path": path, "type": extracting.source_type(path), **loc}
    return out


# --- served viewer ------------------------------------------------------------------------

_CSS = """body{margin:0;font:15px/1.55 system-ui,sans-serif;background:#fff;color:#111}
header{position:sticky;top:0;padding:10px 16px;background:#f4f4f2;border-bottom:1px solid #ddd;font-weight:600}
header small{font-weight:400;color:#666;margin-left:8px}
pre{margin:0;padding:8px 0;font:13px/1.5 ui-monospace,Menlo,monospace;white-space:pre-wrap;overflow-wrap:anywhere}
.ln{display:block;padding:0 16px 0 0;scroll-margin-top:30vh}
.ln::before{content:attr(data-n);display:inline-block;width:4.5em;padding-right:1em;text-align:right;color:#999;user-select:none}
.hit{background:#fff3b0}
section{padding:4px 16px 16px;border-bottom:1px solid #eee;scroll-margin-top:48px;white-space:pre-wrap;overflow-wrap:anywhere}
section h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;color:#666}
section:target{background:#fffbe0}
@media(prefers-color-scheme:dark){body{background:#151515;color:#e8e8e8}header{background:#202020;border-color:#333}
.hit{background:#4a4210}section:target{background:#2c2810}section{border-color:#2a2a2a}}"""


def viewer(ws: Workspace, rel: str, lines: tuple[int, int] | None = None) -> str | None:
    """Escaped HTML view of a source: numbered lines for text/code (cited range highlighted, anchors #L<n>),
    the extracted text split by page/slide (anchors #page-<n>, #slide-<n>) for the rest. None if unreadable."""
    path = ws.sources / rel
    kind = extracting.source_type(rel)
    head = f"<header>{html.escape(rel)}<small>{html.escape(kind)}</small></header>"
    if kind in ("pdf", "docx", "pptx", "html"):
        e = mf.load(ws)["sources"].get(rel) or {}
        cache = ws.text_dir / f"{e.get('hash', '')}.md"
        if not e.get("hash") or not cache.is_file():
            return None
        parts = re.split(r"<!--\s*(page|slide)\s+(\d+)\s*-->", cache.read_text(errors="replace"))
        body = [f"<section><pre>{html.escape(parts[0].strip())}</pre></section>"] if parts[0].strip() else []
        for i in range(1, len(parts) - 2, 3):
            what, n, text = parts[i], parts[i + 1], parts[i + 2]
            body.append(f'<section id="{what}-{n}"><h2>{what} {n}</h2>{html.escape(text.strip())}</section>')
        main = "".join(body)
    else:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            return None
        lo, hi = lines or (0, -1)
        main = "<pre>" + "".join(
            f'<span class="ln{" hit" if lo <= n <= hi else ""}" id="L{n}" data-n="{n}">{html.escape(line) or " "}</span>'
            for n, line in enumerate(text.splitlines(), start=1)) + "</pre>"
    return (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(PurePosixPath(rel).name)}</title><style>{_CSS}</style>{head}{main}")
