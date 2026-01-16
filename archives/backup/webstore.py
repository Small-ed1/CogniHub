from __future__ import annotations
import sqlite3, time
from contextlib import contextmanager
import config
import httpx
from urllib.parse import urlparse

@contextmanager
def _db_conn():
    conn = sqlite3.connect(config.config.web_db, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    """Initialize web caching DB."""
    with _db_conn() as db:
        db.execute("""
CREATE TABLE IF NOT EXISTS pages (
url TEXT PRIMARY KEY,
content TEXT,
timestamp INTEGER
);
""")
        db.execute("""
CREATE TABLE IF NOT EXISTS chunks (
id INTEGER PRIMARY KEY AUTOINCREMENT,
url TEXT,
text TEXT,
FOREIGN KEY(url) REFERENCES pages(url)
);
""")

async def fetch_and_cache(url: str) -> str:
    """
    Fetch a webpage (with SSRF protection) and cache its text.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    # SSRF check: Only allow certain hosts from config (if set)
    allowed = config.config.web_allowed_hosts.split(",")
    blocked = config.config.web_blocked_hosts.split(",")
    if blocked and any(b in host for b in blocked):
        raise ValueError("Host is blocked")
    if allowed and not any(a in host for a in allowed):
        raise ValueError("Host not allowed")
    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers={"User-Agent": config.config.web_user_agent}, timeout=10.0)
        res.raise_for_status()
        text = res.text
        now = int(time.time())
        with _db_conn() as db:
            db.execute("INSERT OR REPLACE INTO pages (url, content, timestamp) VALUES (?, ?, ?)", (url, text, now))
            # Optionally split into chunks, here store whole page as one chunk
            db.execute("DELETE FROM chunks WHERE url = ?", (url,))
            db.execute("INSERT INTO chunks (url, text) VALUES (?, ?)", (url, text))
        return text

def get_cached_page(url: str) -> str | None:
    """Retrieve cached page content if it exists."""
    with _db_conn() as db:
        row = db.execute("SELECT content FROM pages WHERE url = ?", (url,)).fetchone()
        return row["content"] if row else None