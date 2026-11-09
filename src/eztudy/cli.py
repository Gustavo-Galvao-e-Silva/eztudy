"""eztudy command line: deterministic bookkeeping for an agent-run study notebook."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from . import chunk as chunking
from . import extract as extracting
from . import manifest as mf
from . import origins
from . import render as rendering
from . import vectordb, wiki
from .workspace import Workspace, WorkspaceError, find_workspace

CID_RE = re.compile(r"^[0-9a-f]{8}:\d+$")


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


# --- sync (extract) ------------------------------------------------------------


def sync_sources(ws: Workspace, force: bool = False, quiet: bool = False) -> dict:
    """Bring manifest + extracted-text cache in line with sources/."""
    ws.ensure_state()
    data = mf.load(ws)
    diff = mf.scan(ws, data)
    entries = data["sources"]
    log = {"extracted": [], "moved": [], "deleted": [], "unsupported": [], "errors": []}

    for old, new in diff.moved:
        entries[new] = {**entries.pop(old), **diff.current[new]}
        log["moved"].append({"from": old, "to": new})
    for rel in diff.deleted:
        entries.pop(rel, None)
        log["deleted"].append(rel)

    origins.follow_sync(ws, diff.moved, diff.deleted)

    todo = set(diff.new) | set(diff.changed)
    for rel in diff.unchanged:
        e = entries[rel]
        e.update(diff.current[rel])  # refresh mtime after a touch
        if force or (e.get("status") == "ok" and not (ws.text_dir / f"{e['hash']}.md").exists()):
            todo.add(rel)

    for rel in sorted(todo):
        cur = diff.current[rel]
        entry = {**cur}
        try:
            title, text = extracting.extract(ws.sources / rel)
            (ws.text_dir / f"{cur['hash']}.md").write_text(text)
            entry.update(status="ok", extracted_title=title, chars=len(text))
            log["extracted"].append(rel)
        except extracting.UnsupportedSource as e:
            entry.update(status="unsupported", reason=str(e))
            log["unsupported"].append({"path": rel, "reason": str(e)})
        except Exception as e:  # noqa: BLE001 - surface any extractor failure to the agent
            entry.update(status="error", reason=f"{type(e).__name__}: {e}")
            log["errors"].append({"path": rel, "reason": entry["reason"]})
        entries[rel] = entry

    apply_titles(ws, entries)

    # Garbage-collect cached text no longer referenced by any source.
    live = {e["hash"] for e in entries.values()}
    for f in ws.text_dir.glob("*.md"):
        if f.stem not in live:
            f.unlink()

    mf.save(ws, data)
    if not quiet:
        for k, label in [("extracted", "extracted"), ("moved", "moved"), ("deleted", "removed")]:
            for item in log[k]:
                print(f"  {label}: {item if isinstance(item, str) else item['from'] + ' -> ' + item['to']}")
        for item in log["unsupported"] + log["errors"]:
            print(f"  skipped: {item['path']} ({item['reason']})")
    return log


def title_override(ws: Workspace, rel: str, digest: str) -> str | None:
    """A `[titles]` entry from config.toml, keyed by source path or by an 8+ char hash prefix."""
    titles = ws.config.get("titles") or {}
    if rel in titles:
        return str(titles[rel])
    for key, value in titles.items():
        if len(key) >= 8 and re.fullmatch(r"[0-9a-f]+", key) and digest.startswith(key):
            return str(value)
    return None


def apply_titles(ws: Workspace, entries: dict) -> None:
    """Set each extracted source's title: config override, else what the extractor found."""
    for rel, e in entries.items():
        if e.get("status") != "ok":
            continue
        e.setdefault("extracted_title", e.get("title"))  # manifests written before overrides existed
        override = title_override(ws, rel, e["hash"])
        e["title"] = override or e["extracted_title"]
        if override:
            e["title_override"] = True
        else:
            e.pop("title_override", None)


