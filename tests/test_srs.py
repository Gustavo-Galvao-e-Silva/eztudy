import json
from datetime import timedelta

import pytest

from eztudy import progress as prog
from eztudy import srs
from eztudy.cli import main
from eztudy.render import StudyFormatError, id_warnings, load, to_html, validate
from eztudy.workspace import find_workspace

T0 = "2026-11-01T10:00:00Z"


def report(session, at, results, deck="cells", kind="quiz", src=None):
    """results: (id, result) pairs. `src` maps an id to the original {deck, id} (review decks)."""
    items = []
    for iid, res in results:
        it = {"id": iid, "topic": "Organelles", "result": res}
        it.update({"question": f"Q {iid}?"} if kind == "quiz" else {"front": f"F {iid}", "tags": ["cards"]})
        if src and iid in src:
            it["src"] = src[iid]
        items.append(it)
    return {"eztudy_report": 1, "kind": kind, "deck": {"id": deck, "title": deck}, "session": session,
            "started_at": at, "finished_at": at, "items": items}


def at(days: float) -> str:
    return (srs.parse_time(T0) + timedelta(days=days)).isoformat().replace("+00:00", "Z")


def mcq(iid, **kw):
    return {"id": iid, "type": "mcq", "question": f"Q {iid}?", "options": ["a", "b"], "answer": 0,
            "citations": ["c1"], "topic": "Organelles", **kw}


# --- FSRS maths -------------------------------------------------------------------------


def test_first_review_and_growth():
    s, d = srs.init(srs.GOOD)
    assert s == pytest.approx(3.173) and 1 <= d <= 10
    assert srs.interval(s) == pytest.approx(s)  # at 90% retention the interval equals the stability
    assert srs.retrievability(s, s) == pytest.approx(0.9)
    s2, _ = srs.next_state(s, d, srs.GOOD, s)
    assert s2 > 3 * s  # a successful review on time multiplies the interval
    lapse, d3 = srs.next_state(s2, d, srs.AGAIN, s2)
    assert lapse < s2 and d3 > d  # a miss shrinks stability and raises difficulty
    again, _ = srs.init(srs.AGAIN)
    assert again < 1  # a first miss comes back the same day
    same_day, _ = srs.next_state(again, srs.init(srs.AGAIN)[1], srs.GOOD, 0.01)
    assert again < same_day < 1
    assert srs.interval(10, 0.8) > srs.interval(10, 0.9) > srs.interval(10, 0.95)


def test_schedule_replays_reports():
    reps = [report("s1", T0, [("q1", "correct"), ("q2", "wrong"), ("q3", "pending")]),
            report("s2", at(3.5), [("q1", "correct"), ("q2", "correct")])]
    sched = srs.schedule(reps, srs.parse_time(at(4)))
    by_id = {c["id"]: c for c in sched}
    assert set(by_id) == {"q1", "q2"}  # pending carries no signal
    assert by_id["q1"]["reps"] == 2 and by_id["q1"]["lapses"] == 0
    assert by_id["q2"]["lapses"] == 1 and by_id["q2"]["last"] == "correct"
    assert by_id["q1"]["stability"] > by_id["q2"]["stability"]
    assert all(c["overdue_days"] < 0 for c in sched)  # both just reviewed
    later = srs.schedule(reps, srs.parse_time(at(60)))
    assert len(srs.due(later)) == 2 and srs.due_summary(later)["due_now"] == 2
    assert srs.schedule(reps, deck="other") == []


def test_settings_and_cap():
    assert srs.settings({}) == (0.9, 365.0)
    assert srs.settings({"review": {"retention": 0.8, "max_interval_days": 30}}) == (0.8, 30.0)
    assert srs.settings({"review": {"retention": 2}})[0] == 0.9
    reps = [report(f"s{n}", at(n * 40), [("q1", "correct")]) for n in range(6)]
    c = srs.schedule(reps, max_interval=10)[0]
    assert srs.parse_time(c["due"]) - srs.parse_time(c["last_review"]) == timedelta(days=10)


def test_src_counts_toward_the_original():
    reps = [report("s1", T0, [("q1", "wrong")]),
            report("s2", at(1), [("cells--q1", "wrong")], deck="review-2026-11-02", src={"cells--q1": {"deck": "cells", "id": "q1"}})]
    sched = srs.schedule(reps)
    assert [(c["deck"], c["id"], c["reps"], c["lapses"]) for c in sched] == [("cells", "q1", 2, 2)]
    summary = prog.summarize(reps)
    assert [(p["deck"], p["id"], p["attempts"]) for p in summary["problem_items"]] == [("cells", "q1", 2)]
    assert prog.summarize(reps, "cells")["reports"] == 2  # the review session counts for the deck


