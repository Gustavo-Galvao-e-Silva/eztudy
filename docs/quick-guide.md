# eztudy quick guide

How to use eztudy day to day. Installation is in the [README](../README.md#install).

## 1. Set up a notebook

```bash
mkdir -p ~/notebooks/biology/sources        # put PDFs, slides, docs, notes and code in sources/
cd ~/notebooks/biology && claude
> use eztudy: index my sources and build the wiki
```

To use the CLI in your own shell (the plugin only adds it to Claude's PATH), alias the checkout's wrapper:
`alias eztudy="$HOME/Projects/eztudy/bin/eztudy"`.

## 2. Practise

Ask the agent for material: *"make me a 15-question quiz on chapter 2"*, *"flashcards for the heaps lecture"*.
It writes the quiz, opens it in your browser through `eztudy serve` (localhost only), and waits to grade it.

In the quiz player:
- **Click an option, then Confirm.** Multiple-choice options are shuffled on every attempt.
- **Numeric, fill-in-the-blank, ordering and matching** questions are checked exactly, with partial marks shown.
- **Short and code answers** are graded when you finish (feedback + rubric marks, about 10 s).
  - The code editor has completions: **Tab** or **Enter** accepts one.
  - Vim keys are in the ⋯ menu.
- **Citations under an answer are links.** They open the source at the cited page (PDF) or lines (code and text).
- **Skins** (focus, editorial, terminal, system7, typewriter) and light/dark are in the ⋯ menu.

Results are saved to the notebook automatically. The next quiz targets what you missed.

## 3. Review what's due

Every answer feeds a spaced-repetition schedule: misses come back within a day, and each success pushes an item further out.

```bash
eztudy due            # what's due now, how overdue, estimated recall
eztudy review         # builds study/review/review-<date>.json from the due items (least remembered first)
```
Or just tell the agent *"review what's due"*. Review answers count toward the original questions.

## 4. See where you stand

| Want | Run |
|---|---|
| What to study next, mastery, misses, decks | `eztudy dash` (in Claude Code: `! eztudy dash`) |
| The agent to decide and act | ask *"what should I study?"* |
| A one-line summary in Claude Code's status bar | `eztudy statusline --install`, then restart Claude Code |
| A live dashboard beside Claude Code | `eztudy tui --open` (tmux split, else a new Terminal window) |

### The TUI

`eztudy tui` (or `--open` to start it beside the current terminal). It refreshes on its own as you finish quizzes.

| Key | Does |
|---|---|
| `enter` on a recommendation | review that topic (if items are due), else copy a quiz request to paste to Claude |
| `enter` on a deck | open it in the browser |
| `r` | review everything due |
| `d` | due list for the next 7 days |
| `g` / `q` | refresh / quit |
| `ctrl+p` → Change theme | switch theme (remembered for next time) |

**Themes:** `panchi`, `panchi-light`, or any Textual theme.
- The last one you picked is remembered for next time, in `~/.config/eztudy/prefs.json`.
- `eztudy tui --theme panchi` overrides it for one run.
- `[ui] tui_theme` in the notebook config is the default until you pick one.

## 5. Settings (`.eztudy/config.toml`, all optional)

```toml
[study]
syllabus = "topics.md"     # Markdown list of exam topics: unpractised ones get recommended
exam = 2026-12-10          # countdown in the dashboard and status line

[review]
retention = 0.9            # target recall (0.5–0.99); higher = more frequent reviews
max_interval_days = 365

[ui]
theme = "focus"            # quiz player skin
tui_theme = "panchi"       # dashboard theme until you pick one in the TUI

[grading]
model = "haiku"            # model for automatic grading; fallback = "none" turns it off
```

## Command cheat sheet

```text
eztudy status                 what changed; index, wiki, progress, reviews due
eztudy dash [--json]          dashboard
eztudy tui [--open|--theme]   live dashboard
eztudy due | review           spaced repetition
eztudy progress               mastery by topic + problem items
eztudy serve --open <page>    open a quiz/deck so results post back
eztudy search "query"         search your sources
eztudy statusline --install   Claude Code status line for this notebook
```
