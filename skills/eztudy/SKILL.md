---
name: eztudy
description: Local, open-source NotebookLM. Turns any folder with a `sources/` directory (PDF, DOCX, PPTX, Markdown, text, code) into a study notebook — keeps an agent-maintained wiki and a local SQLite vector index over the sources, answers questions with citations, and generates quizzes, flashcards, study guides, briefings, FAQs, glossaries, timelines, mind maps and audio-overview scripts. Use when the user wants to study, learn from, quiz themselves on, summarize, index, search, or ask questions about their own documents/notes/course material, or mentions eztudy, NotebookLM, a `sources/` folder, flashcards or quizzes from their files.
allowed-tools: Bash(eztudy *), Bash(${CLAUDE_SKILL_DIR}/../../bin/eztudy *)
---

# eztudy

A notebook is any directory that contains `sources/`. That is the only thing the user sets up.
You (the agent) do all the bookkeeping. Everything else is created lazily:

```
<notebook>/
  sources/     user material — you MAY reorganize it (see references/reorganizing.md)
  wiki/        mode 1: interlinked markdown knowledge base you write and maintain
  study/       generated study material (.json source of truth -> .md + .html)
  .eztudy/     machine state: manifest.json, text/ (extracted text), index.db, config.toml
```

## The CLI

`eztudy` is on PATH when this is installed as a plugin. If `eztudy` is not found, use
`${CLAUDE_SKILL_DIR}/../../bin/eztudy` instead. Dependencies install via `uv` on first run, which can take a minute.

```bash
eztudy status                      # ALWAYS first: pending changes, index + wiki health
eztudy sync                        # extract new/changed sources -> .eztudy/text, track moves/deletes
eztudy add ../dir [--as name] [--exclude 'a,*.zip'] [--dry-run]   # copy files in from elsewhere (skips IDE/build junk, tracks origin)
eztudy index [--rebuild]           # sync + chunk + embed into SQLite (fastembed, local)
eztudy search "query" [-k 8] [--mode hybrid|vector|fts] [--path bio/] [--full] [--json]
eztudy show <chunk-id> [--context 1]          # read a chunk (+ neighbours) e.g. 3fa9c2d1:12
eztudy show <source-path> [--pages 3-5]       # read a source's extracted text (PDF pages / PPTX slides)
eztudy show <code-file> --lines 340-375 | --symbol removeRecurse   # numbered source lines (exact line numbers)
eztudy sources [--json]            # list tracked sources with hash, size, title, status
eztudy coverage topics.md [--out wiki/coverage.md] [--json]   # syllabus list -> covered / partial / missing per topic
eztudy wiki init | lint [--fix] [--json] | log "ingest | Title" [--detail "..."]
eztudy wiki cite <path|cid>...     # ready-to-paste `sources:` frontmatter (path + hash)
eztudy render study/quizzes/x.json [...] [--strict] [--theme focus|editorial|terminal|system7|typewriter]
                                   # validate + write x.md and an offline, click-only x.html player
                                   # (`code` items get a real code editor with completions, lint, Vim keys);
                                   # warns on citation cids not in the index (--strict: exit 1)
eztudy serve --open study/quizzes/x.html   # serve study/ on localhost and open the page (idempotent; run in background)
eztudy report wait [--timeout S]   # block until a served quiz is finished: prints its grades, or a packet for you to grade (run in background)
eztudy report grade <session> -    # apply your verdicts (JSON on stdin); the student's page shows them at once
eztudy report import [files… | -]  # store performance reports the player saved (default: scan study/ + ~/Downloads)
eztudy progress [--deck ID] [--json]   # mastery by topic (weak/learning/strong) + problem items, from all reports
```

`search --json` prints a list of hits, best first:
```json
[{"cid": "3fa9c2d1:12", "path": "bio/cells.pdf", "title": "Cell Biology Notes", "type": "pdf",
  "heading": "Organelles > Mitochondria", "location": "pages 4-5", "score": 0.032258,
  "text": "…chunk text…", "citation": "bio/cells.pdf (pages 4-5)"}]
```
`type` is one of `pdf | docx | pptx | html | code | markdown | text`; `location` is `page N`, `pages N-M`,
`slide N`… or `""` when the source has no page/slide markers. Code is chunked per class/method with
`location` `lines N-M`, `heading` like `BST > removeRecurse`, and `citation` `hw2/BST.java:340-375 (removeRecurse)`:
cite code with that citation string. `score` is only comparable within one query.

The CLI finds the notebook by walking up from cwd to a dir containing `sources/`; pass `-C <dir>` otherwise.
Never read binary sources (PDF/DOCX/PPTX) directly — use `eztudy show <path>`; it is faster and has page markers.

## The two index modes