# --- render: ids and src ----------------------------------------------------------------


def test_render_checks_ids():
    deck = {"type": "quiz", "title": "Q", "items": [mcq("a"), mcq("a")]}
    assert any("duplicate `id`" in e for e in validate(deck))
    assert any("`src`" in e for e in validate({"type": "quiz", "title": "Q", "items": [mcq("a", src={"deck": "x"})]}))
    assert validate({"type": "quiz", "title": "Q", "items": [mcq("a", src={"deck": "x", "id": "y"})]}) == []
    no_ids = {"type": "flashcards", "title": "F", "items": [{"front": "f", "back": "b", "citations": ["c"]}]}
    assert validate(no_ids) == [] and "have no `id`" in id_warnings(no_ids)[0]


def test_player_passes_src_and_reports_fresh_marks_only():
    page = to_html({"type": "flashcards", "title": "F", "items": [{"id": "c1", "front": "f", "back": "b", "citations": ["c"]}]})
    assert "it.src ? { src: it.src }" in page and "items[i].src ? { src: items[i].src }" in page
    assert "(marked.has(ids[i]) && marks[ids[i]]) || \"unmarked\"" in page


# --- CLI ---------------------------------------------------------------------------------


@pytest.fixture
def nb(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "sources").mkdir()
    q = tmp_path / "study" / "quizzes"
    q.mkdir(parents=True)
    (q / "cells.json").write_text(json.dumps({"type": "quiz", "id": "cells", "title": "Cells", "items": [mcq("q1"), mcq("q2")]}))
    (q / "cards.json").write_text(json.dumps({"type": "flashcards", "id": "cards", "title": "Cards", "items": [
        {"id": "c1", "front": "Mitochondrion", "back": "Makes ATP", "citations": ["c1"]}]}))
    ws = find_workspace(tmp_path)
    for rep in (report("s1", T0, [("q1", "wrong"), ("q2", "correct"), ("gone", "wrong")]),
                report("s2", T0, [("c1", "learn")], deck="cards", kind="flashcards")):
        prog.store(ws, rep)
    return tmp_path


def test_due_and_status(nb, capsys):
    assert main(["-C", str(nb), "due", "--json", "--now", at(1)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["due_now"] == 3 and out["by_kind"] == {"quiz": 2, "flashcards": 1}  # q2 (Good, ~3d) is not due yet
    assert {i["id"] for i in out["items"]} == {"q1", "gone", "c1"}
    assert main(["-C", str(nb), "due", "--now", at(1)]) == 0
    assert "eztudy review" in capsys.readouterr().out
    assert main(["-C", str(nb), "due", "--json", "--now", at(0.01)]) == 0
    assert json.loads(capsys.readouterr().out)["due_now"] == 0
    assert main(["-C", str(nb), "status"]) == 0  # real clock: everything is long overdue
    assert "review:   4 due now (3 quiz, 1 cards)" in capsys.readouterr().out
    assert main(["-C", str(nb), "progress", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["due"]["tracked"] == 4


def test_review_builds_and_renders(nb, capsys):
    assert main(["-C", str(nb), "review", "--now", at(1)]) == 0
    cap = capsys.readouterr()
    assert "skipped [cells / gone]: item no longer in its deck" in cap.err
    quiz = load(nb / "study" / "review" / "review-2026-11-02.json")
    assert [(i["id"], i["src"]) for i in quiz["items"]] == [("cells--q1", {"deck": "cells", "id": "q1"})]
    cards = load(nb / "study" / "review" / "review-2026-11-02-cards.json")
    assert cards["items"][0]["src"] == {"deck": "cards", "id": "c1"} and cards["items"][0]["back"] == "Makes ATP"
    assert (nb / "study" / "review" / "review-2026-11-02.html").exists()
    assert "eztudy serve --open" in cap.out

    # Answering the review deck reschedules the original item.
    ws = find_workspace(nb)
    prog.store(ws, report("s3", at(1), [("cells--q1", "correct")], deck="review-2026-11-02",
                          src={"cells--q1": {"deck": "cells", "id": "q1"}}))
    sched = {(c["deck"], c["id"]): c for c in srs.schedule(prog.load_all(ws), srs.parse_time(at(1.1)))}
    assert sched[("cells", "q1")]["reps"] == 2 and sched[("cells", "q1")]["overdue_days"] < 0
    assert ("review-2026-11-02", "cells--q1") not in sched


def test_review_nothing_due(nb, capsys):
    assert main(["-C", str(nb), "review", "--now", at(0.01)]) == 0
    assert "nothing due for review" in capsys.readouterr().out
    assert not (nb / "study" / "review").exists()
