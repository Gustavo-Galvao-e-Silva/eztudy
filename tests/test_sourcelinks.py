import json
import threading
import urllib.error
import urllib.request

import pytest

from conftest import make_pdf
from eztudy import serve, sourcelinks
from eztudy.cli import main
from eztudy.workspace import find_workspace


def test_parse_location():
    assert sourcelinks.parse_location("page 4") == {"page": 4}
    assert sourcelinks.parse_location("pages 1–2") == {"page": 1}
    assert sourcelinks.parse_location("p.7") == {"page": 7}
    assert sourcelinks.parse_location("slide 3") == {"slide": 3}
    assert sourcelinks.parse_location("lines 340-375") == {"line": 340, "end": 375}
    assert sourcelinks.parse_location("") == {}


@pytest.fixture
def nb(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    src = tmp_path / "sources"
    (src / "exams").mkdir(parents=True)
    make_pdf(src / "exams" / "prac1.pdf", ["Heaps intro", "Heap removal steps"])
    (src / "hw2").mkdir()
    (src / "hw2" / "BST.java").write_text("".join(f"// line {n} <b>\n" for n in range(1, 21)))
    assert main(["-C", str(tmp_path), "sync"]) == 0
    return tmp_path


def deck(citations):
    return {"type": "quiz", "id": "d", "title": "D", "items": [
        {"id": "q1", "type": "mcq", "question": "?", "options": ["a", "b"], "answer": 0, "citations": citations}]}


def test_links_resolve_by_hash_path_and_name(nb):
    ws = find_workspace(nb)
    h = next(e["hash"] for p, e in json.loads((ws.state / "manifest.json").read_text())["sources"].items() if p.endswith(".pdf"))
    m = sourcelinks.links(ws, deck([
        {"cid": f"{h[:8]}:3", "source": "old/place.pdf", "location": "page 2"},  # moved: found by chunk hash
        {"source": "prac1.pdf", "location": "pages 1-2"},                          # bare file name, as in the screenshot
        "hw2/BST.java:5-7 (insert)",
        "BST.java (lines 9-10)",
        {"source": "missing.pdf", "location": "page 1"},
        {"source": "prac1.pdf", "location": "page 2"},  # same file, another place: its own entry
    ]))
    assert m["prac1.pdf#page 2"]["page"] == 2
    assert m[f"{h[:8]}:3"] == {"path": "exams/prac1.pdf", "type": "pdf", "page": 2}
    assert m["prac1.pdf#pages 1-2"] == {"path": "exams/prac1.pdf", "type": "pdf", "page": 1}
    assert m["hw2/BST.java:5-7 (insert)"] == {"path": "hw2/BST.java", "type": "code", "line": 5, "end": 7}
    assert m["BST.java (lines 9-10)"]["line"] == 9
    assert "missing.pdf#page 1" not in m


def test_render_writes_relative_links(nb):
    q = nb / "study" / "quizzes"
    q.mkdir(parents=True)
    (q / "x.json").write_text(json.dumps(deck([{"source": "prac1.pdf", "location": "page 2"}])))
    assert main(["-C", str(nb), "render", "study/quizzes/x.json"]) == 0
    page = (q / "x.html").read_text()
    assert 'window.EZTUDY_LINKS = {"base": "../../sources/", "map": {"prac1.pdf#page 2": {"path": "exams/prac1.pdf"' in page
    assert "a.cite" in page and "citeHref" in page


def test_server_serves_sources_safely(nb):
    ws = find_workspace(nb)
    srv = serve.Server(ws)
    threading.Thread(target=srv.run, daemon=True).start()
    try:
        def get(path, token=srv.token):
            sep = "&" if "?" in path else "?"
            try:
                with urllib.request.urlopen(f"{srv.url}{path}{sep}t={token}", timeout=5) as r:
                    return r.status, r.headers, r.read()
            except urllib.error.HTTPError as e:
                return e.code, e.headers, b""

        code, hd, body = get("/source/exams/prac1.pdf")
        assert code == 200 and hd["Content-Type"] == "application/pdf" and body.startswith(b"%PDF")
        code, hd, body = get("/source/hw2/BST.java?lines=5-7")
        text = body.decode()
        assert code == 200 and "default-src 'none'" in hd["Content-Security-Policy"]
        assert 'class="ln hit" id="L5"' in text and 'class="ln" id="L8"' in text and "&lt;b&gt;" in text and "<b>" not in text
        code, _, body = get("/source/exams/prac1.pdf?view=1")
        assert code == 200 and 'id="page-2"' in body.decode() and "Heap removal" in body.decode()
        assert get("/source/../study")[0] == 404
        assert get("/source/%2e%2e/.eztudy/manifest.json")[0] == 404
        assert get("/source/exams/prac1.pdf", token="nope")[0] == 403
    finally:
        srv.shutdown()