def _docs(ws: Workspace) -> dict[str, dict]:
    """hash -> {path, title, chars} for every successfully extracted source (first path wins)."""
    out: dict[str, dict] = {}
    for rel, e in mf.load(ws)["sources"].items():
        if e.get("status") == "ok" and e["hash"] not in out:
            out[e["hash"]] = {"path": rel, "title": e.get("title") or Path(rel).stem, "chars": e.get("chars", 0)}
    return out


# --- commands ------------------------------------------------------------------


def cmd_add(ws: Workspace, args) -> int:
    patterns = ([] if args.no_default_excludes else list(origins.DEFAULT_EXCLUDES)) + [p.strip() for p in (args.exclude or "").split(",") if p.strip()]
    try:
        log = origins.add(ws, [Path(p).expanduser() for p in args.paths], args.as_name, patterns, dry_run=args.dry_run)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    verb = "would copy" if args.dry_run else "copied"
    for rel in log["copied"]:
        print(f"  {verb}: {rel}")
    for rel in log["updated"]:
        print(f"  {'would update' if args.dry_run else 'updated'}: {rel}")
    for c in log["conflicts"]:
        print(f"  skipped: {c['path']} ({c['reason']})", file=sys.stderr)
    print(f"{len(log['copied'])} new, {len(log['updated'])} updated, {len(log['unchanged'])} unchanged, "
          f"{len(log['conflicts'])} skipped" + ("" if args.dry_run else " -> run `eztudy index`"))
    return 1 if log["conflicts"] else 0


def cmd_status(ws: Workspace, args) -> int:
    data = mf.load(ws)
    diff = mf.scan(ws, data)
    entries = data["sources"]
    by_status: dict[str, int] = {}
    for e in entries.values():
        by_status[e.get("status", "?")] = by_status.get(e.get("status", "?"), 0) + 1

    vec = {"exists": ws.db_path.exists()}
    if ws.db_path.exists():
        db = vectordb.connect(ws.db_path)
        indexed = vectordb.indexed_docs(db)
        docs = _docs(ws)
        vec.update(vectordb.stats(db))
        vec["unindexed"] = sorted(d["path"] for h, d in docs.items() if h not in indexed)
        vec["orphaned"] = sorted(p for h, p in indexed.items() if h not in docs)
    report = wiki.lint(ws, data)
    origin_changes = origins.changed(ws)
    status = {
        "root": str(ws.root),
        "sources": {"tracked": len(entries), **by_status},
        "pending": diff.to_dict(),
        "vector_index": vec,
        "wiki": {
            "pages": report["pages"],
            "uncovered_sources": report["uncovered_sources"],
            "issues": {k: len(v) for k, v in report.items() if isinstance(v, list) and k not in wiki.INFO_KEYS and v},
        },
        "origins_changed": origin_changes,
        "study": sorted(p.relative_to(ws.root).as_posix() for p in ws.study.rglob("*") if p.is_file()) if ws.study.exists() else [],
    }
    if args.json:
        _print_json(status)
        return 0
    print(f"notebook: {ws.root}")
    print(f"sources:  {len(entries)} tracked " + ", ".join(f"{v} {k}" for k, v in by_status.items()))
    p = status["pending"]
    if diff.dirty:
        print(f"pending:  {len(p['new'])} new, {len(p['changed'])} changed, {len(p['moved'])} moved, {len(p['deleted'])} deleted  -> run `eztudy sync`")
        for k in ("new", "changed", "deleted"):
            for rel in p[k]:
                print(f"  {k}: {rel}")
        for m in p["moved"]:
            print(f"  moved: {m['from']} -> {m['to']}")
    else:
        print("pending:  none")
    if vec["exists"]:
        print(f"vectors:  {vec['documents']} docs / {vec['chunks']} chunks ({vec['embedding_model']})"
              + (f"; {len(vec['unindexed'])} unindexed, {len(vec['orphaned'])} orphaned -> run `eztudy index`" if vec["unindexed"] or vec["orphaned"] else ""))
    else:
        print("vectors:  not built (run `eztudy index`)")
    w = status["wiki"]
    print(f"wiki:     {w['pages']} pages; {len(w['uncovered_sources'])} sources not yet cited by any page"
          + (f"; issues: {w['issues']} -> run `eztudy wiki lint`" if w["issues"] else ""))
    for o in origin_changes:
        what = "differs from" if o["state"] == "changed" else "was copied from (now missing)"
        print(f"origin:   {o['path']} {what} {o['origin']}" + (" -> re-run `eztudy add`" if o["state"] == "changed" else ""))
    if status["study"]:
        print(f"study:    {len(status['study'])} files in study/")
    return 0


