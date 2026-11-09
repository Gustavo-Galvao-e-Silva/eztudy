# eztudy

A local, open-source substitute for NotebookLM, packaged as an agent skill (Claude Code and any
agent that reads `SKILL.md`).

**Setup is one folder:** put your PDFs, Word docs, slide decks, notes and code in `sources/`, then
ask your agent to study them. The agent does the rest:

- **Wiki mode** — builds and maintains an interlinked Markdown wiki (summaries, topics, entities,
  citations, index, log) in `wiki/`, incrementally as sources change. Opens fine in Obsidian.
- **Vector mode** — a local SQLite index (`sqlite-vec` + FTS5) with `fastembed` embeddings for
  hybrid semantic + keyword search with page-level citations. No API keys, no servers.
- **Study material** — quizzes, flashcards (both with a self-contained interactive HTML player),
  study guides, briefing docs, FAQs, glossaries, timelines, mind maps, audio-overview scripts.
- **Bookkeeping** — sources are tracked by content hash, so agents can rename and reorganize
  `sources/` freely without re-indexing.

## Install

Requires [uv](https://docs.astral.sh/uv/) (`brew install uv`). Python dependencies install
automatically on first run into `~/.cache/eztudy/venv`.

This repo is a Claude Code plugin and its own marketplace. Once it's pushed to GitHub:

```bash
claude plugin marketplace add Gustavo-Galvao-e-Silva/eztudy
claude plugin install eztudy@eztudy
```

or, inside a session, `/plugin install eztudy --marketplace Gustavo-Galvao-e-Silva/eztudy`.

From a local checkout instead:

```bash
claude plugin marketplace add ~/Projects/eztudy     # loads in place; edits apply on /reload-plugins
claude plugin install eztudy@eztudy
# or, for one session only:
claude --plugin-dir ~/Projects/eztudy
```

The plugin puts `eztudy` on the agent's PATH and adds the `eztudy` skill.

## Use

```bash
mkdir -p ~/notebooks/biology/sources && cp ~/Downloads/*.pdf ~/notebooks/biology/sources/
cd ~/notebooks/biology && claude
> use eztudy: index my sources, build the wiki, and make me a 15-question quiz on chapter 2
```

Then open `study/quizzes/*.html` in a browser.

The CLI is usable directly too (`bin/eztudy` in this repo):

```text
eztudy status                     what changed; index + wiki health
eztudy sync                       extract text, track moves/deletes
eztudy index [--rebuild]          chunk + embed (incremental)
eztudy search "query" [-k 8] [--mode hybrid|vector|fts] [--json]
eztudy show <chunk-id|path> [--context N] [--pages 3-5] [--lines 10-40|--symbol name]
eztudy sources                    list tracked sources
eztudy coverage topics.md         syllabus topics -> covered / partial / missing
eztudy wiki init|lint [--fix]|log|cite
eztudy render study/quizzes/x.json
```

## Layout of a notebook

```
sources/    your files (PDF, DOCX, PPTX, MD/TXT, HTML, code)
wiki/       agent-maintained knowledge base
study/      generated study material
.eztudy/    state: manifest, extracted text, index.db, optional config.toml
```

## Develop

```bash
uv run pytest
```

Layout:

```
.claude-plugin/plugin.json        plugin manifest
.claude-plugin/marketplace.json   single-plugin marketplace (source "./")
skills/eztudy/SKILL.md            agent instructions
skills/eztudy/references/         wiki schema, study formats, reorganizing rules
bin/eztudy                        CLI wrapper (on PATH when the plugin is enabled)
src/eztudy/                       Python CLI
tests/
```

Validate with `claude plugin validate .`; release with `claude plugin tag` after bumping
`version` in `.claude-plugin/plugin.json`.

## License

MIT
