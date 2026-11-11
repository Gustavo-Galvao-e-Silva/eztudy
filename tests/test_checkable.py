"""Exactly-checked quiz item types: numeric, cloze, ordering, matching (graded in the player by checks.js)."""
import shutil
import subprocess
from pathlib import Path

import pytest

from eztudy.render import to_html, to_markdown, validate

ROOT = Path(__file__).resolve().parent.parent
CITE = {"citations": ["notes.md line 1"]}
GOOD = [
    {"type": "numeric", "question": "g?", "answer": 9.81, "tolerance": 0.05, "unit": "m/s²", **CITE},
    {"type": "numeric", "question": "n?", "answer": 200, "tolerance": "2%", **CITE},
    {"type": "cloze", "question": "Fill.", "text": "ATP in the ___ by ___.",
     "answer": [["mitochondria", "mitochondrion"], {"accept": ["OXPHOS"], "regex": "ox ?phos", "case_sensitive": False}], **CITE},
    {"type": "cloze", "question": "Code.", "text": "for i in ___(n):\n    print(i)", "answer": ["range"], "monospace": True, **CITE},
    {"type": "ordering", "question": "Order.", "answer": ["Prophase", "Metaphase", "Anaphase", "Telophase"], **CITE},
    {"type": "matching", "question": "Match.", "answer": [["Mito", "ATP"], ["Chloro", "ATP"], ["Ribo", "Proteins"]],
     "distractors": ["Lipids"], **CITE},
]


def quiz(*items):
    return {"type": "quiz", "title": "T", "items": list(items)}


def test_valid_checked_items():
    assert validate(quiz(*GOOD)) == []


@pytest.mark.parametrize("item, msg", [
    ({"type": "numeric", "answer": "9.8"}, "must be a number"),
    ({"type": "numeric", "answer": True}, "must be a number"),
    ({"type": "numeric", "answer": 1, "tolerance": -1}, "tolerance"),
    ({"type": "numeric", "answer": 1, "tolerance": "two%"}, "tolerance"),
    ({"type": "cloze", "text": "no blanks", "answer": ["x"]}, "one `___` per blank"),
    ({"type": "cloze", "text": "a ___ b ___", "answer": ["x"]}, "has 2 blanks but `answer` has 1"),
    ({"type": "cloze", "text": "a ___", "answer": [{"accept": []}]}, "blank 1"),
    ({"type": "cloze", "text": "a ___", "answer": [{"accept": ["x"], "regex": "("}]}, "not valid"),
    ({"type": "ordering", "answer": ["only"]}, "2 to 10"),
    ({"type": "ordering", "answer": list("abcdefghijk")}, "2 to 10"),
    ({"type": "ordering", "answer": ["a", "a"]}, "unique"),
    ({"type": "matching", "answer": [["a", "b"]]}, "at least 2 pairs"),
    ({"type": "matching", "answer": [["a", "b"], ["a", "c"]]}, "left-hand items must be unique"),
    ({"type": "matching", "answer": [["a", "b"], ["c", "d"]], "distractors": "x"}, "distractors"),
])
def test_invalid_checked_items(item, msg):
    errs = validate(quiz({"question": "q", **CITE, **item}))
    assert any(msg in e for e in errs), errs


def test_markdown_has_questions_and_key():
    md = to_markdown(quiz(*GOOD))
    question, key = md.split("## Answer key")
    assert "_Number in m/s²._" in question and "ATP in the \\_\\_\\_\\_\\_ by" in question
    assert "mitochondria" not in question and "for i in _____(n):" in question
    assert "**9.81 m/s² (± 0.05)**" in key and "[mitochondria / mitochondrion]" in key and "[OXPHOS]" in key
    assert "**Prophase → Metaphase → Anaphase → Telophase**" in key and "Ribo → Proteins" in key
    assert "Lipids" in question  # distractor offered as an option


def test_player_includes_checks_once():
    page = to_html(quiz(*GOOD))
    assert page.count("function checkCloze(") + page.count("const checkCloze =") == 1
    assert "renderChecked" in page


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_answer_checks_in_node():
    r = subprocess.run(["node", "tests/checks.test.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_option_shuffle_flags_and_player():
    from eztudy.render import validate

    item = {"id": "q1", "type": "mcq", "question": "?", "options": ["a", "b"], "answer": 0, "citations": ["c"]}
    assert validate({"type": "quiz", "title": "Q", "items": [{**item, "shuffle": False}]}) == []
    assert any("`shuffle`" in e for e in validate({"type": "quiz", "title": "Q", "items": [{**item, "shuffle": "no"}]}))
    assert any("`shuffle_options`" in e for e in validate({"type": "quiz", "title": "Q", "shuffle_options": 0, "items": [item]}))
    page = to_html({"type": "quiz", "title": "Q", "items": [item]})
    assert "function optionOrder" in page and "st.perm ||=" in page