def cmd_sync(ws: Workspace, args) -> int:
    print("syncing sources…")
    log = sync_sources(ws, force=args.force)
    print(f"done: {len(log['extracted'])} extracted, {len(log['moved'])} moved, {len(log['deleted'])} removed, "
          f"{len(log['unsupported']) + len(log['errors'])} skipped")
    return 0


def cmd_index(ws: Workspace, args, embedder=None) -> int:
    sync_sources(ws, quiet=True)
    docs = _docs(ws)
    db = vectordb.connect(ws.db_path)
    if args.rebuild:
        vectordb.reset(db)
    indexed = vectordb.indexed_docs(db)
    removed = [h for h in indexed if h not in docs]
    for h in removed:
        vectordb.delete_doc(db, h)
    moved = 0
    for h, d in docs.items():
        if h in indexed and indexed[h] != d["path"]:
            vectordb.update_path(db, h, d["path"])
            moved += 1
    for h, title in vectordb.indexed_titles(db).items():
        if h in docs and docs[h]["title"] != title:
            vectordb.update_title(db, h, docs[h]["title"])
    db.commit()

    todo = [h for h in docs if h not in indexed or args.rebuild]
    if vectordb.get_meta(db, "code_chunker") != chunking.CODE_CHUNKER_VERSION:
        # Older indexes chunked code like prose (no line ranges): re-chunk just the code sources.
        todo += [h for h in docs if h in indexed and h not in todo and extracting.source_type(docs[h]["path"]) == "code"]
    model = ws.config["embedding_model"]
    if todo or vectordb.get_meta(db, "embedding_model") != model:
        if embedder is None:
            from .embed import Embedder

            embedder = Embedder(model)
        if vectordb.ensure_vec_table(db, embedder.model_name, embedder.dim):
            print(f"embedding model changed -> rebuilding index with {embedder.model_name}")
            todo = list(docs)
    total_chunks = 0
    for n, h in enumerate(todo, start=1):
        d = docs[h]
        if extracting.source_type(d["path"]) == "code":
            # Chunk the original file (not the normalized extract) so line numbers are exact.
            src = (ws.sources / d["path"]).read_text(errors="replace")
            chunks = chunking.chunk_code(src, Path(d["path"]).suffix, ws.config["chunk_tokens"], ws.config["chunk_overlap"])
        else:
            text = (ws.text_dir / f"{h}.md").read_text()
            chunks = chunking.chunk_markdown(text, ws.config["chunk_tokens"], ws.config["chunk_overlap"])
        if not chunks:
            continue
        embed_inputs = [f"{d['title']}\n{c.heading}\n{c.text}" if c.heading else f"{d['title']}\n{c.text}" for c in chunks]
        vectors = embedder.embed_documents(embed_inputs)
        vectordb.add_doc(db, h, d["path"], d["title"], d["chars"], chunks, vectors)
        db.commit()
        total_chunks += len(chunks)
        print(f"  [{n}/{len(todo)}] {d['path']}: {len(chunks)} chunks")
    vectordb.set_meta(db, "code_chunker", chunking.CODE_CHUNKER_VERSION)
    db.commit()
    st = vectordb.stats(db)
    print(f"index: +{len(todo)} docs ({total_chunks} chunks), -{len(removed)} removed, {moved} path updates; "
          f"total {st['documents']} docs / {st['chunks']} chunks")
    return 0