| | **Wiki** (`wiki/`) | **Vector** (`.eztudy/index.db`) |
|---|---|---|
| What | Pages *you* write: summaries, topics, entities, cross-links, citations | Chunks + local embeddings + FTS5 keyword index |
| Good for | Synthesis, structure, "explain X", coverage planning, contradictions | Exact facts, quotes, "where does it say…", big corpora |
| Cost | Your tokens, once per source (then incremental) | Seconds of local CPU, zero tokens |
| Maintain with | Ingest workflow + `wiki lint` | `eztudy index` (incremental, hash-based) |

Pick by situation:
- **Always** keep the vector index current (`eztudy index`) — it's cheap and gives citable chunk ids.
- Build/extend the **wiki** when the user wants understanding, overviews, or study material, or the
  corpus has more than a handful of sources. For tiny corpora (1–3 short docs) reading sources directly is fine.
- For study material use **both**: wiki for topic structure and coverage, search for grounded facts and citations.

## Workflows

### 0. Bookkeeping (start of every session)
1. `eztudy status`. If anything is pending, `eztudy index` (it syncs first). If it lists saved reports not
   yet imported, run workflow 5.
2. If the wiki exists and `status` lists uncovered sources or issues, run the ingest workflow on them / `eztudy wiki lint`.
3. Report briefly what changed. Don't re-ingest unchanged sources — hashes make it unnecessary.

### 1. Ingest into the wiki
Follow `references/wiki.md` (page format, naming, citation rules). In short, per new/changed source:
read it (`eztudy show <path>`) → write `wiki/summaries/<slug>.md` (one per source, or one per logical unit such as
an assignment made of several files — list them all in `sources:`) → create/update topic & entity pages with
`[[links]]` and inline citations → update `wiki/index.md` → `eztudy wiki log "ingest | <title>"`.
Finish with `eztudy wiki lint` and fix everything it reports. Many sources: ingest in parallel sub-agents,
one source each, then do a single consolidation pass yourself (merge duplicates, fix index, lint).

### 2. Answer questions (chat with your sources)
1. If the wiki exists, read `wiki/index.md` and the relevant pages first.
2. `eztudy search` for the specific claims (try 2–3 phrasings; use `--mode fts` for names/numbers/terms).
3. `eztudy show <cid> --context 1` when a hit is cut off.
4. Answer **only** from sources. Cite every claim as `(path, page N)` or `[cid]`. If the sources don't
   say, say so — never fill gaps from general knowledge unless the user asks, and then label it.
5. If the answer is a reusable synthesis, offer to file it into the wiki (new page + index + log).

### 3. Generate study material
Read `references/study-formats.md` for schemas and quality rules. Then:
1. Scope: which sources/topics, how many items, difficulty. Default: whole notebook, balanced.
   **Tailor to the student** when `wiki/learner.md` exists or `eztudy progress --json` has reports: unless the
   user asks otherwise, put about half the items on `weak_topics` and `problem_items` (new angles on the same idea,
   never the identical question), about a third on `learning` topics, and the rest on topics not practised yet or
   `strong` ones. Target each misconception from `learner.md` with a question whose distractor is that
   misconception. Tell the user what you targeted and why.
   **Pick the item type by the answer:** a number → `numeric`, a key term or code token → `cloze`, a sequence →
   `ordering`, pairs → `matching` (all checked exactly in the page); `mcq` / `multi` / `true_false` for judgements
   between alternatives; `short` / `code` only when the student must explain or write something open (graded by a model).
