"""Agent grading of free-text (`short`) and `code` quiz answers.

When the player is served by `eztudy serve`, a finished quiz's report arrives with those items marked
`result: "pending"`. The server stores it and writes a *job* under `.eztudy/progress/grading/`. A grader then
claims the job, grades it, and writes a *result*:

- by default the server grades at once with headless `claude -p` on a cheap model (`[grading] model`,
  default haiku): the user's own login, no API key, no tools, only the packet (question, answer, key, rubric);
- with no headless grader (no `claude` on PATH, `[grading] fallback = "none"`), or when it fails while an agent
  is listening, the live agent session blocked in `eztudy report wait` claims the job, grades the printed
  packet and pipes verdicts into `eztudy report grade <session> -`.

Processes coordinate only through files, renamed atomically:
`<session>.job.json` → `<session>.claimed.json` → `<session>.result.json` (or `<session>.failed.json`).
A waiting `report wait` keeps `waiter.json` fresh so the server knows a live agent is listening.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import progress as prog
from .workspace import Workspace

FREE_TYPES = {"short", "code"}
WAITER_FRESH_S = 10      # a waiter heartbeat older than this means nobody is listening
FALLBACK_TIMEOUT_S = 240
DEFAULT_MODEL = "haiku"  # grading against a given key is easy: keep it cheap

VERDICT_SCHEMA = {
    "type": "object",
    "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "required": ["id", "result", "feedback"],
        "properties": {
            "id": {"type": "string"},
            "result": {"enum": ["correct", "wrong"]},
            "points": {"type": "number"},
            "feedback": {"type": "string"},
            "rubric": {"type": "array", "items": {"type": "object", "required": ["met"], "properties": {
                "id": {"type": ["string", "null"]}, "index": {"type": "integer"},
                "met": {"type": "boolean"}, "note": {"type": "string"}}}},
        }}}},
}

RULES = """\
Grade each answer against its model answer, rubric and explanation (the sources behind them are cited).
- `correct` when the student's answer gets the core idea right, even in different words or with a
  different but valid approach (code). `wrong` when the core idea is missing, incorrect, or the answer is blank.
- Code with a rubric: mark each criterion `met` true/false (by `index`, 0-based, or `id`) with a short note; set
  `points` to the points earned. Mark `correct` when it earns at least ~70% of the points and has no serious bug.
- `feedback`: one or two sentences to the student. Say what was right, then name the specific gap or mistake.
  Markdown is fine. Don't just restate the model answer.
- Reply with JSON only: {"items": [{"id", "result", "points"?, "feedback", "rubric"?: [{"index", "met", "note"}]}]},
  one entry per item in the packet."""


class GradingError(ValueError):
    pass


def grading_dir(ws: Workspace) -> Path:
    return ws.state / "progress" / "grading"


def _p(ws: Workspace, session: str, kind: str) -> Path:
    return grading_dir(ws) / f"{session}.{kind}.json"


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _read(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def pending_items(rep: dict) -> list[dict]:
    return [it for it in rep.get("items", []) if it.get("result") == "pending"]


def _deck_items(ws: Workspace, rep: dict) -> dict[str, dict]:
    """The deck's own items by report id, for explanation and citations (not carried in the report)."""
    path = rep.get("deck", {}).get("path")
    data = _read(ws.root / path) if path else None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return {}
    return {(it.get("id") or f"q{i + 1}"): it for i, it in enumerate(data["items"]) if isinstance(it, dict)}


def packet(ws: Workspace, rep: dict) -> dict:
    """What a grader needs: each pending item with the student's answer, the model answer and the rubric."""
    src = _deck_items(ws, rep)
    items = []
    for it in pending_items(rep):
        d = src.get(it["id"], {})
        entry = {"id": it["id"], "type": it.get("type"), "topic": it.get("topic"), "question": it.get("question"),
                 "student_answer": it.get("given") or "", "model_answer": it.get("correct_answer")}
        if d.get("explanation"):
            entry["explanation"] = d["explanation"]
        if d.get("citations"):
            entry["citations"] = d["citations"]
        if it.get("type") == "code":
            entry["language"] = it.get("language")
            entry["rubric"] = [{"index": k, "id": c.get("id"), "text": c.get("text"), "points": c.get("points"),
                                "student_ticked": c.get("ticked", False)} for k, c in enumerate(it.get("rubric") or [])]
        items.append(entry)
    return {"session": rep["session"], "deck": rep["deck"], "items": items}


