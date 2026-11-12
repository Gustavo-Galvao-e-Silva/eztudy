"""`eztudy dash`: the insights (insights.py) drawn as Rich panels. Plain text when not a terminal."""

from __future__ import annotations

from datetime import datetime

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import srs

# Colour roles, so a theme can restyle every panel. `default` is the terminal's own ANSI colours; the TUI switches
# palettes with its Textual theme (tui.py), and `eztudy dash` uses `[ui] tui_theme` when it names one of these.
PALETTES = {
    "default": {"brand": "magenta", "action": "cyan", "good": "green", "warn": "yellow", "bad": "red",
                "muted": "dim", "empty": "dim", "frame": "", "title": ""},
    # panchi: peach #FFB592, brown #805B49, warm grey #8F8984, charcoal #45423F; status colours are muted warm
    # tones derived to sit with it (the palette has no red/green).
    "panchi": {"brand": "#FFB592", "action": "#FFB592", "good": "#B5C99A", "warn": "#F2C48D", "bad": "#E07A5F",
               "muted": "#8F8984", "empty": "#45423F", "frame": "#805B49", "title": "#FFB592"},
    "panchi-light": {"brand": "#805B49", "action": "#805B49", "good": "#5E7A4A", "warn": "#A8722A", "bad": "#B5523B",
                     "muted": "#8F8984", "empty": "#E6DED8", "frame": "#FFB592", "title": "#805B49"},
}
_palette = PALETTES["default"]


def set_palette(name: str | None) -> None:
    global _palette
    _palette = PALETTES.get(name or "default", PALETTES["default"])


def S(role: str, bold: bool = False) -> str:
    style = _palette[role]
    return f"bold {style}".strip() if bold else style


def title(text: str) -> Text | str:
    return Text(text, style=S("title", True)) if _palette["title"] else text


def status_style(status: str) -> str:
    return S({"weak": "bad", "learning": "warn", "strong": "good"}.get(status, "muted"))
SPARK = "▁▂▃▄▅▆▇█"
WIDE = 100


def bar(frac: float, width: int = 12, style: str | None = None) -> Text:
    full = round(max(0.0, min(1.0, frac)) * width)
    return Text("█" * full, style=style or S("action")) + Text("░" * (width - full), style=S("empty"))


def sparkline(values: list[float]) -> Text:
    out = Text()
    for v in values:
        out.append(SPARK[min(len(SPARK) - 1, int(v * (len(SPARK) - 1) + 0.5))],
                   style=S("good") if v >= 0.85 else S("warn") if v >= 0.6 else S("bad"))
    return out


def _when(ts: str | None) -> str:
    if not ts:
        return "—"
    t = srs.parse_time(ts).astimezone()
    today = datetime.now().astimezone().date()
    if t.date() == today:
        return t.strftime("today %H:%M")
    return t.strftime("%b %d")


def header(info: dict) -> Text:
    t = info["today"]
    out = Text.assemble(("eztudy", S("brand", True)), "  ", (info["notebook"], "bold"), "   ")
    if t["due_now"]:
        out.append(f"{t['due_now']} due now", style=S("warn", True))
        if t["due_tomorrow"]:
            out.append(f" (+{t['due_tomorrow']} tomorrow)", style=S("warn"))
    elif t["tracked"]:
        out.append("all caught up", style=S("good", True))
        if t["next_due"]:
            out.append(f", next {_when(t['next_due'])}", style=S("good"))
    out.append(f"   {t['sessions_7d']} sessions this week", style=S("muted"))
    if t["streak_days"]:
        out.append(f"   🔥 {t['streak_days']}-day streak", style="bold")
    if t["exam"]:
        d = t["exam"]["days_left"]
        out.append("   exam " + (f"in {d} days" if d > 1 else "tomorrow" if d == 1 else "today" if d == 0 else "passed"),
                   style=S("bad", True) if 0 <= d <= 7 else "bold")
    return out


def next_up(info: dict) -> Panel:
    recs = info["recommend"]
    if not recs:
        body = Text("Nothing pressing. Ask the agent for new material, or come back when reviews are due.", style=S("muted"))
    else:
        rows = Table.grid(padding=(0, 1))
        rows.add_column(width=2, style=S("brand", True))
        rows.add_column(ratio=1)
        for n, r in enumerate(recs, start=1):
            rows.add_row(f"{n}.", Group(Text(r["topic"], style="bold"), Text(" · ".join(r["reasons"]), style=S("muted")),
                                        Text("→ " + r["action"], style=S("action"))))
        body = rows
    return Panel(body, title=title("Next up"), title_align="left", border_style=S("brand"), box=box.ROUNDED)


