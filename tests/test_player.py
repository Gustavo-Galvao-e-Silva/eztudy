import json
import re
from importlib import resources

import pytest

from eztudy.cli import main
from eztudy.render import SKINS, StudyFormatError, to_html

QUIZ = {"type": "quiz", "title": "Q", "items": [
    {"type": "mcq", "question": "Pick", "options": ["a", "b"], "answer": 1, "citations": ["x"]}]}
CARDS = {"type": "flashcards", "title": "C", "items": [{"front": "f", "back": "b", "citations": ["x"]}]}

# (foreground, background, minimum ratio): text needs 4.5:1, UI borders/fills/icons 3:1 (WCAG AA).
PAIRS = [
    ("fg", "bg", 4.5), ("fg", "surface", 4.5), ("fg", "sunk", 4.5), ("fg", "sel", 4.5),
    ("muted", "bg", 4.5), ("muted", "surface", 4.5),
    ("accent-ink", "bg", 4.5), ("accent-ink", "surface", 4.5),
    ("on-good", "good", 4.5), ("on-bad", "bad", 4.5), ("on-btn", "btn", 4.5),
    ("good", "surface", 3), ("bad", "surface", 3), ("good", "bg", 3), ("bad", "bg", 3),
    ("line-strong", "bg", 3), ("line-strong", "surface", 3), ("accent-ink", "sel", 3),
]


def _skin_css(name):
    return resources.files("eztudy").joinpath("templates/player/skins", f"{name}.css").read_text()


def _tokens(css, selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"missing block {selector}"
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})\b", m.group(1)))


def _lum(hex_):
    def ch(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(hex_[i:i + 2]) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("skin", SKINS)
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_skin_contrast(skin, mode):
    css = _skin_css(skin)
    tokens = _tokens(css, f'[data-skin="{skin}"]')
    if mode == "dark":
        tokens = {**tokens, **_tokens(css, f'[data-skin="{skin}"][data-mode="dark"]')}
    failures = [f"{fg} on {bg}: {contrast(tokens[fg], tokens[bg]):.2f} < {need}"
                for fg, bg, need in PAIRS if contrast(tokens[fg], tokens[bg]) < need]
    assert not failures, f"{skin}/{mode}: " + "; ".join(failures)


SYNTAX = ["syn-keyword", "syn-string", "syn-number", "syn-comment", "syn-type", "syn-function",
          "syn-variable", "syn-operator", "syn-punct", "fg"]
# Code editor: syntax colours must read as text on every editor background; UI marks need 3:1.
EDITOR_PAIRS = (
    [(fg, bg, 4.5) for fg in SYNTAX for bg in ("ed-bg", "ed-active", "ed-sel")]
    + [("muted", "ed-gutter", 4.5), ("fg", "ed-gutter", 4.5), ("fg", "ed-active", 4.5),
       ("ed-bg", "ed-cursor", 4.5),  # Vim's block cursor shows the character in --ed-bg
       ("ed-cursor", "ed-bg", 3), ("accent-ink", "ed-bg", 3), ("bad", "ed-bg", 3), ("good", "ed-gutter", 3),
       ("fg", "surface", 4.5), ("muted", "surface", 4.5), ("fg", "sel", 4.5), ("accent-ink", "surface", 4.5)]
)


def _editor_tokens(skin, mode):
    """Tokens in effect inside a question card (where the editor lives), for one skin and mode."""
    css = _skin_css(skin)
    tokens = _tokens(css, f'[data-skin="{skin}"]')
    if mode == "dark":
        tokens = {**tokens, **_tokens(css, f'[data-skin="{skin}"][data-mode="dark"]')}
        card = re.search(re.escape(f'[data-skin="{skin}"][data-mode="dark"] .qbox') + r"[^{]*\{([^}]*)\}", css)
        if card:
            tokens = {**tokens, **dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})\b", card.group(1)))}
    return tokens


@pytest.mark.parametrize("skin", SKINS)
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_editor_contrast(skin, mode):
    tokens = _editor_tokens(skin, mode)
    missing = sorted({t for pair in EDITOR_PAIRS for t in pair[:2] if t not in tokens})
    assert not missing, f"{skin}/{mode}: missing editor tokens {missing}"
    failures = [f"{fg} on {bg}: {contrast(tokens[fg], tokens[bg]):.2f} < {need}"
                for fg, bg, need in EDITOR_PAIRS if contrast(tokens[fg], tokens[bg]) < need]
    assert not failures, f"{skin}/{mode}: " + "; ".join(failures)


def test_typewriter_night_cards_keep_contrast():
    css = _skin_css("typewriter")
    m = re.search(r'\.qbox,\s*\[data-skin="typewriter"\]\[data-mode="dark"\] \.fc-face\s*\{([^}]*)\}', css)
    card = dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})\b", m.group(1)))
    for fg, bg, need in [("fg", "surface", 4.5), ("muted", "surface", 4.5), ("on-btn", "btn", 4.5),
                         ("on-good", "good", 4.5), ("on-bad", "bad", 4.5), ("accent-ink", "surface", 4.5)]:
        assert contrast(card[fg], card[bg]) >= need, (fg, bg)


@pytest.mark.parametrize("data", [QUIZ, CARDS])
def test_player_is_offline_click_only_and_small(data):
    page = to_html(data)
    assert 'data-skin="focus"' in page
    assert all(f'[data-skin="{s}"]' in page for s in SKINS)
    assert not re.search(r"<link|<script[^>]+src=|@import|url\(\s*['\"]?https?:", page)  # no network
    assert not re.search(r"keydown|keyup|keypress", page)  # click-only
    assert "/*__EZTUDY" not in page and "__EZTUDY_" not in page
    assert len(page.encode()) < 150_000  # served-mode grading (~7 KB) and checked item types (~13 KB)


def test_theme_selection(notebook, capsys):
    assert 'data-skin="terminal"' in to_html(QUIZ, "terminal")
    with pytest.raises(StudyFormatError):
        to_html(QUIZ, "neon")
    p = notebook / "q.json"
    p.write_text(json.dumps(QUIZ))
    assert main(["-C", str(notebook), "render", str(p), "--theme", "system7"]) == 0
    assert 'data-skin="system7"' in p.with_suffix(".html").read_text()
    (notebook / ".eztudy").mkdir(exist_ok=True)
    (notebook / ".eztudy" / "config.toml").write_text('[ui]\ntheme = "typewriter"\n')
    assert main(["-C", str(notebook), "render", str(p)]) == 0
    assert 'data-skin="typewriter"' in p.with_suffix(".html").read_text()
    (notebook / ".eztudy" / "config.toml").write_text('[ui]\ntheme = "neon"\n')
    assert main(["-C", str(notebook), "render", str(p)]) == 2
