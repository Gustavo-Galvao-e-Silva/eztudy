import json

from eztudy import chunk, extract, manifest as mf, vectordb, wiki
from eztudy.cli import build_parser, cmd_index, cmd_search, main, sync_sources
from eztudy.render import render, validate
from eztudy.workspace import find_workspace


def args(*argv):
    return build_parser().parse_args(list(argv))


def test_extract_formats(notebook):
    src = notebook / "sources"
    title, text = extract.extract(src / "bio" / "cells.pdf")
    assert title == "Cell Biology Notes"
    assert "<!-- page 2 -->" in text and "Ribosomes" in text
    title, text = extract.extract(src / "bio" / "plants.docx")
    assert "## Photosynthesis" in text and "### Calvin Cycle" in text and "| Light reactions | Thylakoid |" in text
    title, text = extract.extract(src / "genetics.pptx")
    assert title == "Genetics Intro"
    assert "<!-- slide 2 -->" in text and "Speaker notes: Notes about Mendel" in text
    title, _ = extract.extract(src / "history.md")
    assert title == "French Revolution"


def test_pdf_url_title_falls_back_to_heading(tmp_path):
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 80), "Week 06 Notes", fontsize=24)
    page.insert_text((50, 120), "Heaps are complete binary trees.", fontsize=11)
    page.insert_text((50, 140), "The min-heap property holds at every node.", fontsize=11)
    doc.set_metadata({"title": "https:/example.com/course-notes/week-06"})
    doc.save(tmp_path / "web.pdf")
    assert extract.extract(tmp_path / "web.pdf")[0] == "Week 06 Notes"

    # No prominent heading -> file stem, never the URL.
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 80), "just body text", fontsize=11)
    doc.set_metadata({"title": "https://example.com/x"})
    doc.save(tmp_path / "plain-notes.pdf")
    assert extract.extract(tmp_path / "plain-notes.pdf")[0] == "plain-notes"


def test_sync_tracks_moves_and_deletes(notebook):
    ws = find_workspace(notebook)
    log = sync_sources(ws, quiet=True)
    assert len(log["extracted"]) == 4
    assert [u["path"] for u in log["unsupported"]] == ["image.bin"]

    (notebook / "sources" / "history").mkdir()
    (notebook / "sources" / "history.md").rename(notebook / "sources" / "history" / "france.md")
    (notebook / "sources" / "genetics.pptx").unlink()
    diff = mf.scan(ws, mf.load(ws))
    assert diff.moved == [("history.md", "history/france.md")] and diff.deleted == ["genetics.pptx"]

    log = sync_sources(ws, quiet=True)
    assert log["extracted"] == []  # move = no re-extraction
    entries = mf.load(ws)["sources"]
    assert "history/france.md" in entries and "genetics.pptx" not in entries
    assert len(list(ws.text_dir.glob("*.md"))) == 3


def test_chunk_keeps_locations_and_headings():
    md = "# A\n\n<!-- page 1 -->\n" + ("alpha " * 300) + "\n\n<!-- page 2 -->\n## B\n\n" + ("beta " * 300)
    chunks = chunk.chunk_markdown(md, tokens=200, overlap=20)
    assert len(chunks) >= 3
    assert chunks[0].loc_start == 1 and chunks[-1].loc_end == 2
    assert chunks[-1].heading == "A > B"
    assert all(len(c.text) <= 200 * 4 + 50 for c in chunks)


def test_index_search_and_move(notebook, fake_embedder, capsys):
    ws = find_workspace(notebook)
    cmd_index(ws, args("index"), embedder=fake_embedder)
    db = vectordb.connect(ws.db_path)
    assert vectordb.stats(db)["documents"] == 4

    hits = vectordb.search(db, "mitochondria ATP", fake_embedder.embed_query("mitochondria ATP"), k=3)
    assert hits[0].path == "bio/cells.pdf" and hits[0].location == "pages 1-2"
    assert vectordb.search(db, "Bastille", None, mode="fts")[0].path == "history.md"

    # Moving a file updates its path without re-embedding.
    (notebook / "sources" / "history.md").rename(notebook / "sources" / "france.md")
    capsys.readouterr()
    cmd_index(ws, args("index"), embedder=fake_embedder)
    assert "+0 docs" in capsys.readouterr().out
    assert vectordb.search(db, "Bastille", None, mode="fts")[0].path == "france.md"

    cmd_search(ws, args("search", "Calvin cycle RuBisCO", "--json"), embedder=fake_embedder)
    out = json.loads(capsys.readouterr().out)
    assert out[0]["path"] == "bio/plants.docx" and out[0]["heading"].endswith("Calvin Cycle")
    assert out[0]["type"] == "docx" and "title" in out[0]
    assert {"cid", "path", "title", "type", "heading", "location", "score", "text", "citation"} <= out[0].keys()
    assert main(["-C", str(notebook), "show", out[0]["cid"]]) == 0


