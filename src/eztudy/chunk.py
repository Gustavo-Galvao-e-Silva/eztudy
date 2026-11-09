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


# --- code: symbol-aware chunks with exact line ranges -----------------------------

CODE_CHUNKER_VERSION = "1"  # bump to re-chunk code sources in existing indexes

_NOT_A_NAME = {
    "if", "for", "while", "switch", "catch", "return", "new", "else", "do", "try", "synchronized",
    "sizeof", "elif", "with", "throw", "case", "foreach", "using", "lock", "until", "unless", "assert",
}
_HASH_COMMENT_EXTS = {".py", ".rb", ".sh", ".r", ".jl", ".ex", ".exs"}
_PY_LIKE = {".py", ".rb"}
_CLASS_RE = re.compile(
    r"^(\s*)(?:(?:export|default|public|private|protected|internal|static|final|abstract|sealed|open|data|"
    r"partial|pub(?:\([^)]*\))?|unsafe)\s+)*(class|interface|enum|record|struct|trait|impl|object|protocol|module)\s+(\w+)"
)
_PY_RE = re.compile(r"^(\s*)(?:async\s+)?(def|class)\s+(\w+)")
_FUNC_RES = [
    re.compile(r"^(\s*)(?:export\s+)?(?:default\s+)?(?:async\s+)?function\*?\s+(\w+)"),             # JS/TS
    re.compile(r"^(\s*)(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function\b|\([^)]*\)\s*=>|\w+\s*=>)"),
    re.compile(r"^(\s*)func\s+(?:\([^)]*\)\s*)?(\w+)"),                                             # Go/Swift
    re.compile(r"^(\s*)(?:pub(?:\([^)]*\))?\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(\w+)"),  # Rust
    re.compile(r"^(\s*)(?:(?:public|private|protected|internal|override|open|suspend|inline)\s+)*fun\s+(?:<[^>]*>\s*)?(?:\w+\.)?(\w+)"),  # Kotlin
    re.compile(r"^(\s*)def\s+(?:self\.)?(\w+[?!]?)"),                                                # Ruby
    # C/C++/Java/C#: `<modifiers/return type> name(` on a line that doesn't end a statement.
    re.compile(r"^(\s*)(?:[\w$<>\[\],.?*&:~]+(?:\s+|\s*[*&]\s*))+(?:[\w$<>]+::)*([\w$~]+)\s*\([^;=]*$"),
    re.compile(r"^(\s*)(?:(?:async|static|get|set)\s+)*(\w+)\s*\([^)]*\)\s*\{\s*$"),                # JS class method
]


@dataclass
class Symbol:
    name: str
    kind: str  # "class" | "function"
    heading: str  # "Outer > name"
    start: int  # 1-based, including leading comments/annotations
    line: int  # the signature line
    end: int
    indent: int


def _leading_start(lines: list[str], i: int, ext: str) -> int:
    """Index of the first comment/annotation/decorator line directly above line i (0-based)."""
    prefixes = ("//", "/*", "*", "*/", "@", "///", "#[", "template") + (("#",) if ext in _HASH_COMMENT_EXTS else ())
    j = i
    while j > 0 and lines[j - 1].strip().startswith(prefixes):
        j -= 1
    return j


def _match(line: str, ext: str) -> tuple[int, str, str] | None:
    if ext in _PY_LIKE:
        m = _PY_RE.match(line)
        if m:
            return len(m.group(1).expandtabs()), "class" if m.group(2) == "class" else "function", m.group(3)
        if ext == ".py":
            return None
    m = _CLASS_RE.match(line)
    if m and not line.rstrip().endswith(";"):
        return len(m.group(1).expandtabs()), "class", m.group(3)
    for rx in _FUNC_RES:
        m = rx.match(line)
        if not m:
            continue
        name = m.group(2)
        words = re.findall(r"[\w$]+", line[: m.start(2)])
        if name in _NOT_A_NAME or any(w in _NOT_A_NAME for w in words) or line.lstrip().startswith(("//", "*", "#", "/*")):
            return None
        return len(m.group(1).expandtabs()), "function", name
    return None


