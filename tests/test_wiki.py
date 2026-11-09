import datetime as dt

import yaml

from eztudy import manifest as mf, wiki
from eztudy.cli import main, sync_sources
from eztudy.workspace import find_workspace


def _setup(notebook):
    ws = find_workspace(notebook)
    sync_sources(ws, quiet=True)
    main(["-C", str(notebook), "wiki", "init"])
    return ws, {rel: e["hash"][:8] for rel, e in mf.load(ws)["sources"].items()}


def test_body_citations_must_be_in_frontmatter(notebook):
    ws, h = _setup(notebook)
    body = (f"# Cells\nMitochondria make ATP (cells.pdf, page 1). Light reactions [{h['bio/plants.docx']}:0].\n"
            "Not a cite: `history.md` in code, and [[genetics.pptx]] is a link.\n")
    (ws.wiki / "topics" / "cells.md").write_text(f"---\ntitle: Cells\ntype: topic\nsources:\n  - path: genetics.pptx\n---\n{body}")
    r = wiki.lint(ws, mf.load(ws))
    assert r["body_not_in_frontmatter"] == [
        {"page": "topics/cells", "source": "bio/cells.pdf"},
        {"page": "topics/cells", "source": "bio/plants.docx"},
    ]
    assert r["frontmatter_not_in_body"] == [{"page": "topics/cells", "source": "genetics.pptx"}]
    assert not wiki.lint_ok(r)


def test_lint_fix(notebook, capsys):
    ws, h = _setup(notebook)
    body = "# Cells\n\nATP (bio/cells.pdf, page 1).\n\nRevolution: history.md\n"
    page = ws.wiki / "topics" / "cells.md"
    page.write_text(
        "---\ntitle: Cells\ntype: topic\nsources:\n"
        f"  - path: old/plants.docx\n    hash: {h['bio/plants.docx']}\n"   # moved file, found by hash
        "  - genetics.pptx\n"                                              # missing hash
        "  - path: history.md\n    hash: deadbeef\n"                      # stale: must stay as-is
        "updated: 2026-01-01\n---\n" + body)
    fixed = wiki.fix(ws, mf.load(ws), today=dt.date(2026, 11, 9))
    assert fixed[0]["page"] == "topics/cells" and len(fixed[0]["changes"]) == 3
    meta, new_body = wiki.split_frontmatter(page.read_text())
    assert new_body == body
    assert meta["updated"] == dt.date(2026, 11, 9)
    assert meta["sources"] == [
        {"path": "bio/plants.docx", "hash": h["bio/plants.docx"]},
        {"path": "genetics.pptx", "hash": h["genetics.pptx"]},
        {"path": "history.md", "hash": "deadbeef"},
        {"path": "bio/cells.pdf", "hash": h["bio/cells.pdf"]},
    ]
    r = wiki.lint(ws, mf.load(ws))
    assert r["stale_citations"] == [{"page": "topics/cells", "source": "history.md"}]
    assert r["body_not_in_frontmatter"] == [] and r["unknown_sources"] == []
    assert wiki.fix(ws, mf.load(ws)) == []  # idempotent

    capsys.readouterr()
    assert main(["-C", str(notebook), "wiki", "cite", "plants", f"{h['history.md']}:3", "genetics.pptx"]) == 0
    block = yaml.safe_load(capsys.readouterr().out)
    assert block["sources"] == [
        {"path": "bio/plants.docx", "hash": h["bio/plants.docx"]},
        {"path": "history.md", "hash": h["history.md"]},
        {"path": "genetics.pptx", "hash": h["genetics.pptx"]},
    ]
    assert main(["-C", str(notebook), "wiki", "cite", "nope"]) == 1
