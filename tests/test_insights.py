import io
import json
from datetime import timedelta

import pytest
from rich.console import Console

from eztudy import dash, insights, srs
from eztudy import progress as prog
from eztudy.cli import main
from eztudy.workspace import find_workspace

T0 = "2026-11-01T10:00:00Z"


def at(days: float) -> str:
    return (srs.parse_time(T0) + timedelta(days=days)).isoformat().replace("+00:00", "Z")


def report(session, when, results, deck="cells", src=None):
    items = []
    for iid, topic, res in results:
        it = {"id": iid, "topic": topic, "question": f"Q {iid}?", "result": res,
              "given": "Nucleus" if res == "wrong" else "", "correct_answer": "Mitochondrion"}
        if src and iid in src:
            it["src"] = src[iid]
        items.append(it)
    right = sum(r == "correct" for *_, r in results)
    return {"eztudy_report": 1, "kind": "quiz", "deck": {"id": deck, "title": deck}, "session": session,
            "started_at": when, "finished_at": when, "score": {"right": right, "total": len(results)}, "items": items}


@pytest.fixture
def nb(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "sources").mkdir()
    q = tmp_path / "study" / "quizzes"
    q.mkdir(parents=True)
    (q / "cells.json").write_text(json.dumps({"type": "quiz", "id": "cells", "title": "Cells", "items": [
        {"id": f"q{n}", "type": "mcq", "question": "?", "options": ["a", "b"], "answer": 0, "citations": ["c"]} for n in (1, 2, 3)]}))
    (tmp_path / "topics.md").write_text("# Exam 2\n- Organelles\n- Heaps and priority queues\n")
    (tmp_path / ".eztudy").mkdir()
    (tmp_path / ".eztudy" / "config.toml").write_text('[study]\nsyllabus = "topics.md"\nexam = 2026-11-12\n')
    ws = find_workspace(tmp_path)
    prog.store(ws, report("s1", T0, [("q1", "Organelles", "wrong"), ("q2", "Energy", "correct"), ("q3", "Energy", "correct")]))
    prog.store(ws, report("s2", at(1), [("q1", "Organelles", "wrong"), ("q2", "Energy", "correct"), ("q3", "Energy", "correct")]))
    prog.store(ws, report("s3", at(2), [("cells--q1", "Organelles", "wrong")], deck="review-x",
                          src={"cells--q1": {"deck": "cells", "id": "q1"}}))
    return tmp_path


def test_build_ranks_and_counts(nb):
    info = insights.build(find_workspace(nb), srs.parse_time(at(2.5)))
    t = info["today"]
    assert t["sessions"] == 3 and t["sessions_7d"] == 3 and t["streak_days"] == 3
    assert t["exam"] == {"date": "2026-11-12", "days_left": 9}
    recs = [r["topic"] for r in info["recommend"]]
    assert recs[0] == "Organelles" and "Energy" not in recs  # weak + still missed beats a strong topic
    assert info["recommend"][0]["reasons"] and "still missed" in " ".join(info["recommend"][0]["reasons"])
    assert "Heaps and priority queues" in recs  # syllabus topic never practised
    assert info["misconceptions"][0]["picked"] == "Nucleus" and info["misconceptions"][0]["attempts"] == 3
    deck = next(d for d in info["decks"] if d["id"] == "cells")
    assert deck["items"] == 3 and deck["last_score"] == pytest.approx(2 / 3, abs=1e-3)
    assert info["system"]["grading"] == {"pending": 0, "failed": 0}
    later = insights.build(find_workspace(nb), srs.parse_time(at(30)))
    assert next(d for d in later["decks"] if d["id"] == "cells")["due"] == 3  # review copy counts for the deck
    assert later["recommend"][0]["action"].startswith("eztudy review --topic")


def test_dash_renders_wide_narrow_and_empty(nb, tmp_path_factory):
    info = insights.build(find_workspace(nb), srs.parse_time(at(2.5)))
    for width in (80, 140):
        buf = io.StringIO()
        dash.render(info, Console(file=buf, width=width, color_system=None))
        out = buf.getvalue()
        for title in ("Next up", "Mastery", "Still missing", "Recent", "Decks", "exam in 9 days"):
            assert title in out, (width, title)
    empty = tmp_path_factory.mktemp("empty")
    (empty / "sources").mkdir()
    buf = io.StringIO()
    dash.render(insights.build(find_workspace(empty)), Console(file=buf, width=80, color_system=None))
    assert "No study sessions yet" in buf.getvalue()


def test_dash_json_and_statusline(nb, capsys, monkeypatch):
    assert main(["-C", str(nb), "dash", "--json", "--now", at(2.5)]) == 0
    info = json.loads(capsys.readouterr().out)
    assert {"today", "recommend", "topics", "misconceptions", "trend", "decks", "system"} <= set(info)
    line = insights.status_line(insights.build(find_workspace(nb), srs.parse_time(at(30)), quick=True))
    assert line.startswith("📚 ") and "due" in line and "focus: Organelles" in line

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"workspace": {"current_dir": str(nb / "study")}})))
    monkeypatch.setattr("select.select", lambda r, w, x, t: (r, [], []))
    assert main(["statusline"]) == 0
    assert capsys.readouterr().out.startswith("📚 ")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(nb.parent / "nowhere")})))
    assert main(["statusline"]) == 0
    assert capsys.readouterr().out == ""  # outside a notebook: silent, never an error


def test_statusline_install(nb, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", [str(nb / "eztudy")])
    (nb / "eztudy").write_text("#!/bin/sh\n")
    settings = nb / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(eztudy:*)"]}}))
    assert main(["-C", str(nb), "statusline", "--install"]) == 0
    data = json.loads(settings.read_text())
    assert data["permissions"] and data["statusLine"]["command"].endswith("eztudy statusline")
    assert main(["-C", str(nb), "statusline", "--install"]) == 0 and "already installed" in capsys.readouterr().out
    data["statusLine"] = {"type": "command", "command": "other"}
    settings.write_text(json.dumps(data))
    assert main(["-C", str(nb), "statusline", "--install"]) == 1
    assert json.loads(settings.read_text())["statusLine"]["command"] == "other"
    assert main(["-C", str(nb), "statusline", "--install", "--force"]) == 0
    assert json.loads(settings.read_text())["statusLine"]["command"].endswith("eztudy statusline")