def _query_embedder(db, embedder=None):
    """The embedder matching the index's model (or the one passed in); None, with a message, if there's no index."""
    model = vectordb.get_meta(db, "embedding_model")
    if not model:
        print("vector index is empty; run `eztudy index`", file=sys.stderr)
        return None
    if embedder is None:
        from .embed import Embedder

        embedder = Embedder(model)
    return embedder


def cmd_coverage(ws: Workspace, args, embedder=None) -> int:
    from . import coverage

    path = Path(args.topics)
    if not path.is_absolute() and not path.exists():
        path = ws.root / args.topics
    if not path.exists():
        print(f"error: {args.topics} not found", file=sys.stderr)
        return 2
    topics = coverage.parse_topics(path.read_text())
    if not topics:
        print(f"error: no topics found in {path.name} (use a Markdown list)", file=sys.stderr)
        return 2
    if not ws.db_path.exists():
        print("no vector index yet; run `eztudy index` first", file=sys.stderr)
        return 2
    db = vectordb.connect(ws.db_path)
    embedder = _query_embedder(db, embedder)
    if embedder is None:
        return 2
    rows = []
    for t in topics:
        rows.append({**t, **coverage.assess(db, t["topic"], embedder.embed_query(t["topic"]), ws.config, k=args.k)})
    rows.sort(key=lambda r: coverage.ORDER[r["status"]])  # stable: keeps syllabus order within a status
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# Coverage: {path.name}\n\n" + coverage.to_markdown(rows))
    if args.json:
        _print_json(rows)
        return 0
    width = min(48, max(len(r["topic"]) for r in rows))
    for r in rows:
        best = r["matches"][0] if r["matches"] else None
        where = f"{best['citation']} [{best['cid']}]" if best else "—"
        print(f"{r['status']:<8} {r['topic'][:width]:<{width}}  {where}  (terms {r['overlap']:.0%}, sim {r['similarity']:.2f})")
    counts = {s: sum(r["status"] == s for r in rows) for s in coverage.ORDER}
    print(f"\n{counts['covered']} covered, {counts['partial']} partial, {counts['missing']} missing"
          + (f"; wrote {args.out}" if args.out else ""))
    return 0


def cmd_search(ws: Workspace, args, embedder=None) -> int:
    if not ws.db_path.exists():
        print("no vector index yet; run `eztudy index` first", file=sys.stderr)
        return 2
    db = vectordb.connect(ws.db_path)
    qvec = None
    if args.mode != "fts":
        embedder = _query_embedder(db, embedder)
        if embedder is None:
            return 2
        qvec = embedder.embed_query(args.query)
    hits = vectordb.search(db, args.query, qvec, k=args.k, mode=args.mode, path_prefix=args.path)
    if args.json:
        _print_json([h.to_dict() for h in hits])
        return 0
    if not hits:
        print("no results")
    for n, hit in enumerate(hits, start=1):
        head = f" — {hit.heading}" if hit.heading else ""
        print(f"[{n}] {hit.cid}  {hit.citation}{head}  (score {hit.score:.4f})")
        body = hit.text if args.full or len(hit.text) <= 700 else hit.text[:700].rstrip() + " …"
        print("    " + body.replace("\n", "\n    "))
        print()
    return 0


