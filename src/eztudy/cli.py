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
from . import grading
from . import manifest as mf
from . import origins
from . import progress as prog
from . import render as rendering
from . import serve as serving
from . import srs
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
        "progress": _progress_brief(ws),
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
    pg = status["progress"]
    if pg["reports"]:
        print(f"progress: {pg['reports']} sessions, last {pg['last_session'][:10]}"
              + (f"; weak: {', '.join(pg['weak_topics'][:5])}" if pg["weak_topics"] else "") + " -> `eztudy progress`")
    d = pg["due"]
    if d["due_now"]:
        parts = [f"{d['by_kind'].get('quiz', 0)} quiz", f"{d['by_kind'].get('flashcards', 0)} cards"]
        print(f"review:   {d['due_now']} due now ({', '.join(p for p in parts if not p.startswith('0 '))})"
              + (f"; {d['due_tomorrow']} more by tomorrow" if d["due_tomorrow"] else "") + " -> `eztudy review`")
    elif d["next_due"]:
        print(f"review:   nothing due; next {d['next_due'][:10]}")
    if pg["unimported"]:
        print(f"reports:  {pg['unimported']} saved report(s) not imported -> run `eztudy report import`")
    if pg["server"]:
        print(f"server:   {pg['server']}")
    g = pg["grading"]
    if g["pending"] or g["failed"]:
        print(f"grading:  {g['pending']} waiting, {g['failed']} failed"
              + (" -> run `eztudy report wait` to grade them" if g["pending"] else ""))
    if status["study"]:
        print(f"study:    {len(status['study'])} files in study/")
    return 0


def _progress_brief(ws: Workspace) -> dict:
    reports = prog.load_all(ws)
    summary = prog.summarize(reports)
    retention, max_days = srs.settings(ws.config)
    due = srs.due_summary(srs.schedule(reports, retention=retention, max_interval=max_days))
    unimported = prog.count_unimported(ws)
    st = serving.state_path(ws).exists() and serving.running(ws)
    return {"reports": summary["reports"], "last_session": summary["last_session"],
            "weak_topics": summary["weak_topics"], "unimported": unimported, "due": due,
            "server": serving.page_url(st) if st else None,
            "grading": {"pending": len(grading.jobs(ws, "job")) + len(grading.jobs(ws, "claimed")),
                        "failed": len(grading.jobs(ws, "failed"))}}


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
    paths = []
    for p in args.files:
        path = Path(p)
        paths.append(path if path.is_absolute() or path.exists() else ws.root / p)
    return render_files(ws, paths, args.theme, args.strict)


def render_files(ws: Workspace, paths: list[Path], theme: str | None = None, strict: bool = False) -> int:
    rc = 0
    known = None
    if ws.db_path.exists():
        known = {r[0] for r in vectordb.connect(ws.db_path).execute("SELECT cid FROM chunks")}
    else:
        print("note: no index yet, so citation chunk ids were not checked (run `eztudy index`)", file=sys.stderr)
    skin = theme or (ws.config.get("ui") or {}).get("theme")
    if skin and skin not in rendering.SKINS:
        print(f"error: unknown theme {skin!r} in .eztudy/config.toml [ui]; choose one of {', '.join(rendering.SKINS)}", file=sys.stderr)
        return 2
    for path in paths:
        try:
            md, html, warns = rendering.render(path, known, skin, ws)
            print(f"rendered {path.name} -> {md.name}, {html.name}")
            for w in warns:
                print(f"warning: {path.name}: {w}", file=sys.stderr)
            if warns and strict:
                rc = 1
        except (rendering.StudyFormatError, FileNotFoundError) as e:
            print(f"error: {e}", file=sys.stderr)
            rc = 1
    return rc


# --- progress (performance reports) -----------------------------------------------


