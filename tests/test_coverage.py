import json

from eztudy import coverage
from eztudy.cli import build_parser, cmd_coverage, cmd_index
from eztudy.workspace import find_workspace

TOPICS = """# Exam 1 topics

## Biology
- Mitochondria and ATP production
- [[Calvin cycle]] carbon fixation
- Ribosomes and viral RNA
1. Heap sort

## History
* **Storming of the Bastille**
"""


def test_parse_topics():
    ts = coverage.parse_topics(TOPICS)
    assert [t["topic"] for t in ts] == [
        "Mitochondria and ATP production", "Calvin cycle carbon fixation",
        "Ribosomes and viral RNA", "Heap sort", "Storming of the Bastille"]
    assert ts[0]["group"] == "Biology" and ts[-1]["group"] == "History"
    assert [t["topic"] for t in coverage.parse_topics("Graphs\n\nDijkstra\n")] == ["Graphs", "Dijkstra"]


def test_coverage_command(notebook, fake_embedder, capsys):
    ws = find_workspace(notebook)
    cmd_index(ws, build_parser().parse_args(["index"]), embedder=fake_embedder)
    (notebook / "topics.md").write_text(TOPICS)
    capsys.readouterr()
    rc = cmd_coverage(ws, build_parser().parse_args(["coverage", "topics.md", "--json", "--out", str(notebook / "gaps.md")]),
                      embedder=fake_embedder)
    assert rc == 0
    rows = {r["topic"]: r for r in json.loads(capsys.readouterr().out)}
    assert rows["Mitochondria and ATP production"]["status"] == "covered"
    assert rows["Mitochondria and ATP production"]["matches"][0]["path"] == "bio/cells.pdf"
    assert rows["Storming of the Bastille"]["status"] == "covered"
    assert rows["Ribosomes and viral RNA"]["status"] == "partial"  # 1 of 3 terms (ribosome)
    assert rows["Heap sort"]["status"] == "missing" and rows["Heap sort"]["matches"] == []
    assert list(rows)[0] == "Heap sort"  # missing first
    md = (notebook / "gaps.md").read_text()
    assert "| missing | Biology: Heap sort | — |" in md and "1 missing." in md