def cmd_show(ws: Workspace, args) -> int:
    target = args.target
    if CID_RE.match(target):
        db = vectordb.connect(ws.db_path)
        hits = vectordb.get_chunk(db, target, context=args.context)
        if not hits:
            print(f"chunk {target} not found (index may be stale; run `eztudy index`)", file=sys.stderr)
            return 1
        for hit in hits:
            print(f"--- {hit.cid}  {hit.citation}" + (f" — {hit.heading}" if hit.heading else ""))
            print(hit.text)
            print()
        return 0
    entries = mf.load(ws)["sources"]
    rel = _resolve_source(entries, target)
    if rel is None:
        return 1
    e = entries[rel]
    if e.get("status") != "ok":
        print(f"{rel}: not extracted ({e.get('reason', e.get('status'))})", file=sys.stderr)
        return 1
    if args.lines or args.symbol:
        return _show_lines(ws, rel, e, args)
    text = (ws.text_dir / f"{e['hash']}.md").read_text()
    if args.pages:
        a, _, b = args.pages.partition("-")
        lo, hi = int(a), int(b or a)
        parts = re.split(r"(<!--\s*(?:page|slide)\s+\d+\s*-->)", text)
        keep, cur = [], None
        for part in parts:
            m = extracting.MARKER_RE.fullmatch(part.strip())
            if m:
                cur = int(m.group(2))
            if cur is not None and lo <= cur <= hi:
                keep.append(part)
        text = "".join(keep) or f"(no page/slide markers in range {args.pages})"
    print(f"# {e.get('title')}  [sources/{rel}]  hash {e['hash'][:8]}")
    print(text)
    return 0


def _show_lines(ws: Workspace, rel: str, e: dict, args) -> int:
    """Numbered lines of a text/code source, by range (--lines 340-375) or by symbol (--symbol name)."""
    if extracting.source_type(rel) in ("pdf", "docx", "pptx"):
        print(f"{rel}: --lines/--symbol work on text and code sources; use --pages", file=sys.stderr)
        return 1
    lines = (ws.sources / rel).read_text(errors="replace").splitlines()
    if args.symbol:
        syms = [s for s in chunking.code_symbols("\n".join(lines), Path(rel).suffix)
                if args.symbol in (s.name, s.heading)]
        if len(syms) != 1:
            cands = [f"{s.heading} (lines {s.start}-{s.end})" for s in syms]
            print(f"{rel}: " + (f"{args.symbol!r} is ambiguous: {cands} (use 'Class > name')" if syms else f"no symbol {args.symbol!r}"), file=sys.stderr)
            return 1
        lo, hi, label = syms[0].start, syms[0].end, f" ({syms[0].heading})"
    else:
        a, _, b = args.lines.partition("-")
        lo, hi, label = max(1, int(a)), min(len(lines), int(b or a)), ""
    print(f"# {e.get('title')}  [sources/{rel}:{lo}-{hi}]{label}  hash {e['hash'][:8]}")
    width = len(str(hi))
    for n in range(lo, hi + 1):
        print(f"{n:>{width}}  {lines[n - 1]}")
    return 0


def _resolve_source(entries: dict, target: str) -> str | None:
    """Exact source path, chunk id / hash prefix, or unique case-insensitive substring; prints why on failure."""
    rel = target.removeprefix("sources/")
    if rel in entries:
        return rel
    m = re.fullmatch(r"([0-9a-f]{8,64})(?::\d+)?", rel)
    if m and (hit := wiki.source_for_hash(entries, m.group(1))):
        return hit
    matches = [p for p in entries if rel.lower() in p.lower()]
    if len(matches) == 1:
        return matches[0]
    print(f"no tracked source matches {target!r}" + (f"; candidates: {matches}" if matches else " (run `eztudy sync`?)"), file=sys.stderr)
    return None


def cmd_sources(ws: Workspace, args) -> int:
    entries = mf.load(ws)["sources"]
    rows = [{"path": p, "hash": e["hash"][:8], "status": e.get("status"), "title": e.get("title"),
             "title_override": bool(e.get("title_override")), "chars": e.get("chars", 0)} for p, e in entries.items()]
    if args.json:
        _print_json(rows)
        return 0
    if not rows:
        print("no sources tracked yet; run `eztudy sync`")
    for r in rows:
        flag = "" if r["status"] == "ok" else f"  [{r['status']}]"
        mark = " (title from config)" if r["title_override"] else ""
        print(f"{r['hash']}  {r['chars']:>8,} ch  {r['path']}  — {r['title'] or ''}{mark}{flag}")
    return 0


