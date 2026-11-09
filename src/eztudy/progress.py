"""Performance reports from the HTML player: validate, store, and aggregate into mastery.

A report is what the player saves at the end of a quiz or flashcard session (`*.eztudy-report.json`).
`import_reports` stores each one once under `.eztudy/progress/reports/`; `summarize` folds every stored
report into per-topic mastery and a list of problem items that the agent uses to tailor new material.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .workspace import Workspace

REPORT_VERSION = 1
REPORT_GLOB = "*.eztudy-report.json"
RESULTS = {"quiz": {"correct", "wrong"}, "flashcards": {"know", "learn", "unmarked"}}
SCORE = {"correct": 1.0, "know": 1.0, "wrong": 0.0, "learn": 0.0}  # unmarked carries no signal
UNTAGGED = "(untagged)"
# Each newer observation of a topic shrinks the weight of the older ones by this factor.
RECENCY_DECAY = 0.7
WEAK_BELOW, STRONG_FROM = 0.6, 0.85


class ReportError(ValueError):
    pass


def reports_dir(ws: Workspace) -> Path:
    return ws.state / "progress" / "reports"


def validate(rep) -> list[str]:
    if not isinstance(rep, dict):
        return ["report must be a JSON object"]
    if rep.get("eztudy_report") != REPORT_VERSION:
        return [f"not an eztudy report (expected \"eztudy_report\": {REPORT_VERSION})"]
    errs = []
    kind = rep.get("kind")
    if kind not in RESULTS:
        errs.append(f"`kind` must be 'quiz' or 'flashcards', got {kind!r}")
    deck = rep.get("deck")
    if not isinstance(deck, dict) or not isinstance(deck.get("id"), str) or not deck["id"]:
        errs.append("`deck.id` must be a non-empty string")
    if not isinstance(rep.get("finished_at"), str) or not re.match(r"\d{4}-\d\d-\d\dT", rep["finished_at"]):
        errs.append("`finished_at` must be an ISO timestamp")
    items = rep.get("items")
    if not isinstance(items, list):
        return errs + ["`items` must be a list"]
    for n, it in enumerate(items, start=1):
        if not isinstance(it, dict) or not isinstance(it.get("id"), str):
            errs.append(f"item {n}: needs a string `id`")
        elif kind in RESULTS and it.get("result") not in RESULTS[kind]:
            errs.append(f"item {n} ({it['id']}): `result` must be one of {sorted(RESULTS[kind])}")
    return errs


def report_key(rep: dict) -> str:
    """Stable file name: the player's session id, else a content hash."""
    sid = rep.get("session")
    if isinstance(sid, str) and re.fullmatch(r"[\w-]{1,64}", sid):
        return sid
    return hashlib.sha256(json.dumps(rep, sort_keys=True).encode()).hexdigest()[:16]


def parse(text: str, origin: str) -> dict:
    try:
        rep = json.loads(text)
    except json.JSONDecodeError as e:
        raise ReportError(f"{origin}: invalid JSON: {e}") from e
    errs = validate(rep)
    if errs:
        raise ReportError(f"{origin}:\n  - " + "\n  - ".join(errs))
    return rep


def _deck_path(ws: Workspace, deck_id: str) -> str | None:
    """study/…/x.json whose `id` (or title) is this deck, so the agent can open the items."""
    if not ws.study.exists():
        return None
    for p in sorted(ws.study.rglob("*.json")):
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and (data.get("id") or data.get("title")) == deck_id:
            return p.relative_to(ws.root).as_posix()
    return None


def store(ws: Workspace, rep: dict) -> tuple[str, bool]:
    """Save a validated report. Returns (key, newly_added)."""
    out = reports_dir(ws)
    out.mkdir(parents=True, exist_ok=True)
    key = report_key(rep)
    dest = out / f"{key}.json"
    if dest.exists():
        return key, False
    path = _deck_path(ws, rep["deck"]["id"])
    if path:
        rep = {**rep, "deck": {**rep["deck"], "path": path}}
    dest.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n")
    return key, True


