from __future__ import annotations
import sqlite3, os, time
from contextlib import contextmanager
from typing import Any, List
import uuid
import config
import numpy as np

# Attempt to use a real embedding model; fallback to random vectors for demo
try:
    from some_vector_library import embed_text
except ImportError:
    def embed_text(text: str) -> List[float]:
        return list(np.random.rand(128))  # random 128-dim vector

@contextmanager
def _db_conn():
    conn = sqlite3.connect(config.config.rag_db, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    """Initialize RAG document storage schema."""
    with _db_conn() as db:
        db.execute("""
CREATE TABLE IF NOT EXISTS documents (
id INTEGER PRIMARY KEY AUTOINCREMENT,
filename TEXT,
text TEXT,
created INTEGER,
weight REAL DEFAULT 1.0,
group_name TEXT DEFAULT ''
);
""")
        db.execute("""
CREATE TABLE IF NOT EXISTS chunks (
id INTEGER PRIMARY KEY AUTOINCREMENT,
doc_id INTEGER,
text TEXT,
embedding BLOB,
FOREIGN KEY(doc_id) REFERENCES documents(id)
);
""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);")

def list_documents() -> List[dict]:
    """Return metadata about all documents."""
    with _db_conn() as db:
        rows = db.execute("SELECT id, filename, weight, group_name FROM documents").fetchall()
        return [{"id": r["id"], "filename": r["filename"], "weight": r["weight"], "group": r["group_name"]} for r in rows]

def add_document(filename: str, text: str) -> int:
    """
    Store a document and create simple chunks with embeddings.
    """
    created = int(time.time())
    with _db_conn() as db:
        res = db.execute(
            "INSERT INTO documents (filename, text, created) VALUES (?, ?, ?)",
            (filename, text, created)
        )
        doc_id = res.lastrowid
        # Naive splitting: 1000 chars per chunk
        for i in range(0, len(text), 1000):
            chunk_text = text[i:i+1000]
            emb = embed_text(chunk_text)
            emb_blob = sqlite3.Binary(bytes((float(x) for x in emb)))
            db.execute("INSERT INTO chunks (doc_id, text, embedding) VALUES (?, ?, ?)",
                (doc_id, chunk_text, emb_blob))
        return doc_id

def delete_document(doc_id: int) -> None:
    """Delete a document and its chunks."""
    with _db_conn() as db:
        db.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

def update_document(doc_id: int, weight: float | None = None, group_name: str | None = None, filename: str | None = None):
    """Update document metadata."""
    with _db_conn() as db:
        cols, args = [], []
        if weight is not None:
            cols.append("weight = ?")
            args.append(weight)
        if group_name is not None:
            cols.append("group_name = ?")
            args.append(group_name)
        if filename is not None:
            cols.append("filename = ?")
            args.append(filename)
        if not cols:
            return
        args.append(doc_id)
        db.execute(f"UPDATE documents SET {', '.join(cols)} WHERE id = ?", args)

def get_chunk(chunk_id: int) -> dict:
    """Retrieve a chunk by ID."""
    with _db_conn() as db:
        row = db.execute("SELECT text FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        if not row:
            raise KeyError("chunk not found")
        return {"id": chunk_id, "text": row["text"]}

def get_neighbors(chunk_id: int, span: int = 1) -> dict:
    """Return up to `span` previous and next chunks for a given chunk."""
    with _db_conn() as db:
        row = db.execute("SELECT doc_id, id FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        if not row:
            raise KeyError("chunk not found")
        doc_id, _ = row["doc_id"], row["id"]
        prev_rows = db.execute(
            "SELECT id, text FROM chunks WHERE doc_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
            (doc_id, chunk_id, span)
        ).fetchall()
        next_rows = db.execute(
            "SELECT id, text FROM chunks WHERE doc_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
            (doc_id, chunk_id, span)
        ).fetchall()
        return {
            "prev": [{"id": r["id"], "text": r["text"]} for r in reversed(prev_rows)],
            "next": [{"id": r["id"], "text": r["text"]} for r in next_rows]
        }