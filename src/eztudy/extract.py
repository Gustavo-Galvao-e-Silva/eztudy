"""Turn source files into normalized markdown.

Location markers are embedded as HTML comments so chunks can cite them:
  <!-- page N -->   (PDF)
  <!-- slide N -->  (PPTX)
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

TEXT_EXTS = {
    ".md", ".markdown", ".mdx", ".txt", ".text", ".rst", ".org", ".adoc", ".tex",
    ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".ini", ".xml",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".go", ".rs", ".rb", ".c",
    ".h", ".cpp", ".hpp", ".cs", ".swift", ".php", ".sh", ".sql", ".r", ".m", ".scala",
    ".lua", ".hs", ".ex", ".exs", ".clj", ".jl", ".ipynb",
}
HTML_EXTS = {".html", ".htm"}
MARKER_RE = re.compile(r"<!--\s*(page|slide)\s+(\d+)\s*-->")


class UnsupportedSource(Exception):
    pass


def supported(path: Path) -> bool:
    ext = path.suffix.lower()
    return ext in TEXT_EXTS | HTML_EXTS | {".pdf", ".docx", ".pptx"} or _looks_textual(path)


def extract(path: Path) -> tuple[str, str]:
    """Return (title, markdown)."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        title, body = _pdf(path)
    elif ext == ".docx":
        title, body = _docx(path)
    elif ext == ".pptx":
        title, body = _pptx(path)
    elif ext in HTML_EXTS:
        title, body = _html(path)
    elif ext in TEXT_EXTS or _looks_textual(path):
        title, body = _text(path)
    else:
        raise UnsupportedSource(f"unsupported file type: {ext or path.name}")
    body = _normalize(body)
    if not body.strip():
        raise UnsupportedSource("no extractable text (scanned PDF or empty file?)")
    return (title or path.stem).strip(), body


# --- formats -----------------------------------------------------------------


def _pdf(path: Path) -> tuple[str, str]:
    import pymupdf

    parts = []
    with pymupdf.open(path) as doc:
        title = (doc.metadata or {}).get("title") or ""
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text", sort=True)
            parts.append(f"<!-- page {i} -->\n{text.strip()}\n")
    return title, "\n".join(parts)


def _docx(path: Path) -> tuple[str, str]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    title = d.core_properties.title or ""
    out: list[str] = []
    for block in d.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(block, d)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            if style == "title":
                title = title or text
                out.append(f"# {text}")
            elif style.startswith("heading"):
                level = re.sub(r"\D", "", style) or "1"
                out.append(f"{'#' * min(int(level) + 1, 6)} {text}")
            elif "list" in style:
                out.append(f"- {text}")
            else:
                out.append(text)
        elif tag == "tbl":
            out.append(_table_md([[c.text.strip() for c in r.cells] for r in Table(block, d).rows]))
    return title, "\n\n".join(out)


def _pptx(path: Path) -> tuple[str, str]:
    from pptx import Presentation

    prs = Presentation(str(path))
    title = prs.core_properties.title or ""
    out: list[str] = []
    for i, slide in enumerate(prs.slides, start=1):
        out.append(f"<!-- slide {i} -->")
        slide_title = slide.shapes.title.text_frame.text.strip() if slide.shapes.title is not None and slide.shapes.title.has_text_frame else ""
        out.append(f"## Slide {i}" + (f": {slide_title}" if slide_title else ""))
        for shape in slide.shapes:
            if shape == slide.shapes.title:
                continue
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = "".join(r.text for r in para.runs).strip()
                    if text:
                        out.append("  " * para.level + f"- {text}")
            elif getattr(shape, "has_table", False) and shape.has_table:
                out.append(_table_md([[c.text.strip() for c in r.cells] for r in shape.table.rows]))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                out.append(f"\n> Speaker notes: {notes}")
        out.append("")
        if not title and slide_title and i == 1:
            title = slide_title
    return title, "\n".join(out)


class _HTMLText(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCK = {"p", "div", "br", "li", "tr", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.out.append("#" * int(tag[1]) + " ")
        if tag == "li":
            self.out.append("- ")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)


def _html(path: Path) -> tuple[str, str]:
    p = _HTMLText()
    p.feed(path.read_text(errors="replace"))
    return p.title.strip(), "".join(p.out)


def _text(path: Path) -> tuple[str, str]:
    text = path.read_text(errors="replace")
    title = ""
    if path.suffix.lower() in {".md", ".markdown", ".mdx"}:
        m = re.search(r"^#\s+(.+)$", text, re.M)
        title = m.group(1) if m else ""
    elif path.suffix.lower() not in {".txt", ".text", ".rst", ".org"}:
        text = f"```{path.suffix.lstrip('.')}\n{text}\n```"
    return title, text


# --- helpers -----------------------------------------------------------------


def _table_md(rows: list[list[str]]) -> str:
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [[c.replace("\n", " ").replace("|", "\\|") for c in r] + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _looks_textual(path: Path) -> bool:
    try:
        if path.stat().st_size > 5_000_000:
            return False
        head = path.open("rb").read(4096)
    except OSError:
        return False
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False
