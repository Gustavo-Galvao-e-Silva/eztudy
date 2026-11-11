import hashlib
import json
import re
import shutil
import subprocess
from importlib import resources
from pathlib import Path

import pytest

from eztudy.render import LANG_ALIASES, code_langs, editor_lang, to_html, to_markdown, validate

REPO = Path(__file__).resolve().parents[1]
EDITOR = REPO / "editor"
VENDOR = resources.files("eztudy").joinpath("templates/player/vendor")


def code_item(**kw):
    return {"id": "c1", "type": "code", "language": "java", "question": "Write remove()",
            "answer": "public T remove() {\n    return null;\n}", "citations": ["x"], **kw}


def quiz(*items):
    return {"type": "quiz", "title": "Code", "items": list(items)}


MCQ = {"type": "mcq", "question": "Pick", "options": ["a", "b"], "answer": 1, "citations": ["x"]}


def test_valid_code_item():
    item = code_item(starter="public T remove() {\n    $0\n}",
                     context={"identifiers": ["size", {"name": "downHeap", "kind": "method", "detail": "(int i)"}]},
                     rubric=[{"id": "r1", "text": "Handles empty heap", "points": 2, "match": r"NoSuchElement\w+"}])
    assert validate(quiz(item)) == []


@pytest.mark.parametrize("patch, msg", [
    ({"answer": ""}, "model solution"),
    ({"language": 3}, "`language` must be a string"),
    ({"starter": ["x"]}, "`starter` must be a string"),
    ({"context": {"identifiers": [{"kind": "field"}]}}, "`context`"),
    ({"context": ["size"]}, "`context`"),
    ({"rubric": "all of it"}, "`rubric` must be a list"),
    ({"rubric": [{"points": 1}]}, "needs a `text`"),
    ({"rubric": [{"text": "x", "points": "two"}]}, "`points` must be a number"),
    ({"rubric": [{"text": "x", "match": "(unclosed"}]}, "not a valid regex"),
])
def test_invalid_code_items(patch, msg):
    errs = validate(quiz(code_item(**patch)))
    assert any(msg in e for e in errs), errs


def test_language_aliases_and_unknown():
    assert editor_lang("Java") == "java"
    assert editor_lang("c++") == "cpp" and editor_lang("C") == "cpp"
    assert editor_lang("tsx") == "javascript" and editor_lang("postgresql") == "sql"
    assert editor_lang("haskell") == "plain" and editor_lang(None) == "plain"


def test_aliases_match_the_editor_bundle():
    src = (EDITOR / "src" / "editor.js").read_text()
    block = re.search(r"const ALIASES = \{(.*?)\n\};", src, re.S).group(1)
    js = dict(re.findall(r'"?([\w+]+)"?:\s*"([\w:]+)"', block))
    assert js == LANG_ALIASES


def test_vendor_only_for_code_quizzes_and_only_needed_languages():
    plain = to_html(quiz(MCQ))
    assert '".cm-scroller":{' not in plain and len(plain.encode()) < 150_000
    assert not re.search(r"keydown|keyup|keypress", plain)
    assert code_langs(quiz(MCQ)) == []
    data = quiz(MCQ, code_item(), code_item(id="c2", language="py"), code_item(id="c3", language="Java"), code_item(id="c4", language="lisp"))
    assert code_langs(data) == ["java", "plain", "python"]
    page = to_html(data)
    assert page.count('".cm-scroller":{') == 1  # core inlined exactly once
    assert "EZCM.langs.java" in page and "EZCM.langs.python" in page
    assert "EZCM.langs.cpp" not in page and "EZCM.langs.rust" not in page
    assert "<!--__EZTUDY_VENDOR__-->" not in page
    assert not re.search(r"<link|<script[^>]+src=|@import|url\(\s*['\"]?https?:", page)  # still offline


def test_player_code_never_adds_key_listeners():
    app = resources.files("eztudy").joinpath("templates/player/app.js").read_text()
    assert not re.search(r"keydown|keyup|keypress|addEventListener\(\s*['\"]key", app)


def test_markdown_for_code_items():
    md = to_markdown(quiz(code_item(starter="class A {\n  $0\n}", rubric=[{"text": "Returns null", "points": 1}])))
    assert "```java\nclass A {" in md and "$0" not in md
    assert "Rubric:" in md and "- Returns null (1 pt)" in md


def _source_hash():
    """Same algorithm as editor/build.mjs sourceHash()."""
    files = ["build.mjs", "package-lock.json"] + sorted(
        p.relative_to(EDITOR).as_posix() for p in (EDITOR / "src").rglob("*") if p.is_file())
    h = hashlib.sha256()
    for f in sorted(files):
        h.update(f.encode() + b"\0")
        h.update((EDITOR / f).read_bytes())
        h.update(b"\0")
    return h.hexdigest()[:16]


@pytest.mark.skipif(not (EDITOR / "build.mjs").exists(), reason="editor sources not present (installed package)")
def test_vendored_editor_is_built_from_current_sources():
    sizes = json.loads(VENDOR.joinpath("sizes.json").read_text())
    assert sizes["source_hash"] == _source_hash(), "editor/ changed: run `cd editor && npm run build` and commit vendor/"
    for f in ["cm-core.js"] + [f"cm-lang-{x}.js" for x in ("cpp", "go", "java", "javascript", "python", "rust", "sql")]:
        assert VENDOR.joinpath(f).is_file(), f
        assert sizes["files"][f]["raw"] == len(VENDOR.joinpath(f).read_bytes())
    assert sizes["files"]["cm-core.js"]["gzip"] < 260_000  # budget: core + vim + autocomplete + lint


@pytest.mark.skipif(shutil.which("node") is None or not (EDITOR / "test" / "run.mjs").exists(), reason="node not available")
def test_editor_lint_and_completions():
    r = subprocess.run(["node", "test/run.mjs"], cwd=EDITOR, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
