import sqlite3, time, uuid, re, json
from typing import Any, Dict, List, Optional
from contextlib import contextmanager
import config

@contextmanager
def _db_conn():
    """Context manager for SQLite connections with WAL mode for concurrency."""
    conn = sqlite3.connect(config.config.chat_db, timeout=10,
        check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    """Initialize the chats database schema."""
    with _db_conn() as db:
        db.execute("""
 CREATE TABLE IF NOT EXISTS chats (
 id TEXT PRIMARY KEY,
 title TEXT,
 created INTEGER,
 last_preview TEXT,
 archived INTEGER DEFAULT 0,
 pinned INTEGER DEFAULT 0,
 settings TEXT DEFAULT '{}',
 prefs TEXT DEFAULT '{}'
 );
 """)
        db.execute("""
 CREATE TABLE IF NOT EXISTS messages (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 chat_id TEXT, role TEXT, content TEXT, model TEXT,
 timestamp INTEGER, meta_json TEXT,
 FOREIGN KEY(chat_id) REFERENCES chats(id)
 );
 """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_msg_chat ON messages(chat_id);")
        db.execute("""
 CREATE TABLE IF NOT EXISTS tags (
 chat_id TEXT, tag TEXT,
 UNIQUE(chat_id, tag),
 FOREIGN KEY(chat_id) REFERENCES chats(id)
 );
 """)

def list_chats(include_archived: bool = False, query: Optional[str] = None, tag: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Return a list of chats, optionally filtered by archived or search term or
    tag.
    """
    with _db_conn() as db:
        args = []
        conds = []
        if not include_archived:
            conds.append("archived = 0")
        if query:
            conds.append("title LIKE ?")
            args.append(f"%{query}%")
        if tag:
            # join with tags table for filtering
            conds.append("id IN (SELECT chat_id FROM tags WHERE tag = ?)")
            args.append(tag)
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        rows = db.execute(f"SELECT id, title, created, last_preview, archived, pinned FROM chats {where}").fetchall()
        chats = []
        for r in rows:
            chats.append({
                "id": r["id"],
                "title": r["title"],
                "created": r["created"],
                "last_preview": r["last_preview"],
                "archived": bool(r["archived"]),
                "pinned": bool(r["pinned"])
            })
        return chats

def create_chat(title: str) -> Dict[str, Any]:
    """
    Create a new chat with a unique ID and return its data.
    """
    chat_id = uuid.uuid4().hex
    ts = int(time.time())
    with _db_conn() as db:
        db.execute("INSERT INTO chats (id, title, created, last_preview) VALUES (?, ?, ?, ?)",
            (chat_id, title, ts, ""))
        return {"id": chat_id, "title": title, "created": ts, "archived": False, "pinned": False}

def get_chat(chat_id: str, limit: int = 1000, offset: int = 0) -> Dict[str, Any]:
    """
    Retrieve chat metadata and messages up to a limit.
    """
    with _db_conn() as db:
        chat = db.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if not chat:
            raise KeyError("chat not found")
        msgs = []
        rows = db.execute(
            "SELECT id, role, content, model, timestamp, meta_json FROM messages " "WHERE chat_id = ? ORDER BY id ASC LIMIT ? OFFSET ?",
            (chat_id, limit, offset)
        ).fetchall()
        for r in rows:
            msgs.append({
                "id": r["id"],
                "role": r["role"],
                "content": r["content"],
                "model": r["model"],
                "timestamp": r["timestamp"],
                "meta_json": json.loads(r["meta_json"]) if r["meta_json"] else {}
            })
        return {"chat": {"id": chat_id, "title": chat["title"], "archived":
            bool(chat["archived"]), "pinned": bool(chat["pinned"])}, "messages": msgs}

def rename_chat(chat_id: str, title: str) -> None:
    """Change a chat's title."""
    with _db_conn() as db:
        res = db.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))
        if res.rowcount == 0:
            raise KeyError("chat not found")

def set_archived(chat_id: str, archived: bool) -> None:
    """Archive or unarchive a chat."""
    with _db_conn() as db:
        res = db.execute("UPDATE chats SET archived = ? WHERE id = ?", (1 if archived else 0, chat_id))
        if res.rowcount == 0:
            raise KeyError("chat not found")

def set_pinned(chat_id: str, pinned: bool) -> None:
    """Pin or unpin a chat."""
    with _db_conn() as db:
        res = db.execute("UPDATE chats SET pinned = ? WHERE id = ?", (1 if pinned else 0, chat_id))
        if res.rowcount == 0:
            raise KeyError("chat not found")

def append_messages(chat_id: str, messages: List[Dict[str, Any]]) -> None:
    """
    Insert new messages into a chat and update its last preview.
    """
    now = int(time.time())
    with _db_conn() as db:
        # Ensure chat exists
        chat = db.execute("SELECT 1 FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if not chat:
            raise KeyError("chat not found")
        for msg in messages:
            db.execute(
                "INSERT INTO messages (chat_id, role, content, model, timestamp, meta_json) VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, msg.get("role"), msg.get("content"), msg.get("model"), now, json.dumps(msg.get("meta_json") or {}))
            )
        # Update last_preview text (for display in chat list)
        last_preview = messages[-1].get("content", "")[:100] if messages else ""
        db.execute("UPDATE chats SET last_preview = ? WHERE id = ?", (last_preview, chat_id))

def clear_chat(chat_id: str) -> None:
    """Delete all messages from a chat."""
    with _db_conn() as db:
        res = db.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        if res.rowcount is None:
            raise KeyError("chat not found")
        db.execute("UPDATE chats SET last_preview = '' WHERE id = ?", (chat_id,))

def delete_chat(chat_id: str) -> None:
    """Delete a chat and its messages (and tags)."""
    with _db_conn() as db:
        db.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        db.execute("DELETE FROM tags WHERE chat_id = ?", (chat_id,))
        res = db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        if res.rowcount == 0:
            raise KeyError("chat not found")

def list_tags(chat_id: str) -> List[str]:
    """List all tags associated with a chat."""
    with _db_conn() as db:
        db.execute("SELECT 1 FROM chats WHERE id = ?", (chat_id,)).fetchone() or (_ for _ in ()).throw(KeyError("chat not found"))
        rows = db.execute("SELECT tag FROM tags WHERE chat_id = ?", (chat_id,)).fetchall()
        return [r["tag"] for r in rows]

def add_tag(chat_id: str, tag: str) -> None:
    """Add a tag to a chat."""
    if not re.match(r"^[\w-]+$", tag):
        raise ValueError("Invalid tag format")
    with _db_conn() as db:
        db.execute("INSERT OR IGNORE INTO tags (chat_id, tag) VALUES (?, ?)", (chat_id, tag))

def remove_tag(chat_id: str, tag: str) -> None:
    """Remove a tag from a chat."""
    with _db_conn() as db:
        db.execute("DELETE FROM tags WHERE chat_id = ? AND tag = ?", (chat_id, tag))

def toggle_pinned(chat_id: str) -> Dict[str, Any]:
    """Toggle the pinned flag and return the new state."""
    with _db_conn() as db:
        row = db.execute("SELECT pinned FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if not row:
            raise KeyError("chat not found")
        new = 0 if row["pinned"] else 1
        db.execute("UPDATE chats SET pinned = ? WHERE id = ?", (new, chat_id))
        return {"archived": bool(row["pinned"]), "pinned": bool(new)}

def toggle_archived(chat_id: str) -> Dict[str, Any]:
    """Toggle the archived flag and return the new state."""
    with _db_conn() as db:
        row = db.execute("SELECT archived FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if not row:
            raise KeyError("chat not found")
        new = 0 if row["archived"] else 1
        db.execute("UPDATE chats SET archived = ? WHERE id = ?", (new, chat_id))
        return {"archived": bool(new), "pinned": bool(row["archived"])}

def get_prefs(chat_id: str) -> Dict[str, Any]:
    """Get per-chat preferences (for RAG)."""
    with _db_conn() as db:
        row = db.execute("SELECT prefs FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if not row:
            raise KeyError("chat not found")
        return json.loads(row["prefs"] or "{}")

def set_prefs(chat_id: str, rag_enabled: Optional[bool], doc_ids: Any) -> None:
    """Set per-chat RAG preferences."""
    prefs = get_prefs(chat_id)
    if rag_enabled is not None:
        prefs["rag_enabled"] = bool(rag_enabled)
    if doc_ids is not None and doc_ids != "__nochange__":
        prefs["doc_ids"] = doc_ids if isinstance(doc_ids, list) else []
    with _db_conn() as db:
        db.execute("UPDATE chats SET prefs = ? WHERE id = ?", (json.dumps(prefs), chat_id))

def get_settings(chat_id: str) -> Dict[str, Any]:
    """Retrieve chat-specific settings (model, temp, etc.)."""
    with _db_conn() as db:
        row = db.execute("SELECT settings FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if not row:
            raise KeyError("chat not found")
        return json.loads(row["settings"] or "{}")

def set_settings(chat_id: str, **kwargs) -> None:
    """Update chat-specific settings; only provided keys are changed."""
    settings = get_settings(chat_id)
    for k, v in kwargs.items():
        if v is not None:
            settings[k] = v
    with _db_conn() as db:
        db.execute("UPDATE chats SET settings = ? WHERE id = ?", (json.dumps(settings), chat_id))

async def update_message_content_async(chat_id: str, msg_id: int, new_content: str):
    """Asynchronously update a message's content."""
    with _db_conn() as db:
        res = db.execute(
            "UPDATE messages SET content = ? WHERE chat_id = ? AND id = ?", (new_content, chat_id, msg_id)
        )
        if res.rowcount == 0:
            raise KeyError("message not found")

async def trim_after_async(chat_id: str, msg_id: int):
    """Delete all messages after a given ID in a chat."""
    with _db_conn() as db:
        db.execute("DELETE FROM messages WHERE chat_id = ? AND id > ?", (chat_id, msg_id))

def export_chat_markdown(chat_id: str) -> str:
    """Return the entire chat as a Markdown-formatted string."""
    data = get_chat(chat_id, limit=1000000, offset=0)
    lines = []
    for m in data["messages"]:
        prefix = "**User:** " if m["role"] == "user" else "**Assistant:** " if m["role"] == "assistant" else "**System:** "
        lines.append(f"{prefix}{m['content']}")
    return "\n\n".join(lines)

def search_messages(query: str, chat_id: str | None = None, limit: int = 25, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Perform a simple substring search over messages (for demo purposes).
    """
    with _db_conn() as db:
        if chat_id:
            rows = db.execute(
                "SELECT chat_id, id, role, content FROM messages WHERE chat_id = ? AND content LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (chat_id, f"%{query}%", limit, offset)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT chat_id, id, role, content FROM messages WHERE content LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (f"%{query}%", limit, offset)
            ).fetchall()
        return [{"chat_id": r["chat_id"], "id": r["id"], "role": r["role"], "content": r["content"]} for r in rows]

def fork_chat(chat_id: str, msg_id: int) -> Dict[str, Any]:
    """
    Fork a chat: create a new chat containing messages up to msg_id from the original.
    """
    original = get_chat(chat_id, limit=msg_id, offset=0)
    title = original["chat"]["title"] + " (fork)"
    new_chat = create_chat(title)
    for m in original["messages"]:
        append_messages(new_chat["id"], [{
            "role": m["role"],
            "content": m["content"],
            "model": m.get("model"),
            "meta_json": m.get("meta_json")
        }])
    return new_chat