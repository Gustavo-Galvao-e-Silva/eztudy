# Reorganizing sources and the index

Agents may restructure `sources/` and tune the index to make the notebook work better. Identity is
the SHA-256 of file content, so **moving or renaming is free**: no re-extraction, no re-embedding,
chunk ids stay the same.

## When to reorganize
- Flat folder with many files of mixed subjects → group by course / subject / project.
- Cryptic names (`scan_0032.pdf`, `Lecture (3) FINAL v2.pptx`) → descriptive kebab-case names
  (`lectures/03-thermodynamics.pptx`), using the extracted title (`eztudy sources`).
- Exact duplicates (same hash at two paths — visible in `eztudy sources`) → ask before removing one.

## How
1. `eztudy status` must show no pending changes first (run `eztudy index`).
2. Propose the new layout to the user as a short tree unless they already asked you to just do it.
3. Move with `mv` (never copy+delete; never edit contents). Keep extensions.
4. `eztudy index` — expect only "moved"/path updates, 0 newly embedded docs.
5. `eztudy wiki lint` → fix `unknown_sources` by updating `path:` in page frontmatter, and update
   any inline citations that mention the old filename.
6. `eztudy wiki log "reorganize | <summary>"` and tell the user what moved.

## Never
- Modify file contents, convert files in place, or delete a source without explicit permission.
- Put files outside `sources/` or in hidden folders (dot-folders are ignored by the indexer).

## Bringing in files from elsewhere
When the material lives in other folders (assignment repos, a course drive), use `eztudy add` instead of
copying by hand: `eztudy add ../homework02 --as hw2-bst --exclude 'tests,*.csv'`. It skips IDE, build
and archive files by default (`.idea`, `out`, `build`, `bin`, `node_modules`, `*.class`, `*.iml`, `*.zip`,
dot-files…; `--no-default-excludes` turns that off), records each file's origin in
`.eztudy/origins.json`, and never overwrites a different file already in `sources/`. Use `--dry-run` to
preview. `eztudy status` reports when an original has changed since it was copied; re-run the same
`eztudy add` to refresh those copies, then `eztudy index`. Moving or renaming the copies inside `sources/`
keeps the origin link.

## Derived sources
If a source can't be extracted (scanned PDF, image, audio), you may *add* a derived text file next to
it — e.g. `lecture-03.ocr.md` or `interview.transcript.md` — and note the origin at the top. The
original stays untouched.

## Tuning the vector index
`.eztudy/config.toml` (all optional):
```toml
embedding_model = "BAAI/bge-small-en-v1.5"   # any fastembed TextEmbedding model
chunk_tokens = 400
chunk_overlap = 60
```
- Multilingual sources → `"intfloat/multilingual-e5-large"` (see `fastembed.TextEmbedding.list_supported_models()` for more).
- Long technical documents where hits feel fragmentary → raise `chunk_tokens` to 600–800.
- After changing any of these: `eztudy index --rebuild` (a model change also triggers it automatically).
