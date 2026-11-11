"""Validate study JSON (quiz / flashcards) and render it to Markdown + standalone HTML."""

from __future__ import annotations

import html
import json
import os
import re
from importlib import resources
from pathlib import Path

QUIZ_TYPES = {"mcq", "multi", "true_false", "short", "code", "numeric", "cloze", "ordering", "matching"}
CHECKED_TYPES = {"numeric", "cloze", "ordering", "matching"}  # graded exactly in the player (templates/player/checks.js)
BLANK = "___"

# `language` of a code item -> editor language pack ("id" or "id:dialect"). Mirrors ALIASES in
# editor/src/editor.js; anything else is edited as plain text (still with completions from context).
LANG_ALIASES = {
    "java": "java", "python": "python", "py": "python", "python3": "python",
    "c": "cpp", "c++": "cpp", "cpp": "cpp", "cc": "cpp", "cxx": "cpp", "h": "cpp", "hpp": "cpp",
    "javascript": "javascript", "js": "javascript", "jsx": "javascript:jsx", "mjs": "javascript", "node": "javascript",
    "typescript": "javascript:ts", "ts": "javascript:ts", "tsx": "javascript:tsx",
    "sql": "sql", "postgres": "sql:postgresql", "postgresql": "sql:postgresql", "mysql": "sql:mysql", "sqlite": "sql:sqlite",
    "go": "go", "golang": "go", "rust": "rust", "rs": "rust",
}


def editor_lang(language) -> str:
    """Language pack id for a code item's `language` ("plain" when unknown or missing)."""
    return LANG_ALIASES.get(str(language or "").strip().lower(), "plain").split(":")[0]


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
    seen_ids: set[str] = set()
    for n, it in enumerate(items, start=1):
        where = f"item {n}" + (f" ({it.get('id')})" if isinstance(it, dict) and it.get("id") else "")
        if not isinstance(it, dict):
            errs.append(f"{where}: must be an object")
            continue
        iid = it.get("id")
        if iid is not None and not (isinstance(iid, str) and iid.strip()):
            errs.append(f"{where}: `id` must be a non-empty string")
        elif iid in seen_ids:
            errs.append(f"{where}: duplicate `id` {iid!r} (ids key the review schedule, so each must be unique)")
        elif iid:
            seen_ids.add(iid)
        src = it.get("src")
        if src is not None and not (isinstance(src, dict) and all(isinstance(src.get(k), str) and src[k] for k in ("deck", "id"))):
            errs.append(f"{where}: `src` must be {{\"deck\": str, \"id\": str}} (the item a review deck copied)")
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
        elif t == "code":
            errs += [f"{where}: {e}" for e in _code_errors(it)]
        elif t in CHECKED_TYPES:
            errs += [f"{where}: {e}" for e in _checked_errors(it, t)]
    return errs


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _strings(xs, n_min: int = 1) -> bool:
    return isinstance(xs, list) and len(xs) >= n_min and all(isinstance(x, str) and x.strip() for x in xs)


def _checked_errors(it: dict, t: str) -> list[str]:
    ans = it.get("answer")
    if t == "numeric":
        errs = [] if _is_num(ans) else ["numeric `answer` must be a number"]
        tol = it.get("tolerance")
        if tol is not None and not ((_is_num(tol) and tol >= 0) or (isinstance(tol, str) and re.fullmatch(r"\s*\d+(\.\d+)?\s*%\s*", tol))):
            errs.append('`tolerance` must be a number >= 0 or a percentage like "2%"')
        if "unit" in it and not isinstance(it["unit"], str):
            errs.append("`unit` must be a string")
        return errs
    if t == "cloze":
        text = it.get("text")
        if not isinstance(text, str) or BLANK not in text:
            return [f"cloze `text` must be a passage with one `{BLANK}` per blank"]
        if not isinstance(ans, list) or not ans:
            return ["cloze `answer` must list the accepted answer(s) for each blank"]
        errs = []
        if text.count(BLANK) != len(ans):
            errs.append(f"cloze `text` has {text.count(BLANK)} blanks but `answer` has {len(ans)} entries")
        for k, b in enumerate(ans, start=1):
            spec = {"accept": [b]} if isinstance(b, str) else {"accept": b} if isinstance(b, list) else b
            if not isinstance(spec, dict) or not _strings(spec.get("accept")):
                errs.append(f"blank {k}: give a string, a list of strings, or {{\"accept\": [...], \"regex\"?: ...}}")
                continue
            if "regex" in spec:
                try:
                    re.compile(spec["regex"])
                except (re.error, TypeError) as e:
                    errs.append(f"blank {k}: `regex` is not valid: {e}")
        return errs
    if t == "ordering":
        if not _strings(ans, 2) or len(ans) > 10:
            return ["ordering `answer` must be the correct order: 2 to 10 strings"]
        return [] if len(set(ans)) == len(ans) else ["ordering `answer` entries must be unique"]
    # matching
    if not isinstance(ans, list) or len(ans) < 2 or not all(isinstance(p, list) and len(p) == 2 and _strings(p, 2) for p in ans):
        return ['matching `answer` must be at least 2 pairs: [["left", "right"], ...]']
    errs = [] if len({p[0] for p in ans}) == len(ans) else ["matching left-hand items must be unique"]
    if "distractors" in it and not (isinstance(it["distractors"], list) and all(isinstance(d, str) and d.strip() for d in it["distractors"])):
        errs.append("`distractors` must be a list of strings")
    return errs