def test_wiki_lint(notebook):
    ws = find_workspace(notebook)
    sync_sources(ws, quiet=True)
    main(["-C", str(notebook), "wiki", "init"])
    h = mf.load(ws)["sources"]["history.md"]["hash"][:8]
    (ws.wiki / "topics" / "revolution.md").write_text(
        f"---\ntitle: French Revolution\ntype: topic\nsources:\n  - path: history.md\n    hash: {h}\n---\n# French Revolution\nSee [[Napoleon]] and [[Missing Page]].\n")
    (ws.wiki / "entities" / "napoleon.md").write_text("---\ntitle: Napoleon\ntype: entity\nsources: [sources/genetics.pptx]\n---\nBack to [[French Revolution]].\n")
    (ws.wiki / "index.md").write_text((ws.wiki / "index.md").read_text() + "\n- [[revolution]] — the revolution\n")
    r = wiki.lint(ws, mf.load(ws))
    assert r["broken_links"] == [{"page": "topics/revolution", "link": "Missing Page"}]
    assert r["missing_from_index"] == ["entities/napoleon"]
    assert r["orphans"] == []
    assert "bio/cells.pdf" in r["uncovered_sources"]

    (notebook / "sources" / "history.md").write_text("# Changed\n")
    sync_sources(ws, quiet=True)
    r = wiki.lint(ws, mf.load(ws))
    assert r["stale_citations"] == [{"page": "topics/revolution", "source": "history.md"}]


def test_render_quiz_and_flashcards(tmp_path):
    quiz = {"type": "quiz", "title": "Bio Quiz", "items": [
        {"type": "mcq", "question": "Powerhouse?", "options": ["Nucleus", "Mitochondria"], "answer": 1, "explanation": "ATP", "citations": [{"source": "bio/cells.pdf", "location": "page 1"}]},
        {"type": "true_false", "question": "DNA is a helix", "answer": True, "citations": ["genetics.pptx slide 1"]},
        {"type": "short", "question": "Who rose in 1799?", "answer": "Napoleon", "citations": ["history.md"]},
        {"type": "short", "question": "Write remove()", "answer": "T remove() {\n    if (size == 0) throw x;\n}", "citations": ["h.java"]},
    ]}
    p = tmp_path / "quiz.json"
    p.write_text(json.dumps(quiz))
    md, html, _ = render(p)
    assert "## Answer key" in md.read_text() and "1. **B**" in md.read_text()
    assert "   ```\n   T remove() {\n       if (size == 0) throw x;\n   }\n   ```" in md.read_text()
    page = html.read_text()
    assert "Powerhouse?" in page and "/*__EZTUDY_DATA__*/" not in page

    bad = {"type": "quiz", "title": "x", "items": [{"type": "mcq", "question": "q", "options": ["a"], "answer": 3}]}
    errs = validate(bad)
    assert any("citations" in e for e in errs) and any("options" in e for e in errs)

    cards = {"type": "flashcards", "title": "Cards", "items": [{"front": "ATP?", "back": "Energy | currency", "citations": ["x"]}]}
    p = tmp_path / "cards.json"
    p.write_text(json.dumps(cards))
    md, _, _ = render(p)
    assert "Energy \\| currency" in md.read_text()


def test_render_warns_on_unknown_cids(notebook, fake_embedder, capsys):
    ws = find_workspace(notebook)
    cmd_index(ws, args("index"), embedder=fake_embedder)
    cid = vectordb.connect(ws.db_path).execute("SELECT cid FROM chunks LIMIT 1").fetchone()[0]
    quiz = {"type": "quiz", "title": "Q", "items": [
        {"type": "true_false", "question": "ok", "answer": True, "citations": [{"cid": cid}]},
        {"id": "typo", "type": "true_false", "question": "bad", "answer": True, "citations": [{"cid": "deadbeef:99"}]},
    ]}
    p = notebook / "q.json"
    p.write_text(json.dumps(quiz))
    capsys.readouterr()
    assert main(["-C", str(notebook), "render", str(p)]) == 0
    err = capsys.readouterr().err
    assert "item 2 (typo): unknown chunk id 'deadbeef:99'" in err and cid not in err
    assert main(["-C", str(notebook), "render", str(p), "--strict"]) == 1


def test_title_overrides(notebook, fake_embedder, capsys):
    ws = find_workspace(notebook)
    cmd_index(ws, args("index"), embedder=fake_embedder)
    h = mf.load(ws)["sources"]["genetics.pptx"]["hash"][:8]
    ws.config_path.write_text(f'[titles]\n"history.md" = "Revolution notes"\n"{h}" = "Mendel deck"\n')
    ws = find_workspace(notebook)
    cmd_index(ws, args("index"), embedder=fake_embedder)
    capsys.readouterr()
    main(["-C", str(notebook), "sources", "--json"])
    rows = {r["path"]: r for r in json.loads(capsys.readouterr().out)}
    assert rows["history.md"]["title"] == "Revolution notes" and rows["history.md"]["title_override"]
    assert rows["genetics.pptx"]["title"] == "Mendel deck"
    assert rows["bio/cells.pdf"]["title"] == "Cell Biology Notes" and not rows["bio/cells.pdf"]["title_override"]
    db = vectordb.connect(ws.db_path)
    assert vectordb.search(db, "Bastille", None, mode="fts")[0].title == "Revolution notes"

    # The hash key follows the file across a move; removing overrides restores extracted titles.
    (notebook / "sources" / "genetics.pptx").rename(notebook / "sources" / "mendel.pptx")
    sync_sources(ws, quiet=True)
    assert mf.load(ws)["sources"]["mendel.pptx"]["title"] == "Mendel deck"
    ws.config_path.unlink()
    ws = find_workspace(notebook)
    cmd_index(ws, args("index"), embedder=fake_embedder)
    assert mf.load(ws)["sources"]["history.md"]["title"] == "French Revolution"
    assert vectordb.search(db, "Bastille", None, mode="fts")[0].title == "French Revolution"