def code_symbols(text: str, ext: str) -> list[Symbol]:
    """Classes and functions/methods (not ones nested inside functions), with 1-based line ranges."""
    lines = text.splitlines()
    ext = ext.lower()
    found: list[Symbol] = []
    stack: list[Symbol] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        m = _match(line, ext)
        if not m:
            continue
        indent, kind, name = m
        while stack and stack[-1].indent >= indent:
            stack.pop()
        if any(s.kind == "function" for s in stack):
            continue  # nested helper: part of its parent's chunk
        heading = " > ".join([s.name for s in stack] + [name])
        sym = Symbol(name, kind, heading, _leading_start(lines, i, ext) + 1, i + 1, len(lines), indent)
        found.append(sym)
        stack.append(sym)
    for k, sym in enumerate(found):  # a symbol ends before the next one at the same or outer level
        nxt = next((s for s in found[k + 1:] if s.indent <= sym.indent), None)
        end = (nxt.start - 1) if nxt else len(lines)
        while end > sym.line and not lines[end - 1].strip():
            end -= 1
        sym.end = end
    return found


def _pack_lines(lines: list[str], start: int, end: int, max_chars: int, overlap_chars: int) -> list[tuple[int, int]]:
    """Split lines[start..end] (1-based, inclusive) into windows <= max_chars, preferring blank-line breaks."""
    out, lo = [], start
    while lo <= end:
        size, hi, last_blank = 0, lo, None
        while hi <= end and (size + len(lines[hi - 1]) + 1 <= max_chars or hi == lo):
            size += len(lines[hi - 1]) + 1
            if not lines[hi - 1].strip():
                last_blank = hi
            hi += 1
        if hi <= end and last_blank and last_blank > lo + (hi - lo) // 2:
            hi = last_blank + 1
        if hi <= end and sum(len(lines[i - 1]) + 1 for i in range(hi, end + 1)) <= max_chars // 8:
            hi = end + 1  # don't leave a tiny tail (e.g. a lone closing brace) as its own chunk
        out.append((lo, hi - 1))
        if hi > end:
            break
        back, b = 0, hi
        while b - 1 > lo + (hi - lo) // 2 and back + len(lines[b - 2]) + 1 <= overlap_chars:
            back += len(lines[b - 2]) + 1
            b -= 1
        lo = b
    return out


def chunk_code(text: str, ext: str, tokens: int = 400, overlap: int = 60) -> list[Chunk]:
    """One chunk per class preamble / method / function, with exact line ranges; small ones are merged."""
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        return []
    max_chars, overlap_chars = tokens * CHARS_PER_TOKEN, overlap * CHARS_PER_TOKEN
    syms = code_symbols(text, ext)
    # Segments run from one symbol's start to the next symbol's start (of any level).
    starts = [(1, "")] + [(s.start, s.heading) for s in syms]
    segs = []
    for k, (lo, heading) in enumerate(starts):
        hi = starts[k + 1][0] - 1 if k + 1 < len(starts) else len(lines)
        while hi >= lo and not lines[hi - 1].strip():
            hi -= 1
        while lo <= hi and not lines[lo - 1].strip():
            lo += 1
        if lo <= hi:
            segs.append([lo, hi, [heading] if heading else []])

    def size(lo, hi):
        return sum(len(lines[i - 1]) + 1 for i in range(lo, hi + 1))

    merged: list[list] = []
    for seg in segs:  # merge runs of small segments (getters, constants) up to a quarter chunk
        if merged and size(merged[-1][0], seg[1]) <= max_chars // 4 + max_chars // 8:
            merged[-1][1] = seg[1]
            merged[-1][2] += seg[2]
        else:
            merged.append(seg)

    chunks: list[Chunk] = []
    for lo, hi, headings in merged:
        names = list(dict.fromkeys(headings))
        if len(names) > 1:
            parent = names[0].rpartition(" > ")[0]
            heading = (parent + " > " if parent else "") + ", ".join(n.rpartition(" > ")[2] for n in names)
        else:
            heading = names[0] if names else ""
        for a, b in _pack_lines(lines, lo, hi, max_chars, overlap_chars):
            chunks.append(Chunk(len(chunks), "\n".join(lines[a - 1:b]), heading, "line", a, b))
    return chunks