def enqueue(ws: Workspace, rep: dict, agent_only: bool = False) -> bool:
    """Write a grading job for a stored report that has pending items. Returns whether one was queued.
    `agent_only` jobs are left for the live agent (the headless grader already failed on them)."""
    if not pending_items(rep):
        return False
    s = rep["session"]
    for kind in ("result", "failed", "claimed"):
        _p(ws, s, kind).unlink(missing_ok=True)
    _write(_p(ws, s, "job"), {"session": s, "queued_at": time.time(), "agent_only": agent_only})
    return True


def agent_only(path: Path) -> bool:
    return bool((_read(path) or {}).get("agent_only"))


def status(ws: Workspace, session: str) -> dict:
    if (r := _read(_p(ws, session, "result"))) is not None:
        return {"status": "done", **r}
    if (f := _read(_p(ws, session, "failed"))) is not None:
        return {"status": "failed", "error": f.get("error", "grading failed")}
    if _p(ws, session, "job").exists() or _p(ws, session, "claimed").exists():
        return {"status": "pending"}
    return {"status": "none"}


def jobs(ws: Workspace, kind: str = "job") -> list[Path]:
    d = grading_dir(ws)
    return sorted(d.glob(f"*.{kind}.json"), key=lambda p: p.stat().st_mtime) if d.exists() else []


def claim(ws: Workspace, session: str, by: str) -> bool:
    """Atomically take a queued job; False if someone else got it first."""
    try:
        os.rename(_p(ws, session, "job"), _p(ws, session, "claimed"))
    except FileNotFoundError:
        return False
    _write(_p(ws, session, "claimed"), {"session": session, "by": by, "claimed_at": time.time()})
    return True


def heartbeat(ws: Workspace) -> None:
    _write(grading_dir(ws) / "waiter.json", {"pid": os.getpid(), "at": time.time()})


def clear_heartbeat(ws: Workspace) -> None:
    w = _read(grading_dir(ws) / "waiter.json")
    if w and w.get("pid") == os.getpid():
        (grading_dir(ws) / "waiter.json").unlink(missing_ok=True)


def waiter_alive(ws: Workspace) -> bool:
    w = _read(grading_dir(ws) / "waiter.json")
    return bool(w) and time.time() - w.get("at", 0) < WAITER_FRESH_S


def _report_path(ws: Workspace, session: str) -> Path:
    return prog.reports_dir(ws) / f"{session}.json"


def load_report(ws: Workspace, session: str) -> dict:
    rep = _read(_report_path(ws, session))
    if not isinstance(rep, dict):
        raise GradingError(f"no stored report for session {session!r}")
    return rep


def validate_verdicts(rep: dict, data) -> list[dict]:
    """Check verdicts against the report's pending items; returns the normalized verdict list."""
    if isinstance(data, list):
        data = {"items": data}
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise GradingError('verdicts must be {"items": [...]}')
    by_id = {it["id"]: it for it in pending_items(rep)}
    out, errs = [], []
    for n, v in enumerate(data["items"], start=1):
        if not isinstance(v, dict) or v.get("id") not in by_id:
            errs.append(f"verdict {n}: `id` must be one of the pending items {sorted(by_id)}")
            continue
        if v.get("result") not in ("correct", "wrong"):
            errs.append(f"{v['id']}: `result` must be 'correct' or 'wrong'")
        if not isinstance(v.get("feedback"), str) or not v["feedback"].strip():
            errs.append(f"{v['id']}: needs a non-empty `feedback` string")
        if "points" in v and not isinstance(v["points"], (int, float)):
            errs.append(f"{v['id']}: `points` must be a number")
        rubric = by_id[v["id"]].get("rubric") or []
        marks = []
        for c in v.get("rubric") or []:
            k = c.get("index") if isinstance(c, dict) else None
            if not isinstance(k, int) and isinstance(c, dict) and c.get("id") is not None:
                k = next((j for j, r in enumerate(rubric) if r.get("id") == c["id"]), None)
            if not isinstance(c, dict) or not isinstance(k, int) or not 0 <= k < len(rubric) or not isinstance(c.get("met"), bool):
                errs.append(f"{v['id']}: rubric entries need a valid `index` (or `id`) and boolean `met`")
                continue
            marks.append({"index": k, "met": c["met"], **({"note": str(c["note"])} if c.get("note") else {})})
        out.append({"id": v["id"], "result": v.get("result"), "feedback": str(v.get("feedback", "")).strip(),
                    **({"points": v["points"]} if "points" in v else {}), **({"rubric": marks} if marks else {})})
    missing = sorted(set(by_id) - {v["id"] for v in out})
    if missing:
        errs.append(f"no verdict for: {', '.join(missing)}")
    if errs:
        raise GradingError("; ".join(errs))
    return out


