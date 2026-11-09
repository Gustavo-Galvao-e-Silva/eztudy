import hashlib
import math
import re
from pathlib import Path

import pytest


class FakeEmbedder:
    """Deterministic bag-of-words hashing embedder (no model download)."""

    model_name = "fake-hash-64"
    dim = 64

    def _vec(self, text):
        v = [0.0] * self.dim
        for w in re.findall(r"\w+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1
        n = math.sqrt(sum(x * x for x in v)) or 1
        return [x / n for x in v]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


def make_pdf(path: Path, pages: list[str]) -> None:
    import pymupdf

    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text)
    doc.set_metadata({"title": "Cell Biology Notes"})
    doc.save(path)


def make_docx(path: Path) -> None:
    import docx

    d = docx.Document()
    d.add_heading("Photosynthesis", level=1)
    d.add_paragraph("Chlorophyll absorbs light in the thylakoid membranes of the chloroplast.")
    d.add_heading("Calvin Cycle", level=2)
    d.add_paragraph("The Calvin cycle fixes carbon dioxide using the enzyme RuBisCO.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Stage", "Location"
    t.cell(1, 0).text, t.cell(1, 1).text = "Light reactions", "Thylakoid"
    d.save(path)


def make_pptx(path: Path) -> None:
    from pptx import Presentation

    prs = Presentation()
    for title, body in [("Genetics Intro", "DNA is a double helix"), ("Mendel", "Pea plants showed dominant and recessive traits")]:
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = title
        s.placeholders[1].text = body
        s.notes_slide.notes_text_frame.text = f"Notes about {title}"
    prs.save(path)


@pytest.fixture
def notebook(tmp_path):
    src = tmp_path / "sources"
    (src / "bio").mkdir(parents=True)
    make_pdf(src / "bio" / "cells.pdf", [
        "Mitochondria are the powerhouse of the cell. They produce ATP via oxidative phosphorylation.",
        "The nucleus stores genetic material. Ribosomes synthesize proteins from mRNA.",
    ])
    make_docx(src / "bio" / "plants.docx")
    make_pptx(src / "genetics.pptx")
    (src / "history.md").write_text("# French Revolution\n\nThe storming of the Bastille happened in 1789.\n\n## Aftermath\n\nNapoleon rose to power in 1799.\n")
    (src / "image.bin").write_bytes(b"\x00\x01\x02" * 50)
    return tmp_path