def cmd_report(ws: Workspace, args) -> int:
    if args.report_cmd == "wait":
        return _report_wait(ws, args)
    if args.report_cmd == "grade":
        return _report_grade(ws, args)
    if args.report_cmd != "import":
        return 2
    sources: list[tuple[str, str]] = []
    if args.files:
        for f in args.files:
            if f == "-":
                sources.append(("<stdin>", sys.stdin.read()))
                continue
            path = Path(f)
            if not path.exists() and (ws.root / f).exists():
                path = ws.root / f
            try:
                sources.append((str(path), path.read_text()))
            except OSError as e:
                print(f"error: {f}: {e.strerror}", file=sys.stderr)
                return 1
    else:
        cands = prog.default_candidates(ws)
        if not cands:
            print(f"no {prog.REPORT_GLOB} files found in study/ or ~/Downloads; pass a path (or - for stdin)")
            return 0
        sources = [(str(p), p.read_text()) for p in cands]
    added, dup, bad = [], 0, 0
    for origin, text in sources:
        try:
            rep = prog.parse(text, origin)
        except prog.ReportError as e:
            print(f"error: {e}", file=sys.stderr)
            bad += 1
            continue
        key, new = prog.store(ws, rep)
        if new:
            added.append(rep)
            s = rep.get("score") or {}
            score = f"{s['right']}/{s['total']}" if "right" in s else ", ".join(f"{v} {k}" for k, v in s.items())
            print(f"imported {rep['kind']} '{rep['deck'].get('title') or rep['deck']['id']}' ({rep['finished_at'][:16]}){': ' + score if score else ''}")
        else:
            dup += 1
    print(f"done: {len(added)} new, {dup} already imported, {bad} rejected"
          + (" -> run `eztudy progress` and update wiki/learner.md" if added else ""))
    return 1 if bad else 0


def _report_wait(ws: Workspace, args) -> int:
    """Block until a served quiz is finished. If the headless grader handled it, print a short summary (for the
    learner profile); if it falls to the agent, claim it and print the grading packet."""
    import time

    headless = grading.fallback_command(ws) is not None
    start, deadline = time.time(), time.time() + args.timeout
    try:
        while time.time() < deadline:
            grading.heartbeat(ws)
            for job in grading.jobs(ws, "job"):
                if headless and not grading.agent_only(job):
                    continue  # the server's cheap grader takes it
                session = job.name.removesuffix(".job.json")
                if not grading.claim(ws, session, "agent"):
                    continue
                try:
                    pk = grading.packet(ws, grading.load_report(ws, session))
                except grading.GradingError as e:
                    grading.fail(ws, session, str(e))
                    continue
                print(f"grade session {session}: {len(pk['items'])} answer(s) from '{pk['deck'].get('title') or pk['deck']['id']}'"
                      f" ({pk['deck'].get('path') or 'deck file not found'})")
                print(grading.RULES)
                print(f"Then pipe the verdicts in: eztudy report grade {session} -   (the student is waiting on the results screen)")
                _print_json(pk)
                return 0
            for kind in ("result", "failed"):
                for f in grading.jobs(ws, kind):
                    if f.stat().st_mtime < start:
                        continue
                    session = f.name.removesuffix(f".{kind}.json")
                    if kind == "failed":
                        print(f"grading failed for session {session}: {grading.status(ws, session).get('error')}"
                              " (the student can self-grade in the page)")
                        return 0
                    r = grading.status(ws, session)
                    sc = r.get("score") or {}
                    print(f"session {session} graded by {r.get('grader')}: "
                          + ", ".join(f"{v['id']} {v['result']}" for v in r.get("items", []))
                          + (f"; score {sc['right']}/{sc['total']}" if "right" in sc else "")
                          + " -> run `eztudy progress --json` and update wiki/learner.md")
                    return 0
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        grading.clear_heartbeat(ws)
    print(f"no quiz submitted in {args.timeout}s")
    return 0