def default_candidates(ws: Workspace) -> list[Path]:
    """Where the player's downloads usually end up: anywhere in study/, and ~/Downloads."""
    found = list(ws.study.rglob(REPORT_GLOB)) if ws.study.exists() else []
    downloads = Path.home() / "Downloads"
    if downloads.is_dir():
        found += downloads.glob(REPORT_GLOB)
    return sorted(set(found))


def load_all(ws: Workspace) -> list[dict]:
    d = reports_dir(ws)
    reps = []
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            rep = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if not validate(rep):
            reps.append(rep)
    return sorted(reps, key=lambda r: r["finished_at"])


def _topics(it: dict) -> list[str]:
    ts = [it["topic"]] if isinstance(it.get("topic"), str) and it["topic"] else []
    ts += [t for t in it.get("tags") or [] if isinstance(t, str) and t and t not in ts]
    return ts or [UNTAGGED]


def _status(mastery: float, seen: int) -> str:
    if mastery < WEAK_BELOW:
        return "weak"
    if mastery >= STRONG_FROM and seen >= 2:
        return "strong"
    return "learning"


def summarize(reports: list[dict], deck: str | None = None) -> dict:
    """Fold reports (oldest first) into per-topic mastery and problem items."""
    if deck:
        reports = [r for r in reports if r["deck"]["id"] == deck]
    obs: dict[str, list[float]] = defaultdict(list)  # topic -> scores, oldest first
    items: dict[tuple[str, str], dict] = {}
    for rep in reports:
        did = rep["deck"]["id"]
        for it in rep["items"]:
            score = SCORE.get(it["result"])
            if score is None:
                continue
            for t in _topics(it):
                obs[t].append(score)
            rec = items.setdefault((did, it["id"]), {
                "deck": did, "id": it["id"], "deck_path": rep["deck"].get("path"),
                "prompt": it.get("question") or it.get("front") or "", "topics": _topics(it),
                "attempts": 0, "misses": 0, "history": [], "wrong_answers": Counter()})
            rec["attempts"] += 1
            rec["misses"] += score == 0
            rec["history"].append(it["result"])
            if score == 0 and it.get("given"):
                rec["wrong_answers"][str(it["given"])] += 1
            if it.get("correct_answer"):
                rec["correct_answer"] = it["correct_answer"]

    topics = []
    for t, scores in obs.items():
        weights = [RECENCY_DECAY ** (len(scores) - 1 - i) for i in range(len(scores))]
        m = sum(w * s for w, s in zip(weights, scores)) / sum(weights)
        topics.append({"topic": t, "mastery": round(m, 3), "status": _status(m, len(scores)),
                       "seen": len(scores), "correct": int(sum(scores)), "last": "correct" if scores[-1] else "missed"})
    topics.sort(key=lambda x: (x["mastery"], -x["seen"], x["topic"]))

    problems = []
    for rec in items.values():
        last_missed = rec["history"][-1] in ("wrong", "learn")
        if rec["misses"] >= 2 or last_missed:
            problems.append({**rec, "last": rec["history"][-1], "still_missing": last_missed,
                             "wrong_answers": [{"answer": a, "count": c} for a, c in rec["wrong_answers"].most_common()]})
    problems.sort(key=lambda r: (not r["still_missing"], -r["misses"], r["deck"], r["id"]))

    sessions = [{"deck": r["deck"]["id"], "title": r["deck"].get("title"), "kind": r["kind"],
                 "finished_at": r["finished_at"], "score": r.get("score")} for r in reports]
    return {
        "reports": len(reports),
        "last_session": sessions[-1]["finished_at"] if sessions else None,
        "topics": topics,
        "weak_topics": [t["topic"] for t in topics if t["status"] == "weak"],
        "problem_items": problems,
        "sessions": sessions,
    }
