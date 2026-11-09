"""Map a syllabus / topic list onto the indexed sources: covered, partial or missing."""

from __future__ import annotations

import re

from . import vectordb

LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.+?)\s*$")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
STOPWORDS = set(
    "a an and are as at be by for from how in into is it its of on or the to vs versus with what why when "
    "which who using use intro introduction overview basics basic topic topics chapter week lecture part".split()
)
ORDER = {"missing": 0, "partial": 1, "covered": 2}


def parse_topics(text: str) -> list[dict]:
    """List items (-, *, 1.) become topics, grouped under the nearest heading; plain lines if there's no list."""
    topics, group, plain = [], "", []
    for line in text.splitlines():
        if h := HEADING_RE.match(line):
            group = h.group(1)
        elif m := LIST_RE.match(line):
            topics.append({"topic": _clean(m.group(1)), "group": group})
        elif line.strip() and not line.lstrip().startswith(("---", "<!--", ">")):
            plain.append({"topic": _clean(line), "group": group})
    return [t for t in (topics or plain) if t["topic"]]


def _clean(s: str) -> str:
    return re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), re.sub(r"[*_`]", "", s)).strip()


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def terms(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS and len(w) > 1}


def overlap(topic: str, text: str) -> float:
    want = terms(topic)
    return len(want & terms(text)) / len(want) if want else 0.0


def assess(db, topic: str, qvec: list[float] | None, cfg: dict, k: int = 5) -> dict:
    hits = vectordb.search(db, topic, qvec, k=k, mode="hybrid" if qvec is not None else "fts")
    sim = 0.0
    if qvec is not None:
        vhits = vectordb.search(db, topic, qvec, k=1, mode="vector")
        sim = vhits[0].score if vhits else 0.0
    scored = sorted(((overlap(topic, f"{h.title}\n{h.heading}\n{h.text}"), h) for h in hits), key=lambda x: -x[0])
    best_overlap = scored[0][0] if scored else 0.0
    if best_overlap >= cfg["coverage_covered"]:
        status = "covered"
    elif best_overlap >= cfg["coverage_partial"] or sim >= cfg["coverage_min_similarity"]:
        status = "partial"
    else:
        status = "missing"
    matches = [{"cid": h.cid, "path": h.path, "location": h.location, "citation": h.citation, "overlap": round(o, 2)}
               for o, h in scored if o > 0][:3]
    return {"status": status, "overlap": round(best_overlap, 2), "similarity": round(sim, 3), "matches": matches}


def to_markdown(rows: list[dict]) -> str:
    out = ["| Status | Topic | Best matches |", "| --- | --- | --- |"]
    for r in rows:
        topic = (f"{r['group']}: " if r["group"] else "") + r["topic"]
        best = "; ".join(f"{m['citation']} [{m['cid']}]" for m in r["matches"]) or "—"
        out.append(f"| {r['status']} | {topic.replace('|', chr(92) + '|')} | {best.replace('|', chr(92) + '|')} |")
    counts = {s: sum(r["status"] == s for r in rows) for s in ORDER}
    return "\n".join(out) + f"\n\n{counts['covered']} covered, {counts['partial']} partial, {counts['missing']} missing.\n"