def mastery(info: dict) -> Panel:
    topics = info["topics"]
    if not topics:
        return Panel(Text("No topics yet.", style=S("muted")), title=title("Mastery"), title_align="left", border_style=S("frame"), box=box.ROUNDED)
    t = Table.grid(padding=(0, 1))
    t.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
    t.add_column()
    t.add_column(justify="right", width=4)
    t.add_column(style=S("muted"), justify="right")
    for row in topics[:12]:
        style = status_style(row["status"])
        t.add_row(row["topic"], bar(row["mastery"], style=style), Text(f"{row['mastery']:.0%}", style=style), f"{row['seen']}×")
    if len(topics) > 12:
        t.add_row(Text(f"… {len(topics) - 12} more (eztudy progress)", style=S("muted")), "", "", "")
    return Panel(t, title=title("Mastery"), title_align="left", border_style=S("frame"), box=box.ROUNDED)


def missing(info: dict) -> Panel | None:
    ms = info["misconceptions"]
    if not ms:
        return None
    t = Table.grid(padding=(0, 1))
    t.add_column(ratio=1)
    for m in ms:
        line = Text(m["prompt"][:90] or f"{m['deck']} / {m['id']}")
        detail = Text(f"missed {m['misses']}/{m['attempts']}", style=S("bad"))
        if m["picked"]:
            detail.append(f" · picked {m['picked'][:40]}", style=S("muted"))
        if m["correct"]:
            detail.append(f" · answer {str(m['correct'])[:40]}", style=S("good"))
        t.add_row(Group(line, detail))
    return Panel(t, title=title("Still missing"), title_align="left", border_style=S("bad"), box=box.ROUNDED)


def recent(info: dict) -> Panel:
    t = info["today"]
    trend = info["trend"]
    body = Table.grid(padding=(0, 1))
    body.add_column(style=S("muted"))
    body.add_column()
    body.add_row("last scores", sparkline(trend) if trend else Text("—", style=S("muted")))
    if trend:
        body.add_row("latest", Text(f"{trend[-1]:.0%}", style="bold"))
    body.add_row("sessions", f"{t['sessions']} total · {t['sessions_7d']} this week")
    body.add_row("scheduled", f"{t['tracked']} items · {t['due_now']} due now")
    return Panel(body, title=title("Recent"), title_align="left", border_style=S("frame"), box=box.ROUNDED)


def deck_table(info: dict) -> Panel | None:
    ds = [d for d in info.get("decks", []) if not d["review"]][:10]
    if not ds:
        return None
    t = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False)
    t.add_column("deck", ratio=1, overflow="ellipsis", no_wrap=True)
    t.add_column("kind", style=S("muted"))
    t.add_column("items", justify="right")
    t.add_column("due", justify="right")
    t.add_column("last", justify="right")
    for d in ds:
        last = f"{d['last_score']:.0%}" if d["last_score"] is not None else "—"
        t.add_row(d["title"], "cards" if d["kind"] == "flashcards" else "quiz", str(d["items"]),
                  Text(str(d["due"]), style=S("warn", True)) if d["due"] else Text("0", style=S("muted")),
                  Text(last, style=S("muted") if d["last_score"] is None else ""))
    return Panel(t, title=title("Decks"), title_align="left", border_style=S("frame"), box=box.ROUNDED)


def footer(info: dict) -> Text | None:
    s = info.get("system")
    if not s:
        return None
    notes = []
    if s["grading"]["pending"]:
        notes.append(f"{s['grading']['pending']} answer(s) waiting to be graded (eztudy report wait)")
    if s["grading"]["failed"]:
        notes.append(f"{s['grading']['failed']} grading job(s) failed")
    if s["unimported"]:
        notes.append(f"{s['unimported']} saved report(s) not imported (eztudy report import)")
    if s["server"]:
        notes.append("server running: " + s["server"].split("?")[0])
    return Text("  ·  ".join(notes), style=S("muted")) if notes else None


def render(info: dict, console: Console | None = None) -> None:
    console = console or Console()
    console.print(header(info))
    if not info["today"]["sessions"]:
        console.print(Panel(Text.assemble(
            "No study sessions yet. Finish a quiz or flashcard deck in the player and this fills in:\n",
            ("what to study next, mastery by topic, what you keep missing, and when reviews are due.", S("muted"))),
            title=title("Welcome"), title_align="left", border_style=S("brand"), box=box.ROUNDED))
        if (d := deck_table(info)):
            console.print(d)
        return
    left = [next_up(info)] + [p for p in (missing(info),) if p]
    right = [mastery(info), recent(info)]
    if console.width >= WIDE:
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(ratio=1)
        grid.add_column(ratio=1)
        grid.add_row(Group(*left), Group(*right))
        console.print(grid)
    else:
        for p in left + right:
            console.print(p)
    if (d := deck_table(info)):
        console.print(d)
    if (f := footer(info)):
        console.print(f)
