"""What to study next: one summary of the notebook's progress that every view renders.

`build(ws)` folds the stored performance reports (`progress`), the review schedule (`srs`), the optional
syllabus and exam date (`[study]` in .eztudy/config.toml) and the study files into a plain dict. `eztudy dash`
draws it with Rich, `eztudy statusline` condenses it to one line, `eztudy tui` makes it interactive, and the agent
reads `eztudy dash --json`.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import grading
from . import progress as prog
from . import srs
from .workspace import Workspace

SYLLABUS_MATCH = 0.6  # share of a syllabus topic's words found in an item topic/tag to count it as practised
W_DUE, W_WEAK, W_MISSING, W_UNPRACTISED = 1.0, 2.0, 0.5, 1.5
MAX_RECOMMEND = 5


def study_config(ws: Workspace) -> dict:
    cfg = ws.config.get("study")
    return cfg if isinstance(cfg, dict) else {}


def exam_info(ws: Workspace, today: date) -> dict | None:
    raw = study_config(ws).get("exam")
    try:
        when = raw if isinstance(raw, date) else date.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None
    if isinstance(when, datetime):
        when = when.date()
    return {"date": when.isoformat(), "days_left": (when - today).days} if when else None


def syllabus_topics(ws: Workspace) -> list[str]:
    from . import coverage

    rel = study_config(ws).get("syllabus")
    if not rel:
        return []
    path = ws.root / str(rel)
    try:
        return [t["topic"] for t in coverage.parse_topics(path.read_text())]
    except OSError:
        return []


def _streak(days: set[date], today: date) -> int:
    d = today if today in days else today - timedelta(days=1)
    n = 0
    while d in days:
        n += 1
        d -= timedelta(days=1)
    return n


def _score_fraction(score) -> float | None:
    if not isinstance(score, dict):
        return None
    if score.get("total"):
        return score.get("right", 0) / score["total"]
    seen = (score.get("know") or 0) + (score.get("learn") or 0)
    return (score.get("know") or 0) / seen if seen else None


def decks(ws: Workspace, sched: list[dict], sessions: list[dict]) -> list[dict]:
    due_by_deck: dict[str, int] = defaultdict(int)
    for c in srs.due(sched):
        due_by_deck[c["deck"]] += 1
    last: dict[str, dict] = {}
    for s in sessions:  # oldest first, so the newest wins
        last[s["deck"]] = s
    out = []
    for p in sorted(ws.study.rglob("*.json")) if ws.study.exists() else []:
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("type") not in ("quiz", "flashcards") or not isinstance(data.get("items"), list):
            continue
        did = data.get("id") or data.get("title")
        ses = last.get(did)
        out.append({"id": did, "title": data.get("title") or did, "kind": data["type"], "items": len(data["items"]),
                    "path": p.relative_to(ws.root).as_posix(), "due": due_by_deck.get(did, 0),
                    "review": p.parent.name == srs.REVIEW_DIR,
                    "last_session": ses["finished_at"] if ses else None,
                    "last_score": round(f, 3) if ses and (f := _score_fraction(ses.get("score"))) is not None else None})
    out.sort(key=lambda d: (d["review"], -(d["due"]), d["last_session"] is None, d["path"]))
    return out


def recommend(summary: dict, sched: list[dict], syllabus: list[str]) -> list[dict]:
    from .coverage import overlap

    due_by_topic: dict[str, int] = defaultdict(int)
    for c in srs.due(sched):
        for t in c["topics"]:
            due_by_topic[t] += 1
    missing_by_topic: dict[str, int] = defaultdict(int)
    for p in summary["problem_items"]:
        if p["still_missing"]:
            for t in p["topics"]:
                missing_by_topic[t] += 1
    recs = []
    for t in summary["topics"]:
        name = t["topic"]
        if name == prog.UNTAGGED:
            continue
        due, miss = due_by_topic.get(name, 0), missing_by_topic.get(name, 0)
        score = W_DUE * due + W_WEAK * (1 - t["mastery"]) + W_MISSING * miss
        reasons = []
        if due:
            reasons.append(f"{due} due for review")
        if t["mastery"] < prog.STRONG_FROM:  # a "learning" topic at 100% after one try isn't worth flagging
            reasons.append(f"{t['mastery']:.0%} mastery ({t['status']})")
        if miss:
            reasons.append(f"{miss} item{'s' if miss > 1 else ''} still missed")
        if not reasons:
            continue
        recs.append({"topic": name, "score": round(score, 3), "reasons": reasons, "due": due, "mastery": t["mastery"],
                     "action": f"eztudy review --topic {json.dumps(name) if ' ' in name else name}" if due
                     else f"ask the agent for a quiz on {name}"})
    practised = [t["topic"] for t in summary["topics"]]
    for s in syllabus:
        if any(overlap(s, p) >= SYLLABUS_MATCH or overlap(p, s) >= SYLLABUS_MATCH for p in practised):
            continue
        recs.append({"topic": s, "score": W_UNPRACTISED, "reasons": ["on the syllabus, not practised yet"], "due": 0,
                     "mastery": None, "action": f"ask the agent for a quiz on {s}"})
    recs.sort(key=lambda r: (-r["score"], r["topic"]))
    return recs[:MAX_RECOMMEND]


def build(ws: Workspace, now: datetime | None = None, quick: bool = False) -> dict:
    """Everything a dashboard shows. `quick` skips filesystem scans and the server ping (status line)."""
    now = now or srs.now_utc()
    today = now.astimezone().date()
    reports = prog.load_all(ws)
    summary = prog.summarize(reports)
    retention, max_days = srs.settings(ws.config)
    sched = srs.schedule(reports, now, retention=retention, max_interval=max_days)
    due = srs.due_summary(sched)
    days = {srs.parse_time(r["finished_at"]).astimezone().date() for r in reports}
    week_ago = now - timedelta(days=7)
    trend = [f for s in summary["sessions"][-10:] if (f := _score_fraction(s.get("score"))) is not None]
    out = {
        "notebook": ws.root.name,
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "today": {"due_now": due["due_now"], "due_tomorrow": due["due_tomorrow"], "next_due": due["next_due"],
                  "tracked": due["tracked"], "sessions": len(reports),
                  "sessions_7d": sum(srs.parse_time(r["finished_at"]) >= week_ago for r in reports),
                  "streak_days": _streak(days, today), "exam": exam_info(ws, today)},
        "recommend": recommend(summary, sched, syllabus_topics(ws)),
        "topics": [{k: t[k] for k in ("topic", "mastery", "status", "seen", "last")} for t in summary["topics"]
                   if t["topic"] != prog.UNTAGGED],
        "misconceptions": [{"deck": p["deck"], "id": p["id"], "prompt": p["prompt"], "misses": p["misses"],
                            "attempts": p["attempts"], "topics": p["topics"],
                            "picked": p["wrong_answers"][0]["answer"] if p["wrong_answers"] else None,
                            "correct": p.get("correct_answer")}
                           for p in summary["problem_items"] if p["still_missing"]][:5],
        "trend": [round(f, 3) for f in trend],
    }
    if quick:
        return out
    out["decks"] = decks(ws, sched, summary["sessions"])
    out["system"] = system(ws)
    return out


def system(ws: Workspace) -> dict:
    from . import serve as serving

    st = serving.state_path(ws).exists() and serving.running(ws)
    return {"unimported": prog.count_unimported(ws),
            "server": serving.page_url(st) if st else None,
            "grading": {"pending": len(grading.jobs(ws, "job")) + len(grading.jobs(ws, "claimed")),
                        "failed": len(grading.jobs(ws, "failed"))}}


def status_line(info: dict) -> str:
    """One line for Claude Code's status bar."""
    t = info["today"]
    parts = []
    if t["due_now"]:
        parts.append(f"{t['due_now']} due")
    elif t["next_due"]:
        nxt = srs.parse_time(t["next_due"]).astimezone()
        parts.append("all caught up · next " + (nxt.strftime("%H:%M") if nxt.date() == datetime.now().astimezone().date()
                                               else nxt.strftime("%b %d")))
    elif not t["sessions"]:
        parts.append("no sessions yet")
    focus = [r["topic"] for r in info["recommend"][:2]]
    if focus:
        parts.append("focus: " + ", ".join(focus))
    if t["streak_days"] > 1:
        parts.append(f"{t['streak_days']}d streak")
    if t["exam"] and t["exam"]["days_left"] >= 0:
        parts.append(f"exam in {t['exam']['days_left']}d" if t["exam"]["days_left"] else "exam today")
    return "📚 " + " · ".join(parts)
