"""SQLite index: documents, chunks, sqlite-vec vectors and FTS5, with hybrid search.

Chunk ids are stable, human-citable strings: `<first 8 chars of doc hash>:<ord>`,
e.g. `3fa9c2d1:12`. They only change if the source's content changes.
"""

from __future__ import annotations

import json
import re
import sqlite3
import struct
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .chunk import Chunk

RRF_K = 60


def connect(path: Path) -> sqlite3.Connection:
    import sqlite_vec

    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    if not hasattr(db, "enable_load_extension"):
        raise RuntimeError(
            "This Python's sqlite3 cannot load extensions (needed for sqlite-vec). "
            "Use a uv-managed or Homebrew Python."
        )
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS documents (
            hash TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            title TEXT,
            chars INTEGER,
            indexed_at REAL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            cid TEXT UNIQUE NOT NULL,
            doc_hash TEXT NOT NULL REFERENCES documents(hash) ON DELETE CASCADE,
            ord INTEGER NOT NULL,
            heading TEXT,
            loc_kind TEXT,
            loc_start INTEGER,
            loc_end INTEGER,
            text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_hash);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, heading, tokenize='porter unicode61');
        """
    )
    return db


def get_meta(db, key: str) -> str | None:
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(db, key: str, value: str) -> None:
    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))


def ensure_vec_table(db, model: str, dim: int) -> bool:
    """Create the vector table for this model. Returns True if a rebuild was forced."""
    current_model = get_meta(db, "embedding_model")
    rebuilt = False
    if current_model and (current_model != model or int(get_meta(db, "embedding_dim") or 0) != dim):
        reset(db)
        rebuilt = True
    db.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(embedding float[{dim}] distance_metric=cosine)"
    )
    set_meta(db, "embedding_model", model)
    set_meta(db, "embedding_dim", str(dim))
    db.commit()
    return rebuilt


def reset(db) -> None:
    db.execute("DROP TABLE IF EXISTS chunks_vec")
    db.execute("DELETE FROM chunks_fts")
    db.execute("DELETE FROM chunks")
    db.execute("DELETE FROM documents")
    db.execute("DELETE FROM meta WHERE key IN ('embedding_model', 'embedding_dim')")
    db.commit()


def _blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def indexed_docs(db) -> dict[str, str]:
    return {r["hash"]: r["path"] for r in db.execute("SELECT hash, path FROM documents")}


def delete_doc(db, doc_hash: str) -> None:
    ids = [r["id"] for r in db.execute("SELECT id FROM chunks WHERE doc_hash=?", (doc_hash,))]
    for i in ids:
        db.execute("DELETE FROM chunks_vec WHERE rowid=?", (i,))
        db.execute("DELETE FROM chunks_fts WHERE rowid=?", (i,))
    db.execute("DELETE FROM chunks WHERE doc_hash=?", (doc_hash,))
    db.execute("DELETE FROM documents WHERE hash=?", (doc_hash,))


def update_path(db, doc_hash: str, path: str) -> None:
    db.execute("UPDATE documents SET path=? WHERE hash=?", (path, doc_hash))


def add_doc(db, doc_hash: str, path: str, title: str, text_len: int, chunks: list[Chunk], vectors: list[list[float]]) -> None:
    delete_doc(db, doc_hash)
    db.execute(
        "INSERT INTO documents(hash, path, title, chars, indexed_at) VALUES (?,?,?,?,?)",
        (doc_hash, path, title, text_len, time.time()),
    )
    for c, v in zip(chunks, vectors, strict=True):
        cur = db.execute(
            "INSERT INTO chunks(cid, doc_hash, ord, heading, loc_kind, loc_start, loc_end, text) VALUES (?,?,?,?,?,?,?,?)",
            (f"{doc_hash[:8]}:{c.ord}", doc_hash, c.ord, c.heading, c.loc_kind, c.loc_start, c.loc_end, c.text),
        )
        rowid = cur.lastrowid
        db.execute("INSERT INTO chunks_fts(rowid, text, heading) VALUES (?,?,?)", (rowid, c.text, c.heading))
        db.execute("INSERT INTO chunks_vec(rowid, embedding) VALUES (?, ?)", (rowid, _blob(v)))


@dataclass
class Hit:
    cid: str
    path: str
    title: str
    heading: str
    location: str
    score: float
    text: str

    @property
    def citation(self) -> str:
        return f"{self.path}" + (f" ({self.location})" if self.location else "")

    def to_dict(self) -> dict:
        from .extract import source_type

        d = asdict(self)
        d["type"] = source_type(self.path)
        d["citation"] = self.citation
        return d


def _location(row) -> str:
    if not row["loc_kind"]:
        return ""
    if row["loc_start"] == row["loc_end"]:
        return f"{row['loc_kind']} {row['loc_start']}"
    return f"{row['loc_kind']}s {row['loc_start']}-{row['loc_end']}"


def _fts_query(q: str) -> str:
    terms = re.findall(r"\w+", q.lower())
    return " OR ".join(f'"{t}"' for t in terms)


def search(db, query: str, query_vec: list[float] | None, k: int = 8, mode: str = "hybrid", path_prefix: str | None = None) -> list[Hit]:
    pool = max(k * 5, 30)
    ranks: dict[int, float] = {}

    if mode in ("hybrid", "vector") and query_vec is not None:
        rows = db.execute(
            "SELECT rowid, distance FROM chunks_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (_blob(query_vec), pool),
        ).fetchall()
        for rank, r in enumerate(rows):
            score = 1 / (RRF_K + rank) if mode == "hybrid" else 1 - r["distance"]
            ranks[r["rowid"]] = ranks.get(r["rowid"], 0) + score

    if mode in ("hybrid", "fts"):
        fq = _fts_query(query)
        if fq:
            rows = db.execute(
                "SELECT rowid, bm25(chunks_fts) AS s FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY s LIMIT ?",
                (fq, pool),
            ).fetchall()
            for rank, r in enumerate(rows):
                score = 1 / (RRF_K + rank) if mode == "hybrid" else -r["s"]
                ranks[r["rowid"]] = ranks.get(r["rowid"], 0) + score

    if not ranks:
        return []
    ids = list(ranks)
    rows = db.execute(
        f"""SELECT c.id, c.cid, c.heading, c.loc_kind, c.loc_start, c.loc_end, c.text, d.path, d.title
            FROM chunks c JOIN documents d ON d.hash = c.doc_hash
            WHERE c.id IN ({','.join('?' * len(ids))})""",
        ids,
    ).fetchall()
    hits = [
        Hit(r["cid"], r["path"], r["title"] or "", r["heading"] or "", _location(r), round(ranks[r["id"]], 6), r["text"])
        for r in rows
        if not path_prefix or r["path"].startswith(path_prefix)
    ]
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]


def get_chunk(db, cid: str, context: int = 0) -> list[Hit]:
    row = db.execute("SELECT doc_hash, ord FROM chunks WHERE cid=?", (cid,)).fetchone()
    if not row:
        return []
    rows = db.execute(
        """SELECT c.cid, c.heading, c.loc_kind, c.loc_start, c.loc_end, c.text, d.path, d.title
           FROM chunks c JOIN documents d ON d.hash = c.doc_hash
           WHERE c.doc_hash=? AND c.ord BETWEEN ? AND ? ORDER BY c.ord""",
        (row["doc_hash"], row["ord"] - context, row["ord"] + context),
    ).fetchall()
    return [Hit(r["cid"], r["path"], r["title"] or "", r["heading"] or "", _location(r), 0.0, r["text"]) for r in rows]


def stats(db) -> dict:
    return {
        "documents": db.execute("SELECT count(*) FROM documents").fetchone()[0],
        "chunks": db.execute("SELECT count(*) FROM chunks").fetchone()[0],
        "embedding_model": get_meta(db, "embedding_model"),
    }


def dump_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)
