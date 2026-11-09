# Wiki mode

An LLM-maintained knowledge base, compiled from `sources/` once and kept current incrementally
(the "LLM wiki" pattern). Sources are the immutable raw layer; the wiki is the synthesized layer you
own; this file is the schema. The wiki is plain Markdown with `[[wikilinks]]`, so it also opens in Obsidian.

## Layout

```
wiki/
  index.md          catalog of every page, one line each — read this first, update on every change
  log.md            append-only history (use `eztudy wiki log`)
  summaries/        one page per source or logical unit: summaries/<slug>.md
  topics/           concepts, themes, methods: topics/<topic-slug>.md
  entities/         people, places, orgs, works, named things: entities/<name-slug>.md
  (optional) overview.md, questions/, comparisons/ — add folders when they earn their keep
```

File names are lowercase kebab-case slugs. Links may use the slug, the relative path, or the page
title — `[[photosynthesis]]`, `[[topics/photosynthesis]]`, `[[Photosynthesis]]` all resolve.
`[[page|label]]` and `[[page#section]]` work too.

## Page format

```markdown
---
title: Calvin Cycle
type: topic            # summary | topic | entity | overview | question
sources:               # every source this page draws on; path relative to sources/
  - path: bio/plants.docx
    hash: 2f0cdc84     # first 8 chars of the source hash (from `eztudy sources`) — lets lint flag stale pages
  - path: bio/cells.pdf
    hash: a8cbb175
    pages: 3-4
updated: 2026-11-08
tags: [biology, photosynthesis]
---

# Calvin Cycle

One-paragraph definition in plain language.

## Key points
- The cycle fixes CO₂ using RuBisCO (plants.docx; [2f0cdc84:0]).
- ...

## Related
- [[photosynthesis]] — parent process
- [[rubisco]]
```

Rules:
- **Cite inline**: `(file, page N)`, `(file, slide N)`, or a chunk id `[3fa9c2d1:12]`. No uncited facts.
  Every source cited in the body must be in `sources:` (lint: `body_not_in_frontmatter`). Don't copy
  hashes by hand: `eztudy wiki cite <path|cid>...` prints the block, and `eztudy wiki lint --fix` fills it in.
  Quote a hash that is all digits (`hash: "12345678"`), or YAML reads it as a number.
- **Link generously**: first mention of any concept/entity that has (or deserves) a page gets `[[link]]`.
  Create stub pages for important link targets rather than leaving links broken.
- **Synthesize, don't copy**: topic pages merge what *all* sources say; note disagreements explicitly
  under a `## Conflicts` heading with both citations.
- **Summaries** (`summaries/`): 150–400 words, the source's thesis, structure, key claims, and links
  to the topic/entity pages it feeds. Write one summary per **logical unit**: usually one source, but an
  assignment, chapter or lecture split across several files (e.g. `hw2/BST.java`, `hw2/BSTNode.java`,
  `hw2/spec.pdf`) gets one summary `summaries/hw2-bst.md` whose `sources:` lists every file in it.
  Lint counts each listed file as covered.
- Keep pages focused (~100–800 words). Split when a page sprawls; merge near-duplicates.

## index.md

Grouped catalog, one line per page: `- [[topics/calvin-cycle]] — how plants fix carbon`. Every non-special
page must appear here (lint enforces it). Keep an `## Overview` section with a 3–6 sentence synthesis
of the whole notebook.

## Workflows

**Ingest** (per new or changed source, from `eztudy status`):
1. `eztudy show <path>` (use `--pages` for long PDFs; for very long sources read in sections).
2. Write/overwrite `summaries/<slug>.md` (one per source, or one per logical unit of several files).
3. For each significant concept/entity: update its page if it exists (merge, don't append blindly;
   bump `updated`, add the source to `sources:`), otherwise create it.
4. Update `index.md` and the Overview if the big picture changed.
5. `eztudy wiki log "ingest | <source title>" --detail "pages touched: ..."`.

**Changed source**: lint reports `stale_citations`. Re-read the source, revise affected pages, update
the hash in their frontmatter.

**Deleted source**: lint reports `unknown_sources`. Remove the citation; if a page has no sources
left, delete it (and its index line) or fold it into another page.

**Moved source**: update the `path:` in frontmatter of pages that cite it (`unknown_sources` lists them).

**Query → file back**: when an answer you gave is a durable synthesis (comparison, explanation),
save it as a page (`type: question` or a topic), link it, index it, log it.

**Lint pass** (`eztudy wiki lint`): first run `eztudy wiki lint --fix`. It mechanically repairs `sources:`
frontmatter: fills missing hashes, follows sources that moved (by hash), adds sources cited in the body,
and bumps `updated:` on pages it changed. It rewrites only the frontmatter (YAML comments there are
dropped) and never refreshes a stale hash; that needs a re-read. `frontmatter_not_in_body` is
informational: a listed source the body never cites inline. Then fix broken links (create the page or fix the link), orphans (link
them from related pages), missing index entries, uncited pages, stale/unknown citations. Then do a
judgment pass the tool can't: contradictions between pages, claims superseded by newer sources,
concepts mentioned on many pages that lack their own page, gaps worth flagging to the user.