2. Plan coverage from the wiki index (or `eztudy sources` + summaries). Spread items across topics.
   If the user has a syllabus or topic list, run `eztudy coverage <list.md>` first and tell them which
   topics have **no** material (don't invent items for those); re-run it after new sources are ingested.
3. Ground every item: search, then cite the chunk id + source location.
4. Write `study/<kind>/<slug>.json`, then `eztudy render` it (validates; writes `.md` + `.html`).
   Non-interactive kinds (guide, briefing, FAQ, glossary, timeline, mind map, audio script) are
   plain Markdown in `study/guides/` etc. — still cited.
5. Open it for the student and stand by to grade (workflow 6): run `eztudy serve --open study/quizzes/<slug>.html`
   **in the background** (if a server is already up it just opens the page; it exits by itself about 2 minutes
   after the last quiz tab closes), then `eztudy report wait` **in the background**, once per quiz you open. Tell the
   user the quiz is open and that their written answers are graded when they finish. If you can't run background
   commands, give them the `.html` path instead.

### 4. Reorganize sources / reindex
You may move, rename, and group files in `sources/` to improve organization (e.g. by course/topic),
following `references/reorganizing.md`. Moves are detected by content hash: no re-extraction, no
re-embedding, and wiki citations stay valid after you update their paths (lint reports `unknown_sources`).
`eztudy index --rebuild` after changing `embedding_model` / chunk settings in `.eztudy/config.toml`.

Fix a bad source title (e.g. a web PDF titled with its URL) in `.eztudy/config.toml`, keyed by path or by the
8-char hash from `eztudy sources` (the hash survives moves); the next `sync`/`index` applies it, no re-extraction:
```toml
[titles]
"web/week-06.pdf" = "CS 1332 – Week 06"
"3fa9c2d1" = "Mock exam 1 key"
```

### 5. Learn from a finished session (performance reports)
Served pages (workflow 6) send their report on their own; it is already imported. Opened from disk, the
player instead offers **Save report** (downloads
`<deck>.<time>.eztudy-report.json`) and **Copy report** (JSON to paste into chat). When the user says they
finished, pastes a report, or `status` shows unimported reports:
1. `eztudy report import` (scans `study/` and `~/Downloads`), or `eztudy report import <file>`. For pasted JSON, pipe
   it in: `eztudy report import -`. Imports are idempotent and stored in `.eztudy/progress/reports/`.
2. `eztudy progress --json`. It gives `topics` (`mastery` 0–1 with recent sessions weighted more, `status`
   weak/learning/strong), `weak_topics`, and `problem_items` (each with `misses`, `still_missing`, the
   `wrong_answers` picked and `deck_path` to the source JSON).
3. Diagnose, don't just count: for each still-missing item, compare the wrong answer with the correct one and
   the item's citations (`eztudy show <cid>`). Name the likely **misconception** ("treats mitosis and meiosis
   as the same", "off-by-one on 0-indexed formula").
4. Write or update `wiki/learner.md` (yours to maintain, linked from `wiki/index.md`):
   ```markdown
   # Learner profile
   _Updated 2026-11-09 from 4 sessions._
   ## Focus next
   - [[Organelles]]: 35% (weak). Picked "Nucleus" for ATP production twice.
   ## Misconceptions
   - Thinks the nucleus makes ATP. Correct: mitochondria (bio/cells.pdf, page 1). Seen in cells/q1. Open.
   ## Strong
   - [[Energy]]: 92%
   ```
   Mark a misconception resolved once its items are answered correctly in two later sessions. Numbers come
   from `eztudy progress`; never invent them. `eztudy wiki log "progress | <deck>"`.
5. Tell the user in two or three lines what went well, what to focus on, and offer a tailored quiz or deck
   (workflow 3).

### 6. Grade a served quiz (short and code answers)
The server grades short and code answers itself with headless `claude -p` on a cheap model (haiku by default;
`[grading] model = "sonnet"` in `.eztudy/config.toml` to change, `fallback = "none"` to turn it off). It sends only
the question, the student's answer, the key and the rubric, with no tools. So `eztudy report wait` usually returns
a one-line summary ("graded by claude: q2 correct, …"): continue with workflow 5 from step 2.

It returns a **grading packet** instead when there is no headless grader or it failed. Then you grade, promptly,
because the student is on the results screen watching "Grading…":
1. Read the printed packet: per item the question, `student_answer`, `model_answer`, `explanation`,
   `citations` and, for code, the `rubric` (with what the student ticked). Check a cited chunk
   (`eztudy show <cid>`) only when the model answer doesn't settle it.
2. Grade fairly: `correct` when the core idea is right, even in other words or with another valid approach.
   For code, mark each rubric criterion `met` and give `points`; correct means about 70% of the points and no
   serious bug. Feedback is one or two sentences to the student: what was right, then the specific gap.
3. Pipe the verdicts in (one per item; JSON via heredoc):
   `eztudy report grade <session> - <<'EOF'` + `{"items": [{"id": "q2", "result": "correct", "feedback": "…"},
   {"id": "q3", "result": "wrong", "points": 1, "feedback": "…", "rubric": [{"index": 0, "met": false, "note": "…"}]}]}`.
   A rejected verdict says what to fix; resend.
4. Run workflow 5 from step 2 (the report is already imported). Don't re-arm `eztudy report wait` on your own:
   each wake-up costs your tokens, and retries are graded without you anyway (they show up in `eztudy status` and
   `eztudy progress`). Start it again only when you open another quiz or the user asks.
If nobody can grade (no headless grader and no agent waiting, or both failed), after about 3 minutes the page
lets the student grade themselves.

## Rules
- `sources/` content is the user's: never edit file contents, never delete without explicit permission.
  Moving/renaming/grouping is allowed; mention what you moved.
- Only `wiki/`, `study/` and `.eztudy/` are yours to write. Never edit stored reports in `.eztudy/progress/`.
- Every factual statement in wiki pages and study material carries a citation to a source.
- Unsupported/failed sources show in `status`/`sources` (e.g. scanned PDFs without text). Tell the
  user; offer to OCR (`anthropic-skills:pdf`) into a `.md` placed next to the original.
