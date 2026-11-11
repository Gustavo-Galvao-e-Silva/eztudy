"""Spaced repetition: when each quiz item and flashcard should come back.

The schedule is derived, never stored: every call replays the imported performance reports
(`progress.load_all`, oldest first) through FSRS-5 with its published default weights. So
re-imports, self-graded replacements of `pending` reports and edited decks stay consistent
with no state to migrate.

Grades are binary because the player records pass/fail: `correct`/`know` -> Good, `wrong`/`learn`
-> Again; `pending`/`unmarked` carry no signal and are skipped (the same rule as `progress.SCORE`).
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

from . import progress as prog

# FSRS-5 default parameters (https://github.com/open-spaced-repetition/fsrs4anki/wiki/The-Algorithm).
W = (0.40255, 1.18385, 3.173, 15.69105, 7.1949, 0.5345, 1.4604, 0.0046, 1.54575, 0.1192,
     1.01925, 1.9395, 0.11, 0.29605, 2.2698, 0.2315, 2.9898, 0.51655, 0.6621)
DECAY = -0.5
FACTOR = 0.9 ** (1 / DECAY) - 1  # = 19/81, so that R(S, S) = 0.9
AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
GRADE = {"correct": GOOD, "know": GOOD, "wrong": AGAIN, "learn": AGAIN}
DEFAULT_RETENTION = 0.9
DEFAULT_MAX_INTERVAL = 365.0  # days
MIN_STABILITY = 0.01


def retrievability(elapsed_days: float, stability: float) -> float:
    """Probability of recall after `elapsed_days` for a memory of this stability."""
    return (1 + FACTOR * max(elapsed_days, 0.0) / stability) ** DECAY


def interval(stability: float, retention: float = DEFAULT_RETENTION) -> float:
    """Days until recall probability falls to `retention` (equals the stability at 0.9)."""
    return stability / FACTOR * (retention ** (1 / DECAY) - 1)


def _clamp_d(d: float) -> float:
    return min(max(d, 1.0), 10.0)


def _init_difficulty(grade: int) -> float:
    return W[4] - math.exp(W[5] * (grade - 1)) + 1


def init(grade: int) -> tuple[float, float]:
    """(stability, difficulty) after the first review."""
    return W[grade - 1], _clamp_d(_init_difficulty(grade))


def _next_difficulty(d: float, grade: int) -> float:
    d2 = d + (-W[6] * (grade - 3)) * (10 - d) / 9  # linear damping
    return _clamp_d(W[7] * _init_difficulty(EASY) + (1 - W[7]) * d2)  # mean reversion


def next_state(stability: float, difficulty: float, grade: int, elapsed_days: float) -> tuple[float, float]:
    """(stability, difficulty) after a review `elapsed_days` after the previous one."""
    if elapsed_days < 1:  # same-day review: short-term stability update
        s = stability * math.exp(W[17] * (grade - 3 + W[18]))
    else:
        r = retrievability(elapsed_days, stability)
        if grade == AGAIN:
            forget = W[11] * difficulty ** -W[12] * ((stability + 1) ** W[13] - 1) * math.exp(W[14] * (1 - r))
            s = min(forget, stability)
        else:
            hard = W[15] if grade == HARD else 1.0
            easy = W[16] if grade == EASY else 1.0
            s = stability * (1 + math.exp(W[8]) * (11 - difficulty) * stability ** -W[9]
                             * (math.exp(W[10] * (1 - r)) - 1) * hard * easy)
    return max(s, MIN_STABILITY), _next_difficulty(difficulty, grade)


def parse_time(ts: str) -> datetime:
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def settings(config: dict) -> tuple[float, float]:
    """(retention, max_interval_days) from `[review]` in .eztudy/config.toml."""
    cfg = config.get("review") if isinstance(config.get("review"), dict) else {}
    try:
        retention = float(cfg.get("retention", DEFAULT_RETENTION))
        max_days = float(cfg.get("max_interval_days", DEFAULT_MAX_INTERVAL))
    except (TypeError, ValueError):
        return DEFAULT_RETENTION, DEFAULT_MAX_INTERVAL
    if not 0.5 <= retention < 1:
        retention = DEFAULT_RETENTION
    return retention, max(max_days, 1.0)


def schedule(reports: list[dict], now: datetime | None = None, deck: str | None = None,
             retention: float = DEFAULT_RETENTION, max_interval: float = DEFAULT_MAX_INTERVAL) -> list[dict]:
    """One entry per reviewed item (keyed like `progress.item_key`), soonest due first."""
    now = now or now_utc()
    cards: dict[tuple[str, str], dict] = {}
    for rep in sorted(reports, key=lambda r: r["finished_at"]):
        at = parse_time(rep["finished_at"])
        for it in rep["items"]:
            grade = GRADE.get(it.get("result"))
            if grade is None:
                continue
            did, iid = prog.item_key(rep, it)
            if deck and did != deck:
                continue
            c = cards.get((did, iid))
            if c is None:
                s, d = init(grade)
                c = cards[(did, iid)] = {"deck": did, "id": iid, "kind": rep["kind"], "deck_path": None,
                                         "reps": 0, "lapses": 0}
            else:
                s, d = next_state(c["stability"], c["difficulty"], grade, (at - c["_at"]).total_seconds() / 86400)
            c.update(stability=s, difficulty=d, _at=at, reps=c["reps"] + 1, lapses=c["lapses"] + (grade == AGAIN),
                     last=it["result"], prompt=it.get("question") or it.get("front") or c.get("prompt", ""),
                     topics=prog._topics(it))
            if did == rep["deck"]["id"] and rep["deck"].get("path"):
                c["deck_path"] = rep["deck"]["path"]

    out = []
    for c in cards.values():
        at = c.pop("_at")
        due = at + timedelta(days=min(interval(c["stability"], retention), max_interval))
        out.append({**c, "stability": round(c["stability"], 3), "difficulty": round(c["difficulty"], 3),
                    "last_review": at.isoformat().replace("+00:00", "Z"),
                    "due": due.isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "overdue_days": round((now - due).total_seconds() / 86400, 2),
                    "retrievability": round(retrievability((now - at).total_seconds() / 86400, c["stability"]), 3)})
    out.sort(key=lambda c: (c["due"], c["deck"], c["id"]))
    return out


def due(sched: list[dict], within_days: float = 0) -> list[dict]:
    """Items due now, or within the next `within_days`."""
    return [c for c in sched if c["overdue_days"] >= -within_days]


def due_summary(sched: list[dict]) -> dict:
    now_items = due(sched)
    upcoming = [c for c in sched if c["overdue_days"] < 0]
    by_kind = {"quiz": 0, "flashcards": 0}
    for c in now_items:
        by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
    return {"tracked": len(sched), "due_now": len(now_items), "due_tomorrow": len(due(sched, 1)) - len(now_items),
            "by_kind": by_kind, "next_due": upcoming[0]["due"] if upcoming else None,
            "decks": sorted({c["deck"] for c in now_items})}


# --- review decks ----------------------------------------------------------------------

REVIEW_DIR = "review"
SEP = "--"


def _load_deck(ws, deck_id: str, deck_path: str | None) -> dict | None:
    path = deck_path or prog._deck_path(ws, deck_id)
    if not path:
        return None
    try:
        data = json.loads((ws.root / path).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and (data.get("id") or data.get("title")) == deck_id else None


def review_decks(ws, picked: list[dict], day: str) -> tuple[dict[str, dict], list[dict]]:
    """Copy the picked schedule entries out of their source decks into a review quiz and/or
    flashcard deck. Each copy keeps `src: {deck, id}` so its result counts toward the original.
    Returns ({"quiz": data, "flashcards": data} (only kinds with items), skipped entries)."""
    cache: dict[str, dict | None] = {}
    out: dict[str, list[dict]] = {"quiz": [], "flashcards": []}
    skipped = []
    for c in picked:
        if c["deck"] not in cache:
            cache[c["deck"]] = _load_deck(ws, c["deck"], c.get("deck_path"))
        data = cache[c["deck"]]
        item = next((it for it in (data or {}).get("items", []) if isinstance(it, dict) and it.get("id") == c["id"]), None)
        kind = (data or {}).get("type")
        if item is None or kind not in out:
            skipped.append({"deck": c["deck"], "id": c["id"],
                            "reason": "item no longer in its deck" if data else "source deck not found under study/"})
            continue
        out[kind].append({**item, "id": f"{c['deck']}{SEP}{c['id']}", "src": {"deck": c["deck"], "id": c["id"]}})
    decks = {}
    if out["quiz"]:
        decks["quiz"] = {"type": "quiz", "id": f"review-{day}", "title": f"Review · {day}",
                         "description": "Items due for review, picked by the spaced-repetition schedule.",
                         "items": out["quiz"]}
    if out["flashcards"]:
        decks["flashcards"] = {"type": "flashcards", "id": f"review-{day}-cards", "title": f"Review cards · {day}",
                               "description": "Cards due for review, picked by the spaced-repetition schedule.",
                               "items": out["flashcards"]}
    return decks, skipped