def _report_grade(ws: Workspace, args) -> int:
    try:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
        result = grading.apply(ws, args.session, json.loads(text), grader="agent")
    except (OSError, ValueError, grading.GradingError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    s = result["score"] or {}
    print(f"graded {len(result['items'])} answer(s): "
          + ", ".join(f"{v['id']} {v['result']}" for v in result["items"])
          + (f"; score now {s['right']}/{s['total']}" if "right" in s else "")
          + " -> the player shows the feedback now; run `eztudy progress --json` and update wiki/learner.md")
    return 0


def cmd_serve(ws: Workspace, args) -> int:
    import signal
    import webbrowser

    if args.stop:
        print("stopped" if serving.stop(ws) else "no server running for this notebook")
        return 0
    rel = ""
    if args.open:
        target = Path(args.open)
        target = (target if target.is_absolute() else (Path.cwd() / target if (Path.cwd() / target).exists() else ws.root / target)).resolve()
        if target.suffix == ".json":
            target = target.with_suffix(".html")
        if not target.is_file() or not target.is_relative_to(ws.study.resolve()):
            print(f"error: {args.open}: not a rendered page under study/ (run `eztudy render` first)", file=sys.stderr)
            return 1
        rel = target.relative_to(ws.root.resolve()).as_posix()
    st = serving.running(ws)
    if st:
        url = serving.page_url(st, rel)
        print(f"eztudy server already running: {url}")
        if rel and not args.no_browser:
            webbrowser.open(url)
        return 0
    srv = serving.Server(ws, port=args.port)
    url = serving.page_url(srv.state(), rel)
    fb = (f"{Path(srv.fallback[0]).name} headless" + (f" ({srv.fallback[srv.fallback.index('--model') + 1]})" if "--model" in srv.fallback else "")
          + ", else the agent session (`eztudy report wait`)") if srv.fallback else "agent session (`eztudy report wait`)"
    print(f"serving {ws.study} at {url}\ngrading: {fb}\nstop with `eztudy serve --stop`", flush=True)
    signal.signal(signal.SIGTERM, lambda *_: __import__("threading").Thread(target=srv.shutdown, daemon=True).start())
    if rel and not args.no_browser:
        webbrowser.open(url)
    try:
        srv.run()
    except KeyboardInterrupt:
        pass
    return 0


def _schedule(ws: Workspace, deck: str | None = None, now: str | None = None) -> list[dict]:
    retention, max_days = srs.settings(ws.config)
    return srs.schedule(prog.load_all(ws), srs.parse_time(now) if now else None, deck, retention, max_days)


def _ago(days: float) -> str:
    d = abs(days)
    span = f"{d * 24:.0f}h" if d < 1 else f"{d:.0f}d"
    return f"{span} overdue" if days >= 0 else f"in {span}"


def cmd_due(ws: Workspace, args) -> int:
    sched = _schedule(ws, args.deck, args.now)
    items = srs.due(sched, args.days)
    if args.topic:
        items = [c for c in items if args.topic in c["topics"]]
    if args.json:
        _print_json({**srs.due_summary(sched), "items": items[: args.limit]})
        return 0
    if not sched:
        print("nothing scheduled yet: finish a quiz or deck in the player (reports feed the schedule)")
        return 0
    summ = srs.due_summary(sched)
    print(f"{summ['due_now']} of {summ['tracked']} reviewed items due now"
          + (f"; {summ['due_tomorrow']} more by tomorrow" if summ["due_tomorrow"] else "")
          + (f"; next at {summ['next_due'][:16].replace('T', ' ')}" if not summ["due_now"] and summ["next_due"] else ""))
    for c in items[: args.limit]:
        kind = "card" if c["kind"] == "flashcards" else "quiz"
        print(f"  {_ago(c['overdue_days']):<13} recall {c['retrievability']:.0%}  {kind}  [{c['deck']} / {c['id']}] {c['prompt'][:80]}")
    if len(items) > args.limit:
        print(f"  … {len(items) - args.limit} more (--limit)")
    if summ["due_now"]:
        print("-> `eztudy review` builds a review session from these")
    return 0


def cmd_review(ws: Workspace, args) -> int:
    now = srs.parse_time(args.now) if args.now else srs.now_utc()
    sched = _schedule(ws, args.deck, args.now)
    picked = srs.due(sched)
    if args.topic:
        picked = [c for c in picked if args.topic in c["topics"]]
    picked.sort(key=lambda c: (c["retrievability"], c["due"]))  # least likely to be remembered first
    picked = picked[: args.limit]
    if not picked:
        summ = srs.due_summary(sched)
        print("nothing due for review" + (f"; next at {summ['next_due'][:16].replace('T', ' ')}" if summ["next_due"] else ""))
        return 0
    day = now.astimezone().date().isoformat()
    decks, skipped = srs.review_decks(ws, picked, day)
    for s in skipped:
        print(f"skipped [{s['deck']} / {s['id']}]: {s['reason']}", file=sys.stderr)
    if not decks:
        print("error: none of the due items could be found in their decks under study/", file=sys.stderr)
        return 1
    out = Path(args.output) if args.output else ws.study / srs.REVIEW_DIR
    out = out if out.is_absolute() else ws.root / out
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for kind, data in decks.items():
        path = out / f"{data['id']}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        paths.append(path)
        print(f"wrote {path.relative_to(ws.root) if path.is_relative_to(ws.root) else path} "
              f"({len(data['items'])} {'card' if kind == 'flashcards' else 'question'}{'s' if len(data['items']) != 1 else ''})")
    rc = render_files(ws, paths)
    st = serving.state_path(ws).exists() and serving.running(ws)
    for path in paths:
        html = path.with_suffix(".html")
        if st and html.resolve().is_relative_to(ws.study.resolve()):
            print(f"open: {serving.page_url(st, html.resolve().relative_to(ws.root.resolve()).as_posix())}")
    if not st:
        rel = paths[0].with_suffix(".html")
        print(f"-> `eztudy serve --open {rel.relative_to(ws.root) if rel.is_relative_to(ws.root) else rel}` so the results come back")
    return rc


def cmd_progress(ws: Workspace, args) -> int:
    summary = prog.summarize(prog.load_all(ws), args.deck)
    summary["due"] = srs.due_summary(_schedule(ws, args.deck))
    if args.json:
        _print_json(summary)
        return 0
    if not summary["reports"]:
        print("no performance reports yet. Finish a quiz or deck in the player, Save report, then `eztudy report import`.")
        return 0
    print(f"{summary['reports']} sessions, last {summary['last_session'][:16]}")
    print("\nmastery by topic (weakest first):")
    for t in summary["topics"]:
        bar = "#" * round(t["mastery"] * 10)
        print(f"  {t['status']:<8} {bar:<10} {t['mastery']:.0%}  {t['topic']}  ({t['correct']}/{t['seen']}, last {t['last']})")
    if summary["problem_items"]:
        print("\nproblem items:")
        for p in summary["problem_items"][: args.limit]:
            flag = "still missing" if p["still_missing"] else "recovered"
            print(f"  [{p['deck']} / {p['id']}] missed {p['misses']}/{p['attempts']}, {flag}: {p['prompt'][:90]}")
            for w in p["wrong_answers"][:2]:
                print(f"      picked: {w['answer'][:80]} (x{w['count']})")
    d = summary["due"]
    print(f"\nreview: {d['due_now']} of {d['tracked']} items due now" + (" -> `eztudy due`, `eztudy review`" if d["due_now"] else ""))
    return 0


# --- dashboard ----------------------------------------------------------------------


def cmd_dash(ws: Workspace, args) -> int:
    from . import insights

    info = insights.build(ws, srs.parse_time(args.now) if args.now else None)
    if args.json:
        _print_json(info)
        return 0
    from . import dash

    from . import prefs

    dash.set_palette(prefs.tui_theme(ws.config))
    dash.render(info)
    return 0


def cmd_tui(ws: Workspace, args) -> int:
    try:
        from . import tui
    except ImportError:
        print("the interactive dashboard needs the `tui` extra: pip install 'eztudy[tui]' "
              "(in a checkout: uv sync --extra tui). Showing the static dashboard instead.\n", file=sys.stderr)
        args.json, args.now = False, None
        return cmd_dash(ws, args)
    if args.command:
        print(tui.launch_command(ws, args.theme))
        return 0
    if args.open:
        print(tui.open_beside(ws, args.theme))
        return 0
    if not sys.stdout.isatty():
        print("eztudy tui needs an interactive terminal; use `eztudy tui --open` to start it beside this one, "
              "or `eztudy dash` here", file=sys.stderr)
        return 2
    from . import prefs

    tui.run(ws, args.theme or prefs.tui_theme(ws.config))
    return 0


def _statusline_cwd() -> str | None:
    """Claude Code pipes JSON with the session's directory to the status-line command."""
    import select

    if sys.stdin is None or sys.stdin.isatty():
        return None
    try:
        if not select.select([sys.stdin], [], [], 0.2)[0]:
            return None
        data = json.loads(sys.stdin.read() or "{}")
    except (OSError, ValueError):
        return None
    ws_info = data.get("workspace") if isinstance(data, dict) else None
    cwd = (ws_info or {}).get("current_dir") if isinstance(ws_info, dict) else None
    return cwd or (data.get("cwd") if isinstance(data, dict) else None)


def cmd_statusline(args) -> int:
    """Never fails loudly: a status line shows whatever this prints, so errors print nothing."""
    if args.install:
        return _install_statusline(args)
    try:
        from . import insights

        ws = find_workspace(args.root or _statusline_cwd())
        print(insights.status_line(insights.build(ws, quick=True)))
    except Exception:  # noqa: BLE001 - outside a notebook or on any error: empty status line
        pass
    return 0


def _install_statusline(args) -> int:
    import shlex
    import shutil

    try:
        ws = find_workspace(args.root)
    except WorkspaceError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    exe = Path(sys.argv[0]).resolve() if sys.argv and Path(sys.argv[0]).name == "eztudy" else None
    exe = str(exe) if exe and exe.exists() else shutil.which("eztudy")
    if not exe:
        print("error: can't find the eztudy executable on PATH", file=sys.stderr)
        return 1
    want = {"type": "command", "command": f"{shlex.quote(exe)} statusline"}
    path = ws.root / ".claude" / "settings.json"
    try:
        settings = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        print(f"error: {path} is not valid JSON; fix it first", file=sys.stderr)
        return 1
    cur = settings.get("statusLine")
    if cur == want:
        print(f"already installed in {path}")
        return 0
    if cur and not args.force:
        print(f"{path} already has a statusLine: {json.dumps(cur)}\nre-run with --force to replace it", file=sys.stderr)
        return 1
    settings["statusLine"] = want
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"set statusLine in {path}:\n  {json.dumps(want)}\nClaude Code sessions in this notebook now show it (restart open sessions).")
    return 0


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
    s.add_argument("--theme", choices=rendering.SKINS,
                   help="default skin of the HTML player (viewers can switch in the page); default: [ui] theme or focus")
    s = sub.add_parser("report", help="performance reports saved by the quiz/flashcard player")
    rsub = s.add_subparsers(dest="report_cmd", required=True)
    r = rsub.add_parser("import", help="store *.eztudy-report.json files (default: scan study/ and ~/Downloads)")
    r.add_argument("files", nargs="*", help="report files, or - to read one from stdin")
    r = rsub.add_parser("wait", help="block until a served quiz needs grading; print the grading packet (run in background)")
    r.add_argument("--timeout", type=int, default=3600, help="seconds to wait (default 3600)")
    r = rsub.add_parser("grade", help="apply verdicts for a waiting session; the player shows them immediately")
    r.add_argument("session")
    r.add_argument("file", help="verdict JSON file, or - for stdin")

    s = sub.add_parser("serve", help="serve study/ on localhost: reports post themselves and answers get graded")
    s.add_argument("--open", help="rendered page (or its .json) under study/ to open in the browser")
    s.add_argument("--no-browser", action="store_true", help="print the URL only")
    s.add_argument("--port", type=int, default=0, help="port (default: a free one)")
    s.add_argument("--stop", action="store_true", help="stop this notebook's server")

    s = sub.add_parser("progress", help="mastery by topic and problem items, from imported reports")
    s.add_argument("--deck", help="only this deck id")
    s.add_argument("--limit", type=int, default=15, help="problem items to list (text output)")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("due", help="items the spaced-repetition schedule says to review now")
    s.add_argument("--deck", help="only this deck id")
    s.add_argument("--topic", help="only items with this topic or tag")
    s.add_argument("--days", type=float, default=0, help="also list items due within this many days")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--json", action="store_true")
    s.add_argument("--now", help=argparse.SUPPRESS)

    s = sub.add_parser("dash", help="dashboard: what to study next, mastery, misses, reviews due, decks")
    s.add_argument("--json", action="store_true", help="the same data as JSON (for the agent)")
    s.add_argument("--now", help=argparse.SUPPRESS)

    s = sub.add_parser("tui", help="live, interactive dashboard for a terminal pane (needs the `tui` extra)")
    s.add_argument("--open", action="store_true", help="start it beside this terminal (tmux split or a new Terminal window)")
    s.add_argument("--command", action="store_true", help="print a shell command that starts it from any terminal")
    s.add_argument("--theme", help="panchi, panchi-light, or any Textual theme (default: [ui] tui_theme, else textual-dark)")

    s = sub.add_parser("statusline", help="one-line summary for Claude Code's status line (reads its JSON on stdin)")
    s.add_argument("--install", action="store_true", help="set it as the status line in this notebook's .claude/settings.json")
    s.add_argument("--force", action="store_true", help="with --install: replace an existing statusLine")

    s = sub.add_parser("review", help="build and render a review quiz/deck from the items due now")
    s.add_argument("--deck", help="only this deck id")
    s.add_argument("--topic", help="only items with this topic or tag")
    s.add_argument("--limit", type=int, default=20, help="most items in the session (least remembered first)")
    s.add_argument("-o", "--output", help="directory for the review files (default: study/review/)")
    s.add_argument("--now", help=argparse.SUPPRESS)
    return ap


COMMANDS = {
    "status": cmd_status, "add": cmd_add, "sync": cmd_sync, "index": cmd_index, "search": cmd_search,
    "show": cmd_show, "coverage": cmd_coverage, "sources": cmd_sources, "wiki": cmd_wiki, "render": cmd_render,
    "report": cmd_report, "progress": cmd_progress, "serve": cmd_serve,
    "due": cmd_due, "review": cmd_review, "dash": cmd_dash, "tui": cmd_tui,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "statusline":  # finds its notebook from Claude Code's JSON, and must never print an error
        return cmd_statusline(args)
    try:
        ws = find_workspace(args.root)
    except WorkspaceError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return COMMANDS[args.cmd](ws, args) or 0


if __name__ == "__main__":
    sys.exit(main())
