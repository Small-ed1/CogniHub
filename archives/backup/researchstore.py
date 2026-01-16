from __future__ import annotations
import sqlite3, time, uuid
from contextlib import contextmanager
from typing import List
import config

@contextmanager
def _db_conn():
    conn = sqlite3.connect(config.config.research_db, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    """Initialize research DB."""
    with _db_conn() as db:
        db.execute("""
CREATE TABLE IF NOT EXISTS runs (
id TEXT PRIMARY KEY,
question TEXT,
created INTEGER,
status TEXT
);
""")
        db.execute("""
CREATE TABLE IF NOT EXISTS sources (
run_id TEXT,
ref_id TEXT,
title TEXT,
url TEXT,
pinned INTEGER DEFAULT 0,
excluded INTEGER DEFAULT 0,
PRIMARY KEY (run_id, ref_id)
);
""")

def create_run(question: str) -> str:
    """Start a new research run."""
    run_id = uuid.uuid4().hex
    now = int(time.time())
    with _db_conn() as db:
        db.execute("INSERT INTO runs (id, question, created, status) VALUES (?, ?, ?, ?)", (run_id, question, now, "running"))
    return run_id

def update_run_status(run_id: str, status: str):
    with _db_conn() as db:
        db.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))

def add_source(run_id: str, ref_id: str, title: str, url: str):
    """Add a source reference to a run."""
    with _db_conn() as db:
        db.execute("INSERT OR IGNORE INTO sources (run_id, ref_id, title, url) VALUES (?, ?, ?, ?)", (run_id, ref_id, title, url))

def get_sources(run_id: str) -> List[dict]:
    """Get sources for a run."""
    with _db_conn() as db:
        rows = db.execute("SELECT ref_id, title, url, pinned, excluded FROM sources WHERE run_id = ?", (run_id,)).fetchall()
        return [{"ref_id": r["ref_id"], "title": r["title"], "url": r["url"], "pinned": bool(r["pinned"]), "excluded": bool(r["excluded"])} for r in rows]

def update_source_flags(run_id: str, ref_id: str, pinned: bool = None, excluded: bool = None):
    """Update pinned/excluded flags for a source."""
    with _db_conn() as db:
        if pinned is not None:
            db.execute("UPDATE sources SET pinned = ? WHERE run_id = ? AND ref_id = ?", (1 if pinned else 0, run_id, ref_id))
        if excluded is not None:
            db.execute("UPDATE sources SET excluded = ? WHERE run_id = ? AND ref_id = ?", (1 if excluded else 0, run_id, ref_id))

def get_run_status(run_id: str) -> dict:
    """Get current status of a research run."""
    with _db_conn() as db:
        row = db.execute("SELECT question, status FROM runs WHERE id = ?", (run_id,)).fetchone()
        return {"run_id": run_id, "question": row["question"], "status": row["status"]} if row else None