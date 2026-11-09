"""Heading/paragraph-aware chunking that preserves page/slide locations."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .extract import MARKER_RE

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
CHARS_PER_TOKEN = 4


@dataclass
class Chunk:
    ord: int
    text: str
    heading: str  # "H1 > H2 > H3"
    loc_kind: str | None  # "page" | "slide" | None
    loc_start: int | None
    loc_end: int | None

    @property
    def location(self) -> str:
        if self.loc_kind is None:
            return ""
        if self.loc_start == self.loc_end:
            return f"{self.loc_kind} {self.loc_start}"
        return f"{self.loc_kind}s {self.loc_start}-{self.loc_end}"


@dataclass
class _Block:
    text: str
    heading: str
    loc_kind: str | None
    loc: int | None


def _blocks(markdown: str) -> list[_Block]:
    blocks: list[_Block] = []
    stack: list[tuple[int, str]] = []
    loc_kind: str | None = None
    loc: int | None = None
    in_fence = False
    buf: list[str] = []

    def flush():
        text = "\n".join(buf).strip()
        buf.clear()
        if text:
            blocks.append(_Block(text, " > ".join(h for _, h in stack), loc_kind, loc))

    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            buf.append(line)
            continue
        if not in_fence:
            m = MARKER_RE.fullmatch(line.strip())
            if m:
                flush()
                loc_kind, loc = m.group(1), int(m.group(2))
                continue
            h = HEADING_RE.match(line)
            if h:
                flush()
                level = len(h.group(1))
                stack[:] = [(lv, t) for lv, t in stack if lv < level]
                stack.append((level, h.group(2)))
                buf.append(line)
                continue
            if not line.strip():
                flush()
                continue
        buf.append(line)
    flush()
    return blocks


def _split_long(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+|\n", text)
    out, cur = [], ""
    for s in sentences:
        while len(s) > max_chars:  # pathological: no sentence breaks
            if cur:
                out.append(cur)
                cur = ""
            out.append(s[:max_chars])
            s = s[max_chars:]
        if len(cur) + len(s) + 1 > max_chars and cur:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip() if cur else s
    if cur:
        out.append(cur)
    return out


def chunk_markdown(markdown: str, tokens: int = 400, overlap: int = 60) -> list[Chunk]:
    max_chars = tokens * CHARS_PER_TOKEN
    overlap_chars = overlap * CHARS_PER_TOKEN
    pieces: list[_Block] = []
    for b in _blocks(markdown):
        for part in _split_long(b.text, max_chars):
            pieces.append(_Block(part, b.heading, b.loc_kind, b.loc))

    chunks: list[Chunk] = []
    cur: list[_Block] = []

    def emit():
        if not cur:
            return
        locs = [b.loc for b in cur if b.loc is not None]
        kind = next((b.loc_kind for b in cur if b.loc_kind), None)
        chunks.append(
            Chunk(
                ord=len(chunks),
                text="\n\n".join(b.text for b in cur),
                heading=cur[-1].heading or cur[0].heading,
                loc_kind=kind,
                loc_start=min(locs) if locs else None,
                loc_end=max(locs) if locs else None,
            )
        )

    size = 0
    for p in pieces:
        # A new top-level section starts a fresh chunk if the current one is reasonably full.
        section_break = cur and p.heading.split(" > ")[0] != cur[-1].heading.split(" > ")[0] and size > max_chars // 3
        only_headings = all(HEADING_RE.match(b.text) for b in cur)
        if cur and not only_headings and (size + len(p.text) > max_chars or section_break):
            emit()
            # carry overlap from the tail of the previous chunk
            tail: list[_Block] = []
            tsize = 0
            for b in reversed(cur):
                if tsize + len(b.text) > overlap_chars or section_break:
                    break
                tail.insert(0, b)
                tsize += len(b.text)
            if tsize + len(p.text) > max_chars:
                tail, tsize = [], 0
            cur, size = tail, tsize
        cur.append(p)
        size += len(p.text)
    emit()
    return chunks
