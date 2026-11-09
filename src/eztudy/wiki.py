"""Wiki-mode bookkeeping: page discovery, link graph and lint.

The agent writes the wiki; this module only checks it. Conventions live in
references/wiki.md.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .workspace import Workspace

LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
FENCE_RE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
SPECIAL = {"index", "log"}
CID_CITE_RE = re.compile(r"\b([0-9a-f]{8}):\d+\b")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


@dataclass
class Page:
    path: Path
    rel: str  # relative to wiki/, without .md
    meta: dict
    body: str
    links: list[str] = field(default_factory=list)

    @property
    def is_special(self) -> bool:
        return self.rel.lower() in SPECIAL


def split_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            try:
                meta = yaml.safe_load(text[4:end]) or {}
            except yaml.YAMLError:
                meta = {"__invalid__": True}
            nl = text.find("\n", end + 4)
            return (meta if isinstance(meta, dict) else {"__invalid__": True}), text[nl + 1 if nl != -1 else len(text):]
    return {}, text


def load_pages(ws: Workspace) -> list[Page]:
    pages = []
    if not ws.wiki.is_dir():
        return pages
    for path in sorted(ws.wiki.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(ws.wiki).parts):
            continue
        meta, body = split_frontmatter(path.read_text(errors="replace"))
        links = [m.group(1).strip() for m in LINK_RE.finditer(FENCE_RE.sub("", body))]
        rel = path.relative_to(ws.wiki).with_suffix("").as_posix()
        pages.append(Page(path, rel, meta, body, links))
    return pages


class Resolver:
    """Resolve [[links]] by relative path, then by unique file stem, then by title (all slug-insensitive)."""

    def __init__(self, pages: list[Page]):
        self.by_rel = {slug(p.rel): p for p in pages}
        self.by_stem: dict[str, list[Page]] = {}
        for p in pages:
            self.by_stem.setdefault(slug(Path(p.rel).name), []).append(p)
            title = p.meta.get("title")
            if isinstance(title, str) and slug(title) != slug(Path(p.rel).name):
                self.by_stem.setdefault(slug(title), []).append(p)

    def resolve(self, target: str) -> Page | None:
        t = target.removesuffix(".md")
        if slug(t) in self.by_rel:
            return self.by_rel[slug(t)]
        cands = self.by_stem.get(slug(Path(t).name), [])
        return cands[0] if len(cands) >= 1 else None


def _source_entries(meta: dict) -> list[dict]:
    raw = meta.get("sources") or []
    if isinstance(raw, (str, dict)):
        raw = [raw]
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            out.append({"path": item})
        elif isinstance(item, dict) and item.get("path"):
            out.append(item)
    return out


def source_for_hash(sources: dict, prefix: str) -> str | None:
    """The tracked source whose content hash starts with `prefix` (first path if several share it)."""
    return next((rel for rel, e in sorted(sources.items()) if e.get("hash", "").startswith(prefix)), None)


def body_sources(body: str, sources: dict) -> set[str]:
    """Sources a page body cites inline: chunk ids like [3fa9c2d1:12], full paths, or unique basenames."""
    text = LINK_RE.sub(" ", FENCE_RE.sub(" ", body))
    found = set()
    for m in CID_CITE_RE.finditer(text):
        rel = source_for_hash(sources, m.group(1))
        if rel:
            found.add(rel)
    basenames: dict[str, list[str]] = {}
    for rel in sources:
        basenames.setdefault(Path(rel).name, []).append(rel)
    for rel in sources:
        names = [rel] + ([Path(rel).name] if len(basenames[Path(rel).name]) == 1 and "/" in rel else [])
        if any(re.search(r"(?<![\w/.-])(?:sources/)?" + re.escape(n) + r"(?![\w/-])", text) for n in names):
            found.add(rel)
    return found


def fix(ws: Workspace, manifest: dict, today: dt.date | None = None) -> list[dict]:
    """Repair frontmatter `sources:` mechanically. Never touches stale hashes (those need a re-read).

    Fills missing hashes, follows moved files by hash, and adds sources cited in the body.
    Only the YAML block is rewritten; the body is kept byte-for-byte.
    """
    sources = manifest.get("sources", {})
    today = today or dt.date.today()
    fixed = []
    for p in load_pages(ws):
        if p.is_special or p.meta.get("__invalid__"):
            continue
        raw = p.meta.get("sources") or []
        entries = [raw] if isinstance(raw, (str, dict)) else list(raw) if isinstance(raw, list) else []
        changes = []
        listed = set()
        for i, e in enumerate(entries):
            item = {"path": e} if isinstance(e, str) else e
            if not isinstance(item, dict) or not item.get("path"):
                continue
            spath = str(item["path"]).removeprefix("sources/")
            if spath not in sources and item.get("hash") is not None:
                moved = source_for_hash(sources, str(item["hash"]))
                if moved:
                    item = {**item, "path": moved}
                    changes.append(f"path {spath} -> {moved}")
                    spath = moved
            if spath in sources and item.get("hash") is None:
                item = {**item, "hash": sources[spath]["hash"][:8]}
                changes.append(f"hash for {spath}")
            if item is not e:
                entries[i] = item
            listed.add(spath)
        for rel in sorted(body_sources(p.body, sources) - listed):
            entries.append({"path": rel, "hash": sources[rel]["hash"][:8]})
            changes.append(f"added {rel} (cited in body)")
        if not changes:
            continue
        meta = dict(p.meta)
        meta["sources"] = entries
        meta["updated"] = today
        p.path.write_text("---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n" + p.body)
        fixed.append({"page": p.rel, "changes": changes})
    return fixed


def lint(ws: Workspace, manifest: dict) -> dict:
    pages = load_pages(ws)
    res = Resolver(pages)
    sources = manifest.get("sources", {})
    report: dict[str, list] = {
        "broken_links": [],
        "orphans": [],
        "missing_from_index": [],
        "uncited": [],
        "stale_citations": [],
        "unknown_sources": [],
        "invalid_frontmatter": [],
        "body_not_in_frontmatter": [],
        "uncovered_sources": [],
        "frontmatter_not_in_body": [],
    }
    if not pages:
        report["uncovered_sources"] = sorted(sources)
        return {"pages": 0, **report}

    inbound: dict[str, int] = {p.rel: 0 for p in pages}
    index = next((p for p in pages if p.rel.lower() == "index"), None)
    in_index: set[str] = set()
    cited: set[str] = set()

    for p in pages:
        if p.meta.get("__invalid__"):
            report["invalid_frontmatter"].append(p.rel)
        for target in p.links:
            hit = res.resolve(target)
            if hit is None:
                report["broken_links"].append({"page": p.rel, "link": target})
            elif hit is not p:
                inbound[hit.rel] += 1
                if p is index:
                    in_index.add(hit.rel)
        if p.is_special:
            continue
        entries = _source_entries(p.meta)
        if not entries:
            report["uncited"].append(p.rel)
        listed = {str(e["path"]).removeprefix("sources/") for e in entries}
        in_body = body_sources(p.body, sources)
        report["body_not_in_frontmatter"] += [{"page": p.rel, "source": s} for s in sorted(in_body - listed)]
        report["frontmatter_not_in_body"] += [{"page": p.rel, "source": s} for s in sorted(listed - in_body) if s in sources]
        for e in entries:
            spath = str(e["path"]).removeprefix("sources/")
            cited.add(spath)
            if spath not in sources:
                report["unknown_sources"].append({"page": p.rel, "source": spath})
            elif e.get("hash") and not sources[spath]["hash"].startswith(str(e["hash"])):
                report["stale_citations"].append({"page": p.rel, "source": spath})

    for p in pages:
        if p.is_special:
            continue
        if inbound[p.rel] == 0:
            report["orphans"].append(p.rel)
        if index is not None and p.rel not in in_index:
            report["missing_from_index"].append(p.rel)
    if index is None:
        report["missing_from_index"] = ["(wiki/index.md does not exist)"]

    report["uncovered_sources"] = sorted(s for s in sources if s not in cited and sources[s].get("status") != "unsupported")
    return {"pages": len(pages), **report}


INFO_KEYS = {"uncovered_sources", "frontmatter_not_in_body"}  # worth a look, but not lint failures


def lint_ok(report: dict) -> bool:
    keys = ["broken_links", "orphans", "missing_from_index", "uncited", "stale_citations", "unknown_sources",
            "invalid_frontmatter", "body_not_in_frontmatter"]
    return not any(report[k] for k in keys)
