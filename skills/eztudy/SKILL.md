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
eztudy index [--rebuild]           # sync + chunk + embed into SQLite (fastembed, local)
eztudy search "query" [-k 8] [--mode hybrid|vector|fts] [--path bio/] [--full] [--json]
eztudy show <chunk-id> [--context 1]          # read a chunk (+ neighbours) e.g. 3fa9c2d1:12
eztudy show <source-path> [--pages 3-5]       # read a source's extracted text (PDF pages / PPTX slides)
eztudy sources [--json]            # list tracked sources with hash, size, title, status
eztudy wiki init | lint [--json] | log "ingest | Title" [--detail "..."]
eztudy render study/quizzes/x.json [...] [--strict]  # validate + write x.md and interactive x.html;
                                   # warns on citation cids not in the index (--strict: exit 1)
```

`search --json` prints a list of hits, best first:
```json
[{"cid": "3fa9c2d1:12", "path": "bio/cells.pdf", "title": "Cell Biology Notes", "type": "pdf",
  "heading": "Organelles > Mitochondria", "location": "pages 4-5", "score": 0.032258,
  "text": "…chunk text…", "citation": "bio/cells.pdf (pages 4-5)"}]
```
`type` is one of `pdf | docx | pptx | html | code | markdown | text`; `location` is `page N`, `pages N-M`,
`slide N`… or `""` when the source has no page/slide markers. `score` is only comparable within one query.

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
1. `eztudy status`. If anything is pending, `eztudy index` (it syncs first).
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
2. Plan coverage from the wiki index (or `eztudy sources` + summaries). Spread items across topics.
3. Ground every item: search, then cite the chunk id + source location.
4. Write `study/<kind>/<slug>.json`, then `eztudy render` it (validates; writes `.md` + `.html`).
   Non-interactive kinds (guide, briefing, FAQ, glossary, timeline, mind map, audio script) are
   plain Markdown in `study/guides/` etc. — still cited.
5. Tell the user the `.html` path to open in a browser.

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

## Rules
- `sources/` content is the user's: never edit file contents, never delete without explicit permission.
  Moving/renaming/grouping is allowed; mention what you moved.
- Only `wiki/`, `study/` and `.eztudy/` are yours to write.
- Every factual statement in wiki pages and study material carries a citation to a source.
- Unsupported/failed sources show in `status`/`sources` (e.g. scanned PDFs without text). Tell the
  user; offer to OCR (`anthropic-skills:pdf`) into a `.md` placed next to the original.