def _code_errors(it: dict) -> list[str]:
    errs = []
    if not (isinstance(it.get("answer"), str) and it["answer"].strip()):
        errs.append("code `answer` must be a non-empty model solution string")
    for k in ("language", "starter"):
        if k in it and not isinstance(it[k], str):
            errs.append(f"`{k}` must be a string")
    ctx = it.get("context")
    if ctx is not None:
        ids = ctx.get("identifiers") if isinstance(ctx, dict) else None
        if not isinstance(ctx, dict) or not isinstance(ids, list) or not all(
                isinstance(i, str) or (isinstance(i, dict) and isinstance(i.get("name"), str)) for i in ids):
            errs.append("`context` must be {\"identifiers\": [name or {\"name\", \"kind\"?, \"detail\"?}, ...]}")
    rubric = it.get("rubric")
    if rubric is not None:
        if not isinstance(rubric, list):
            return errs + ["`rubric` must be a list of criteria"]
        for k, c in enumerate(rubric, start=1):
            if not isinstance(c, dict) or not isinstance(c.get("text"), str) or not c["text"].strip():
                errs.append(f"rubric {k}: needs a `text`")
                continue
            if "points" in c and (isinstance(c["points"], bool) or not isinstance(c["points"], (int, float))):
                errs.append(f"rubric {k}: `points` must be a number")
            if "match" in c:
                try:
                    re.compile(c["match"])
                except (re.error, TypeError) as e:
                    errs.append(f"rubric {k}: `match` is not a valid regex: {e}")
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


def id_warnings(data: dict) -> list[str]:
    """Items without an `id` are tracked by position, so reordering the deck mixes up their history."""
    missing = [str(n) for n, it in enumerate(data.get("items") or [], start=1) if isinstance(it, dict) and not it.get("id")]
    if not missing:
        return []
    return [f"item(s) {', '.join(missing[:10])}{' …' if len(missing) > 10 else ''} have no `id`; add stable ids so "
            "progress and the review schedule follow each item when the deck is edited"]


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


def _blank_answers(b) -> str:
    accept = [b] if isinstance(b, str) else b if isinstance(b, list) else b.get("accept", [])
    return " / ".join(accept)


def _cloze_md(text: str, fills: list[str], monospace=False) -> str:
    filled = "".join(p + (fills[k] if k < len(fills) else "") for k, p in enumerate(text.split(BLANK)))
    return f"```\n{filled.strip(chr(10))}\n```" if monospace else filled


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
        elif t == "code":
            lang = q.get("language", "")
            starter = (q.get("starter") or "").replace("$0", "")
            out += [f"_Write code ({lang or 'any language'})._", ""]
            if starter.strip():
                out += [f"```{lang}", starter.strip("\n"), "```"]
            ans = f"```{lang}\n{q['answer'].strip(chr(10))}\n```"
            if q.get("rubric"):
                ans += "\n\nRubric:\n" + "\n".join(
                    f"- {c['text']}" + (f" ({c['points']} pt)" if "points" in c else "") for c in q["rubric"])
        elif t == "numeric":
            tol = q.get("tolerance")
            out.append("_Number" + (f" in {q['unit']}" if q.get("unit") else "") + "._")
            ans = f"{q['answer']}" + (f" {q['unit']}" if q.get("unit") else "") + (f" (± {tol})" if tol is not None else "")
        elif t == "cloze":
            mono = q.get("monospace")
            out += [_cloze_md(q["text"], ["_____" if mono else "\\_" * 5] * len(q["answer"]), mono)]
            ans = _cloze_md(q["text"], [f"[{_blank_answers(b)}]" for b in q["answer"]], mono)
        elif t == "ordering":
            out += [f"- {x}" for x in sorted(q["answer"])]
            ans = " → ".join(q["answer"])
        elif t == "matching":
            rights = sorted({r for _, r in q["answer"]} | set(q.get("distractors") or []))
            out += [f"- {left}" for left, _ in q["answer"]] + ["", "_Options:_ " + " · ".join(rights)]
            ans = "; ".join(f"{left} → {right}" for left, right in q["answer"])
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


