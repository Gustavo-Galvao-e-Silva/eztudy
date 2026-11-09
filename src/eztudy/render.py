"""Validate study JSON (quiz / flashcards) and render it to Markdown + standalone HTML."""

from __future__ import annotations

import html
import json
from importlib import resources
from pathlib import Path

QUIZ_TYPES = {"mcq", "multi", "true_false", "short"}


class StudyFormatError(ValueError):
    pass


def validate(data: dict) -> list[str]:
    errs: list[str] = []
    kind = data.get("type")
    if kind not in ("quiz", "flashcards"):
        return [f"top-level `type` must be 'quiz' or 'flashcards', got {kind!r}"]
    if not data.get("title"):
        errs.append("missing `title`")
    if "instant_feedback" in data and not isinstance(data["instant_feedback"], bool):
        errs.append("`instant_feedback` must be true or false")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return errs + ["`items` must be a non-empty list"]
    for n, it in enumerate(items, start=1):
        where = f"item {n}" + (f" ({it.get('id')})" if isinstance(it, dict) and it.get("id") else "")
        if not isinstance(it, dict):
            errs.append(f"{where}: must be an object")
            continue
        if not it.get("citations"):
            errs.append(f"{where}: missing `citations` (every item must be grounded in sources)")
        if kind == "flashcards":
            for k in ("front", "back"):
                if not it.get(k):
                    errs.append(f"{where}: missing `{k}`")
            continue
        t = it.get("type")
        if t not in QUIZ_TYPES:
            errs.append(f"{where}: `type` must be one of {sorted(QUIZ_TYPES)}")
            continue
        if not it.get("question"):
            errs.append(f"{where}: missing `question`")
        ans = it.get("answer")
        if t in ("mcq", "multi"):
            opts = it.get("options")
            if not isinstance(opts, list) or len(opts) < 2:
                errs.append(f"{where}: `options` needs at least 2 entries")
                continue
            idxs = ans if isinstance(ans, list) else [ans]
            if t == "mcq" and isinstance(ans, list):
                errs.append(f"{where}: mcq `answer` must be a single option index (use type 'multi' for several)")
            if not idxs or not all(isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(opts) for i in idxs):
                errs.append(f"{where}: `answer` must be 0-based option index(es) within range")
        elif t == "true_false" and not isinstance(ans, bool):
            errs.append(f"{where}: true_false `answer` must be true or false")
        elif t == "short" and not (isinstance(ans, str) and ans.strip()):
            errs.append(f"{where}: short `answer` must be a non-empty model answer string")
    return errs


def unknown_citations(data: dict, known_cids: set[str]) -> list[str]:
    """Warnings for citation objects whose `cid` is not a chunk in the index (likely a typo)."""
    warns = []
    for n, it in enumerate(data.get("items") or [], start=1):
        if not isinstance(it, dict):
            continue
        where = f"item {n}" + (f" ({it['id']})" if it.get("id") else "")
        for c in it.get("citations") or []:
            cid = c.get("cid") if isinstance(c, dict) else None
            if cid and cid not in known_cids:
                warns.append(f"{where}: unknown chunk id {cid!r}")
    return warns


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise StudyFormatError(f"{path}: invalid JSON: {e}") from e
    errs = validate(data)
    if errs:
        raise StudyFormatError(f"{path}:\n  - " + "\n  - ".join(errs))
    return data


def _cite_text(item: dict) -> str:
    parts = []
    for c in item.get("citations") or []:
        if isinstance(c, str):
            parts.append(c)
        else:
            s = ", ".join(x for x in (c.get("source"), c.get("location")) if x)
            if c.get("cid"):
                s += f" [{c['cid']}]"
            parts.append(s)
    return "; ".join(parts)


def to_markdown(data: dict) -> str:
    out = [f"# {data['title']}", ""]
    if data.get("description"):
        out += [data["description"], ""]
    if data["type"] == "flashcards":
        out += ["| # | Front | Back | Source |", "| --- | --- | --- | --- |"]
        for n, c in enumerate(data["items"], start=1):
            cell = lambda s: str(s).replace("|", "\\|").replace("\n", "<br>")
            out.append(f"| {n} | {cell(c['front'])} | {cell(c['back'])} | {cell(_cite_text(c))} |")
        return "\n".join(out) + "\n"

    key = []
    for n, q in enumerate(data["items"], start=1):
        out.append(f"**{n}. {q['question']}**")
        out.append("")
        t = q["type"]
        if t in ("mcq", "multi"):
            out += [f"- {'ABCDEFGHIJ'[i]}. {o}" for i, o in enumerate(q["options"])]
            idx = q["answer"] if isinstance(q["answer"], list) else [q["answer"]]
            ans = ", ".join("ABCDEFGHIJ"[i] for i in idx)
        elif t == "true_false":
            out.append("- True / False")
            ans = "True" if q["answer"] else "False"
        else:
            out.append("_Short answer._")
            ans = q["answer"]
        out.append("")
        expl = f" — {q['explanation']}" if q.get("explanation") else ""
        if "\n" in str(ans):
            # Keep multi-line answers (code, steps) intact inside the numbered list.
            body = str(ans).strip("\n")
            block = body if body.lstrip().startswith("```") else f"```\n{body}\n```"
            block = "\n".join("   " + ln if ln else "" for ln in block.splitlines())
            key.append(f"{n}. _Model answer:_{expl} _({_cite_text(q)})_\n\n{block}\n")
        else:
            key.append(f"{n}. **{ans}**{expl} _({_cite_text(q)})_")
    out += ["---", "", "## Answer key", "", *key]
    return "\n".join(out) + "\n"


def to_html(data: dict) -> str:
    template = resources.files("eztudy").joinpath("templates/player.html").read_text()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")
    return (
        template.replace("__EZTUDY_TITLE__", html.escape(data["title"]))
        .replace("/*__EZTUDY_DATA__*/null", payload)
    )


def render(path: Path, known_cids: set[str] | None = None) -> tuple[Path, Path, list[str]]:
    """Validate and write .md + .html. Returns (md, html, warnings); warnings need `known_cids`."""
    data = load(path)
    warns = unknown_citations(data, known_cids) if known_cids is not None else []
    md_path, html_path = path.with_suffix(".md"), path.with_suffix(".html")
    md_path.write_text(to_markdown(data))
    html_path.write_text(to_html(data))
    return md_path, html_path, warns
