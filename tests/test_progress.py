import json

import pytest

from eztudy import progress as prog
from eztudy.cli import main
from eztudy.render import to_html
from eztudy.workspace import find_workspace


def quiz_report(session, at, results, deck="cells"):
    items = [{"id": iid, "type": "mcq", "topic": topic, "question": f"Q {iid}?", "result": res,
              "given": "" if res == "correct" else "Nucleus", "correct_answer": "Mitochondrion"}
             for iid, topic, res in results]
    right = sum(r == "correct" for _, _, r in results)
    return {"eztudy_report": 1, "kind": "quiz", "deck": {"id": deck, "title": "Cells"}, "session": session,
            "started_at": at, "finished_at": at, "score": {"right": right, "total": len(results)}, "items": items}


@pytest.fixture
def nb(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # keep ~/Downloads out of the test
    (tmp_path / "sources").mkdir()
    (tmp_path / "study" / "quizzes").mkdir(parents=True)
    (tmp_path / "study" / "quizzes" / "cells.json").write_text(json.dumps({"type": "quiz", "id": "cells", "title": "Cells", "items": []}))
    return tmp_path


def test_validate_rejects_malformed():
    assert prog.validate(quiz_report("s1", "2026-11-01T10:00:00Z", [("q1", "A", "correct")])) == []
    assert "not an eztudy report" in prog.validate({"kind": "quiz"})[0]
    bad = quiz_report("s1", "2026-11-01T10:00:00Z", [("q1", "A", "know")])
    assert any("`result`" in e for e in prog.validate(bad))
    with pytest.raises(prog.ReportError):
        prog.parse("{nope", "x.json")


def test_import_is_idempotent_and_finds_deck(nb, capsys):
    f = nb / "study" / "quizzes" / "cells.20261101T100000.eztudy-report.json"
    f.write_text(json.dumps(quiz_report("s1", "2026-11-01T10:00:00Z", [("q1", "A", "wrong")])))
    assert main(["-C", str(nb), "report", "import"]) == 0  # scans study/
    assert "1 new" in capsys.readouterr().out
    assert main(["-C", str(nb), "report", "import", str(f)]) == 0
    assert "0 new, 1 already imported" in capsys.readouterr().out
    stored = json.loads((nb / ".eztudy" / "progress" / "reports" / "s1.json").read_text())
    assert stored["deck"]["path"] == "study/quizzes/cells.json"
    (nb / "junk.eztudy-report.json").write_text("[]")
    assert main(["-C", str(nb), "report", "import", str(nb / "junk.eztudy-report.json")]) == 1


def test_summarize_mastery_weights_recent_and_lists_problems():
    reps = [
        quiz_report("s1", "2026-11-01T10:00:00Z", [("q1", "Organelles", "wrong"), ("q2", "Energy", "correct")]),
        quiz_report("s2", "2026-11-02T10:00:00Z", [("q1", "Organelles", "wrong"), ("q2", "Energy", "correct")]),
        quiz_report("s3", "2026-11-03T10:00:00Z", [("q1", "Organelles", "correct"), ("q2", "Energy", "correct")]),
    ]
    s = prog.summarize(reps)
    topics = {t["topic"]: t for t in s["topics"]}
    assert topics["Energy"]["status"] == "strong" and topics["Energy"]["mastery"] == 1
    # 1 right, 2 wrong, but the right one is newest: weighted above the plain 1/3.
    assert 1 / 3 < topics["Organelles"]["mastery"] < 0.6
    assert s["weak_topics"] == ["Organelles"]
    [p] = s["problem_items"]
    assert (p["id"], p["misses"], p["still_missing"]) == ("q1", 2, False)
    assert p["wrong_answers"] == [{"answer": "Nucleus", "count": 2}]


def test_flashcard_reports_use_tags_and_skip_unmarked():
    rep = {"eztudy_report": 1, "kind": "flashcards", "deck": {"id": "cards"}, "finished_at": "2026-11-01T10:00:00Z",
           "items": [{"id": "c1", "tags": ["ATP"], "front": "ATP?", "result": "learn"},
                     {"id": "c2", "front": "x", "result": "unmarked"}]}
    s = prog.summarize([rep])
    assert [(t["topic"], t["status"]) for t in s["topics"]] == [("ATP", "weak")]
    assert s["problem_items"][0]["still_missing"]


def test_progress_and_status_cli(nb, capsys):
    ws = find_workspace(nb)
    prog.store(ws, quiz_report("s1", "2026-11-01T10:00:00Z", [("q1", "Organelles", "wrong")]))
    (nb / "study" / "later.eztudy-report.json").write_text(json.dumps(quiz_report("s2", "2026-11-02T10:00:00Z", [("q1", "Organelles", "correct")])))
    assert main(["-C", str(nb), "progress", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["reports"] == 1 and out["weak_topics"] == ["Organelles"]
    assert main(["-C", str(nb), "status"]) == 0
    text = capsys.readouterr().out
    assert "weak: Organelles" in text and "1 saved report(s) not imported" in text


def test_player_offers_report():
    page = to_html({"type": "quiz", "title": "Q", "items": [
        {"type": "mcq", "question": "P", "options": ["a", "b"], "answer": 1, "citations": ["x"]}]})
    assert "eztudy_report: 1" in page and "Save report" in page and ".eztudy-report.json" in page
