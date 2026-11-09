"""Wiki-mode bookkeeping: page discovery, link graph and lint.

The agent writes the wiki; this module only checks it. Conventions live in
references/wiki.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .workspace import Workspace

LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
FENCE_RE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
SPECIAL = {"index", "log"}


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
        "uncovered_sources": [],
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


def lint_ok(report: dict) -> bool:
    keys = ["broken_links", "orphans", "missing_from_index", "uncited", "stale_citations", "unknown_sources", "invalid_frontmatter"]
    return not any(report[k] for k in keys)
