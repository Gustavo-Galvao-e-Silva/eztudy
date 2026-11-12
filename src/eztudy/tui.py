"""`eztudy tui`: the dashboard (insights.py, drawn with dash.py's panels) as a live Textual app.

Meant for a terminal pane beside Claude Code: it refreshes on its own when a quiz finishes or grading lands.
Keys: enter acts on the selected recommendation or deck, r reviews what's due, d lists due items, q quits.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import DataTable, Footer, OptionList, Static
from textual.widgets.option_list import Option

from . import dash, insights, srs
from .workspace import Workspace

REFRESH_S = 2.0

# panchi: peach #FFB592, brown #805B49, warm grey #8F8984, charcoal #45423F (status colours derived to match).
THEMES = [
    Theme(name="panchi", primary="#FFB592", secondary="#805B49", accent="#FFB592", foreground="#EDE6E1",
          background="#2A2826", surface="#34312F", panel="#45423F", warning="#F2C48D", error="#E07A5F",
          success="#B5C99A", dark=True),
    Theme(name="panchi-light", primary="#805B49", secondary="#8F8984", accent="#805B49", foreground="#45423F",
          background="#FAF6F3", surface="#F2EBE6", panel="#E8DFD8", warning="#A8722A", error="#B5523B",
          success="#5E7A4A", dark=False),
]


def cli_command(ws: Workspace, *args: str) -> list[str]:
    return [sys.executable, "-m", "eztudy.cli", "-C", str(ws.root), *args]


def _signature(ws: Workspace) -> tuple:
    """Changes when reports, grading state or study files change (cheap: directory listings and mtimes)."""
    sig = []
    for d in (ws.state / "progress" / "reports", ws.state / "progress" / "grading", ws.study):
        try:
            sig.append((d.stat().st_mtime_ns, sum(p.stat().st_mtime_ns for p in d.iterdir())))
        except OSError:
            sig.append(None)
    return tuple(sig)


class DueScreen(ModalScreen):
    BINDINGS = [Binding("escape,d,q", "dismiss", "Close")]
    DEFAULT_CSS = """
    DueScreen { align: center middle; }
    DueScreen > VerticalScroll { width: 90%; height: 80%; border: round $accent; background: $surface; padding: 0 1; }
    """

    def __init__(self, ws: Workspace):
        super().__init__()
        self.ws = ws

    def compose(self) -> ComposeResult:
        from . import progress as prog

        retention, max_days = srs.settings(self.ws.config)
        sched = srs.schedule(prog.load_all(self.ws), retention=retention, max_interval=max_days)
        table = DataTable(zebra_stripes=True, cursor_type="row")
        table.add_columns("when", "recall", "kind", "item", "prompt")
        for c in srs.due(sched, within_days=7):
            d = c["overdue_days"]
            when = (f"{d * 24:.0f}h" if abs(d) < 1 else f"{abs(d):.0f}d") + (" overdue" if d >= 0 else "")
            table.add_row(Text(when if d >= 0 else "in " + when, style=dash.S("warn") if d >= 0 else dash.S("muted")),
                          f"{c['retrievability']:.0%}", "card" if c["kind"] == "flashcards" else "quiz",
                          f"{c['deck']} / {c['id']}", c["prompt"][:70])
        with VerticalScroll():
            yield Static(Text("Due now and over the next 7 days (esc to close)", style="bold"))
            yield table


class Dashboard(App):
    TITLE = "eztudy"
    CSS = """
    Screen { layout: vertical; }
    #header { height: auto; padding: 0 1; }
    #main { height: 1fr; }
    #left, #right { width: 1fr; height: 100%; }
    #recs { height: auto; max-height: 60%; border: round $accent; border-title-color: $accent; }
    #recs > .option-list--option { padding: 0 1; }
    #decks { height: auto; max-height: 12; border: round $primary-darken-1; }
    .panel { height: auto; }
    #hint { height: 1; padding: 0 1; color: $text-muted; }
    """
    BINDINGS = [
        Binding("r", "review", "Review due"),
        Binding("d", "due", "Due list"),
        Binding("tab", "focus_next", "Switch list", show=False),
        Binding("g", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, ws: Workspace, theme: str | None = None):
        super().__init__()
        self.ws = ws
        self.info: dict = {}
        self.sig: tuple | None = None
        for t in THEMES:
            self.register_theme(t)
        self.start_theme = theme

    def compose(self) -> ComposeResult:
        yield Static(id="header")
        with Horizontal(id="main"):
            with VerticalScroll(id="left"):
                yield OptionList(id="recs")
                yield Static(classes="panel", id="missing")
            with VerticalScroll(id="right"):
                yield Static(classes="panel", id="mastery")
                yield Static(classes="panel", id="recent")
        yield DataTable(id="decks", cursor_type="row", zebra_stripes=True)
        yield Static(id="hint")
        yield Footer()

    def on_mount(self) -> None:
        if self.start_theme in self.available_themes:
            self.theme = self.start_theme
        elif self.start_theme:
            self.notify(f"Unknown theme {self.start_theme!r}; pick one with ctrl+p → Change theme", severity="warning")
        dash.set_palette(self.theme)
        # Panels are Rich renderables coloured by dash's palette: repaint them when the theme changes (ctrl+p).
        self.theme_changed_signal.subscribe(self, lambda theme: (dash.set_palette(theme.name), self.load()))
        self.query_one("#recs", OptionList).border_title = "Next up · enter to act"
        self.query_one("#decks", DataTable).border_title = "Decks · enter to open"
        self.load()
        self.set_interval(REFRESH_S, self.poll)

    # --- data ---------------------------------------------------------------------------

    def poll(self) -> None:
        if _signature(self.ws) != self.sig:
            self.load()

    def load(self) -> None:
        self.sig = _signature(self.ws)
        self.info = insights.build(self.ws)
        info = self.info
        self.query_one("#header", Static).update(dash.header(info))
        recs = self.query_one("#recs", OptionList)
        keep = recs.highlighted
        recs.clear_options()
        if info["recommend"]:
            for n, r in enumerate(info["recommend"], start=1):
                recs.add_option(Option(Text.assemble((f"{n}. {r['topic']}\n", "bold"), (" · ".join(r["reasons"]) + "\n", dash.S("muted")),
                                                     ("→ " + r["action"], dash.S("action"))), id=f"rec-{n - 1}"))
            recs.highlighted = min(keep or 0, len(info["recommend"]) - 1)
        else:
            recs.add_option(Option(Text("Nothing pressing. Finish a quiz, or ask the agent for new material.", style=dash.S("muted")),
                                   disabled=True))
        miss = dash.missing(info)
        self.query_one("#missing", Static).update(miss or "")
        self.query_one("#mastery", Static).update(dash.mastery(info))
        self.query_one("#recent", Static).update(dash.recent(info))
        table = self.query_one("#decks", DataTable)
        row = table.cursor_row
        table.clear(columns=True)
        shown = [d for d in info.get("decks", []) if not d["review"]] + [d for d in info.get("decks", []) if d["review"]][:3]
        # Explicit width: auto-sizing after clear(columns=True) can collapse the column on a redraw.
        table.add_column("deck", width=max([4] + [min(48, len(d["title"])) for d in shown]))
        table.add_columns("kind", "items", "due", "last")
        for d in shown:
            last = f"{d['last_score']:.0%}" if d["last_score"] is not None else "—"
            table.add_row(d["title"], "cards" if d["kind"] == "flashcards" else "quiz", str(d["items"]),
                          Text(str(d["due"]), style=dash.S("warn", True)) if d["due"] else Text("0", style=dash.S("muted")), last, key=d["path"])
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))
        foot = dash.footer(info)
        self.query_one("#hint", Static).update(foot or Text(f"refreshes on its own · {self.ws.root}", style=dash.S("muted")))

    def action_refresh(self) -> None:
        self.load()
        self.notify("Refreshed", timeout=1.5)

    # --- actions ------------------------------------------------------------------------

    def open_page(self, rel: str) -> None:
        """`eztudy serve --open` in the background: reuses a running server or starts one; opens the browser."""
        subprocess.Popen(cli_command(self.ws, "serve", "--open", rel), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.notify(f"Opening {Path(rel).name} in your browser")

    @work(thread=True, exclusive=True)
    def run_review(self, topic: str | None = None) -> None:
        cmd = cli_command(self.ws, "review", *(["--topic", topic] if topic else []))
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        made = re.findall(r"^wrote (\S+\.json)", res.stdout, re.M)
        if made:
            self.call_from_thread(self.open_page, made[0])
        else:
            msg = (res.stdout.strip() or res.stderr.strip() or "nothing to review").splitlines()[-1]
            self.call_from_thread(self.notify, msg, severity="warning" if res.returncode else "information")

    def action_review(self) -> None:
        self.run_review()

    def action_due(self) -> None:
        self.push_screen(DueScreen(self.ws))

    @on(OptionList.OptionSelected, "#recs")
    def act_on_rec(self, event: OptionList.OptionSelected) -> None:
        if not event.option.id:
            return
        rec = self.info["recommend"][int(event.option.id.split("-")[1])]
        if rec["due"]:
            self.run_review(rec["topic"])
            return
        prompt = f"Make me a quiz on {rec['topic']} (eztudy: {', '.join(rec['reasons'])})"
        self.copy_to_clipboard(prompt)
        self.notify(f"Copied for Claude: “{prompt}”", timeout=5)

    @on(DataTable.RowSelected, "#decks")
    def open_deck(self, event: DataTable.RowSelected) -> None:
        self.open_page(str(event.row_key.value))


def run(ws: Workspace, theme: str | None = None) -> None:
    Dashboard(ws, theme).run()


def launch_command(ws: Workspace, theme: str | None = None) -> str:
    """A shell command that starts the TUI for this notebook from any terminal."""
    import shlex

    exe = os.environ.get("EZTUDY_BIN") or (sys.argv[0] if Path(sys.argv[0]).name == "eztudy" else None)
    base = [str(Path(exe).resolve())] if exe else [sys.executable, "-m", "eztudy.cli"]
    return shlex.join([*base, "-C", str(ws.root), "tui", *(["--theme", theme] if theme else [])])


def open_beside(ws: Workspace, theme: str | None = None) -> str:
    """Start the TUI next to the current terminal: a tmux split, else a new macOS Terminal window.
    Returns what happened, for the caller to print."""
    import shutil

    cmd = launch_command(ws, theme)
    if os.environ.get("TMUX") and shutil.which("tmux"):
        subprocess.run(["tmux", "split-window", "-h", "-l", "45%", cmd], check=True)
        return "opened in a tmux split to the right"
    if sys.platform == "darwin" and shutil.which("osascript"):
        script = f'tell application "Terminal" to do script "{cmd.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
        subprocess.run(["osascript", "-e", script, "-e", 'tell application "Terminal" to activate'], check=True,
                       capture_output=True)
        return "opened in a new Terminal window"
    return f"run this in another terminal:\n  {cmd}"