def apply(ws: Workspace, session: str, data, grader: str) -> dict:
    """Validate verdicts, fold them into the stored report, and publish the result for the player."""
    rep = load_report(ws, session)
    verdicts = validate_verdicts(rep, data)
    by_id = {v["id"]: v for v in verdicts}
    for it in rep["items"]:
        v = by_id.get(it["id"])
        if not v:
            continue
        it.update(result=v["result"], graded=grader, feedback=v["feedback"])
        if "points" in v:
            it["points"] = v["points"]
        for m in v.get("rubric", []):
            c = it["rubric"][m["index"]]
            c["met"] = m["met"]
            if m.get("note"):
                c["note"] = m["note"]
    if rep["kind"] == "quiz":
        rep["score"] = {"right": sum(it["result"] == "correct" for it in rep["items"]), "total": len(rep["items"])}
    _write(_report_path(ws, session), rep)
    result = {"session": session, "grader": grader, "score": rep.get("score"), "items": verdicts}
    _write(_p(ws, session, "result"), result)
    for kind in ("job", "claimed", "failed"):
        _p(ws, session, kind).unlink(missing_ok=True)
    return result


def fail(ws: Workspace, session: str, error: str) -> None:
    _write(_p(ws, session, "failed"), {"session": session, "error": error})
    for kind in ("job", "claimed"):
        _p(ws, session, kind).unlink(missing_ok=True)


# --- headless fallback ---------------------------------------------------------------


def fallback_command(ws: Workspace) -> list[str] | None:
    """`claude -p` with no tools, or [grading] command from config; None when disabled or unavailable."""
    cfg = ws.config.get("grading", {}) if isinstance(ws.config.get("grading"), dict) else {}
    if cfg.get("fallback", "claude") == "none":
        return None
    if cfg.get("command"):
        cmd = cfg["command"]
        return [cmd] if isinstance(cmd, str) else list(cmd)
    exe = shutil.which("claude")
    if not exe:
        return None
    return [exe, "-p", "--model", str(cfg.get("model") or DEFAULT_MODEL), "--tools", "", "--output-format", "json",
            "--no-session-persistence", "--json-schema", json.dumps(VERDICT_SCHEMA, separators=(",", ":"))]


def prompt_for(pk: dict) -> str:
    """Only what grading needs: citations are dropped (the grader can't open sources) and JSON is compact."""
    items = [{k: v for k, v in it.items() if k != "citations"} for it in pk["items"]]
    return (f"You are grading a student's quiz answers for the study deck \"{pk['deck'].get('title') or pk['deck']['id']}\".\n\n"
            f"{RULES}\n\nGrading packet:\n{json.dumps(items, ensure_ascii=False, separators=(',', ':'))}\n")


def _parse_cli_output(text: str):
    """`claude -p --output-format json` wraps the answer; accept the wrapper, its fields, or bare JSON."""
    text = text.strip()
    obj = json.loads(text)
    if isinstance(obj, dict) and "items" not in obj:
        if obj.get("is_error"):
            raise GradingError(f"claude reported an error: {str(obj.get('result'))[:200]}")
        if isinstance(obj.get("structured_output"), dict):
            return obj["structured_output"]
        if isinstance(obj.get("result"), str):
            inner = obj["result"].strip()
            if inner.startswith("```"):
                inner = inner.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(inner)
    return obj


def run_fallback(ws: Workspace, session: str, cmd: list[str]) -> dict | None:
    """Grade a claimed job with the headless command. Writes a result or a failure; never raises."""
    try:
        pk = packet(ws, load_report(ws, session))
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
        proc = subprocess.run(cmd, input=prompt_for(pk), capture_output=True, text=True,
                              timeout=FALLBACK_TIMEOUT_S, cwd=ws.root, env=env)
        if proc.returncode != 0:
            raise GradingError(f"{Path(cmd[0]).name} exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:300]}")
        return apply(ws, session, _parse_cli_output(proc.stdout), grader="claude")
    except (GradingError, ValueError, OSError, subprocess.TimeoutExpired) as e:
        if waiter_alive(ws):  # an agent is listening: let it grade instead of giving up
            try:
                enqueue(ws, load_report(ws, session), agent_only=True)
                return None
            except GradingError:
                pass
        fail(ws, session, f"automatic grading failed: {e}")
        return None


def sweep(ws: Workspace, start_fallback) -> None:
    """One watchdog pass: hand every queued job to the headless grader (`start_fallback(session)`)."""
    for p in jobs(ws, "job"):
        if agent_only(p):
            continue
        session = p.name.removesuffix(".job.json")
        if claim(ws, session, "fallback"):
            start_fallback(session)