WIKI_INDEX = """---
title: Index
type: index
---

# {name} — Wiki Index

Catalog of every page in this wiki. Keep one line per page: `[[page]] — one-line description`.
Agents: read this first when answering questions; update it on every ingest.

## Overview

## Topics

## Entities

## Source summaries
"""

WIKI_LOG = """---
title: Log
type: log
---

# Log

Append-only record of ingests, queries filed back, and lint passes. Newest at the bottom.
Format: `## [YYYY-MM-DD] <action> | <subject>`
"""


def cmd_wiki(ws: Workspace, args) -> int:
    if args.wiki_cmd == "init":
        for sub in ("topics", "entities", "summaries"):
            (ws.wiki / sub).mkdir(parents=True, exist_ok=True)
        created = []
        if not (ws.wiki / "index.md").exists():
            (ws.wiki / "index.md").write_text(WIKI_INDEX.format(name=ws.root.name))
            created.append("wiki/index.md")
        if not (ws.wiki / "log.md").exists():
            (ws.wiki / "log.md").write_text(WIKI_LOG)
            created.append("wiki/log.md")
        print("created: " + (", ".join(created) if created else "nothing (wiki already initialized)"))
        return 0
    if args.wiki_cmd == "log":
        path = ws.wiki / "log.md"
        if not path.exists():
            ws.wiki.mkdir(parents=True, exist_ok=True)
            path.write_text(WIKI_LOG)
        with path.open("a") as fh:
            fh.write(f"\n## [{dt.date.today().isoformat()}] {args.message}\n")
            if args.detail:
                fh.write(f"{args.detail}\n")
        print(f"logged: {args.message}")
        return 0
    if args.wiki_cmd == "cite":
        entries = mf.load(ws)["sources"]
        rels = [_resolve_source(entries, t) for t in args.targets]
        if None in rels:
            return 1
        print("sources:")
        for rel in dict.fromkeys(rels):
            short = entries[rel]["hash"][:8]
            print(f"  - path: {rel}\n    hash: {repr(short) if short.isdigit() else short}")  # quote all-digit hashes for YAML
        return 0
    if args.wiki_cmd == "lint":
        fixed = wiki.fix(ws, mf.load(ws)) if args.fix else []
        report = wiki.lint(ws, mf.load(ws))
        if args.fix:
            report = {"fixed": fixed, **report}
        if args.json:
            _print_json(report)
            return 0 if wiki.lint_ok(report) else 1
        print(f"{report['pages']} pages")
        for key, items in report.items():
            if not isinstance(items, list) or not items:
                continue
            info = " (info)" if key in wiki.INFO_KEYS else ""
            print(f"\n{key.replace('_', ' ')}{info} ({len(items)}):")
            for it in items:
                print("  - " + (it if isinstance(it, str) else ", ".join(f"{k}={v}" for k, v in it.items())))
        ok = wiki.lint_ok(report)
        print("\nOK" if ok else "\nissues found")
        return 0 if ok else 1
    return 2


def cmd_render(ws: Workspace, args) -> int:
    rc = 0
    known = None
    if ws.db_path.exists():
        known = {r[0] for r in vectordb.connect(ws.db_path).execute("SELECT cid FROM chunks")}
    else:
        print("note: no index yet, so citation chunk ids were not checked (run `eztudy index`)", file=sys.stderr)
    for p in args.files:
        path = Path(p)
        if not path.is_absolute() and not path.exists():
            path = ws.root / p
        try:
            md, html, warns = rendering.render(path, known)
            print(f"rendered {path.name} -> {md.name}, {html.name}")
            for w in warns:
                print(f"warning: {path.name}: {w}", file=sys.stderr)
            if warns and args.strict:
                rc = 1
        except (rendering.StudyFormatError, FileNotFoundError) as e:
            print(f"error: {e}", file=sys.stderr)
            rc = 1
    return rc