SKINS = ("focus", "editorial", "terminal", "system7", "typewriter")
DEFAULT_SKIN = "focus"


def _player(name: str) -> str:
    return resources.files("eztudy").joinpath("templates/player", name).read_text()


def code_langs(data: dict) -> list[str]:
    """Editor language packs a quiz needs (empty when it has no code items: no editor bytes)."""
    if data.get("type") != "quiz":
        return []
    langs = {editor_lang(it.get("language")) for it in data["items"] if isinstance(it, dict) and it.get("type") == "code"}
    return sorted(langs)


def _vendor(langs: list[str]) -> str:
    if not langs:
        return ""
    files = ["cm-core.js"] + [f"cm-lang-{lang}.js" for lang in langs if lang != "plain"]
    js = "\n".join(_player(f"vendor/{f}") for f in files)
    if re.search(r"</script|<!--", js, re.I):
        raise StudyFormatError("vendored editor contains a sequence that would end the <script> tag; rebuild it")
    return f"<script>\n{js}\n</script>"


def to_html(data: dict, skin: str | None = None, links: dict | None = None) -> str:
    """One self-contained offline page: base layout + every skin (switchable in the page) + the app.
    Quizzes with `code` items also inline the CodeMirror editor and only the language packs they use.
    `links` ({"base": relative URL of sources/, "map": sourcelinks.links(...)}) makes citations clickable."""
    skin = skin or DEFAULT_SKIN
    if skin not in SKINS:
        raise StudyFormatError(f"unknown theme {skin!r}; choose one of {', '.join(SKINS)}")
    css = "\n".join([_player("base.css")] + [_player(f"skins/{s}.css") for s in SKINS])
    payload = _script_json(data)
    page = (
        _player("shell.html")
        .replace("__EZTUDY_SKIN__", skin)
        .replace("__EZTUDY_TITLE__", html.escape(data["title"]))
        .replace("/*__EZTUDY_CSS__*/", css)
        .replace("<!--__EZTUDY_VENDOR__-->", _vendor(code_langs(data)))
        .replace("/*__EZTUDY_JS__*/", _player("checks.js") + "\n" + _player("app.js"))
        .replace("/*__EZTUDY_DATA__*/null", payload)
    )
    if links and links.get("map"):
        page = page.replace("<script>", f"<script>window.EZTUDY_LINKS = {_script_json(links)};</script>\n<script>", 1)
    return page


def offline_links(ws, data: dict, html_path: Path) -> dict:
    from .sourcelinks import links

    base = Path(os.path.relpath(ws.sources.resolve(), html_path.parent.resolve())).as_posix().rstrip("/") + "/"
    return {"base": base, "map": links(ws, data)}


def _script_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")


def render(path: Path, known_cids: set[str] | None = None, skin: str | None = None, ws=None) -> tuple[Path, Path, list[str]]:
    """Validate and write .md + .html. Returns (md, html, warnings); citation checks need `known_cids`.
    With the notebook `ws`, citations in the page link to their source files (relative, so it works offline)."""
    data = load(path)
    warns = id_warnings(data) + (unknown_citations(data, known_cids) if known_cids is not None else [])
    md_path, html_path = path.with_suffix(".md"), path.with_suffix(".html")
    md_path.write_text(to_markdown(data))
    html_path.write_text(to_html(data, skin, offline_links(ws, data, html_path) if ws else None))
    return md_path, html_path, warns