# --- entry -----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="eztudy", description=__doc__)
    ap.add_argument("-C", "--root", help="notebook dir (default: nearest ancestor with sources/, or $EZTUDY_ROOT)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="what changed in sources/, index + wiki health")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("add", help="copy files/folders from elsewhere into sources/, tracking their origin")
    s.add_argument("paths", nargs="+")
    s.add_argument("--as", dest="as_name", help="folder under sources/ to put them in (default: the folder's name)")
    s.add_argument("--exclude", help="extra comma-separated name patterns to skip, e.g. 'tests,*.csv'")
    s.add_argument("--dry-run", action="store_true", help="only list what would be copied")
    s.add_argument("--no-default-excludes", action="store_true",
                   help="don't skip IDE/build/archive files (.idea, out, build, bin, *.class, *.zip, …)")

    s = sub.add_parser("sync", help="extract new/changed sources to text; track moves/deletes")
    s.add_argument("--force", action="store_true", help="re-extract everything")

    s = sub.add_parser("index", help="sync, then chunk + embed into the SQLite vector index")
    s.add_argument("--rebuild", action="store_true", help="drop and rebuild the whole index")

    s = sub.add_parser("search", help="hybrid (vector + keyword) search over chunks")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=8)
    s.add_argument("--mode", choices=["hybrid", "vector", "fts"], default="hybrid")
    s.add_argument("--path", help="only sources whose path starts with this prefix")
    s.add_argument("--full", action="store_true", help="don't truncate chunk text")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("coverage", help="map a syllabus/topic list (Markdown list) to the sources")
    s.add_argument("topics", help="Markdown file; each list item is a topic, headings group them")
    s.add_argument("-k", type=int, default=5, help="hits to consider per topic")
    s.add_argument("--out", help="also write a Markdown coverage table here")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("show", help="print a chunk (by id) or a source's extracted text (by path)")
    s.add_argument("target", help="chunk id like 3fa9c2d1:12, or a source path / unique substring")
    s.add_argument("--context", type=int, default=0, help="neighbouring chunks to include")
    s.add_argument("--pages", help="for PDFs/PPTX: page or slide range, e.g. 3-5")
    s.add_argument("--lines", help="for text/code: numbered line range, e.g. 340-375")
    s.add_argument("--symbol", help="for code: a class/function/method name (or 'Class > method')")

    s = sub.add_parser("sources", help="list tracked sources")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("wiki", help="wiki-mode helpers")
    wsub = s.add_subparsers(dest="wiki_cmd", required=True)
    wsub.add_parser("init", help="create wiki/index.md, wiki/log.md and folders")
    w = wsub.add_parser("lint", help="check links, orphans, index coverage, citations")
    w.add_argument("--json", action="store_true")
    w.add_argument("--fix", action="store_true",
                   help="fill missing hashes, follow moved sources, add body-cited sources to frontmatter")
    w = wsub.add_parser("cite", help="print a ready-to-paste `sources:` frontmatter block")
    w.add_argument("targets", nargs="+", help="source paths, unique substrings, or chunk ids")
    w = wsub.add_parser("log", help="append an entry to wiki/log.md")
    w.add_argument("message")
    w.add_argument("--detail")

    s = sub.add_parser("render", help="validate study JSON and write .md + interactive .html next to it")
    s.add_argument("files", nargs="+")
    s.add_argument("--strict", action="store_true", help="exit 1 if any citation chunk id is not in the index")
    return ap


COMMANDS = {
    "status": cmd_status, "add": cmd_add, "sync": cmd_sync, "index": cmd_index, "search": cmd_search,
    "show": cmd_show, "coverage": cmd_coverage, "sources": cmd_sources, "wiki": cmd_wiki, "render": cmd_render,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ws = find_workspace(args.root)
    except WorkspaceError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return COMMANDS[args.cmd](ws, args) or 0


if __name__ == "__main__":
    sys.exit(main())
