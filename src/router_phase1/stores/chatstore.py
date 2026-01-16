import asyncio
import os, sqlite3, time, uuid, json, re
from typing import Any, Optional
from contextlib import contextmanager

CHAT_DB = os.getenv("CHAT_DB", os.path.join(os.path.dirname(__file__), "../data/chat.sqlite3"))

VALID_ROLES = {"system", "user", "assistant"}

def _now() -> int:
    return int(time.time())

def _conn():
    con = sqlite3.connect(CHAT_DB, timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA busy_timeout=5000;")
    con.execute("PRAGMA temp_store=MEMORY;")
    con.execute("PRAGMA cache_size=-20000;")
    return con

@contextmanager
def _db():
    con = _conn()
    try:
        yield con
        con.commit()
    finally:
        con.close()

def _get_user_version(con: sqlite3.Connection) -> int:
    return int(con.execute("PRAGMA user_version;").fetchone()[0] or 0)

def _set_user_version(con: sqlite3.Connection, v: int):
    con.execute(f"PRAGMA user_version={int(v)};")

def init_db():
    with _db() as con:
        v = _get_user_version(con)
        if v < 1:
            _migrate_1_baseline(con)
            _set_user_version(con, 1); v = 1
        if v < 2:
            _migrate_2_last_message_pointer(con)
            _set_user_version(con, 2); v = 2
        if v < 3:
            _migrate_3_fts(con)
            _set_user_version(con, 3); v = 3
        if v < 4:
            _migrate_4_prefs_and_forks(con)
            _set_user_version(con, 4); v = 4
        if v < 5:
            _migrate_5_tags_and_settings(con)
            _set_user_version(con, 5); v = 5
        if v < 6:
            _migrate_6_autosummary(con)
            _set_user_version(con, 6); v = 6
        if v < 7:
            _migrate_7_token_count(con)
            _set_user_version(con, 7); v = 7

def _migrate_1_baseline(con: sqlite3.Connection):
    con.execute("""
    CREATE TABLE IF NOT EXISTS chats (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL,
      archived INTEGER NOT NULL DEFAULT 0,
      pinned INTEGER NOT NULL DEFAULT 0
    );
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      chat_id TEXT NOT NULL,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      model TEXT,
      meta_json TEXT,
      FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
    );
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_time ON messages(chat_id, created_at, id);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_chats_updated ON chats(updated_at);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_chats_arch_pin_upd ON chats(archived, pinned, updated_at);")

def _migrate_2_last_message_pointer(con: sqlite3.Connection):
    cols = {r["name"] for r in con.execute("PRAGMA table_info(chats);").fetchall()}
    if "last_message_id" not in cols:
        con.execute("ALTER TABLE chats ADD COLUMN last_message_id INTEGER;")

    con.execute("""
    UPDATE chats
       SET last_message_id = (
         SELECT m.id
           FROM messages m
          WHERE m.chat_id = chats.id
          ORDER BY m.created_at DESC, m.id DESC
          LIMIT 1
       )
     WHERE last_message_id IS NULL;
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_chats_lastmsg ON chats(last_message_id);")

def _migrate_3_fts(con: sqlite3.Connection):
    con.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
    USING fts5(
      chat_id UNINDEXED,
      content,
      tokenize='unicode61'
    );
    """)

    con.execute("DROP TRIGGER IF EXISTS messages_ai;")
    con.execute("DROP TRIGGER IF EXISTS messages_ad;")
    con.execute("DROP TRIGGER IF EXISTS messages_au;")

    con.execute("""
    CREATE TRIGGER IF NOT EXISTS messages_ai
    AFTER INSERT ON messages
    BEGIN
      INSERT INTO messages_fts(rowid, chat_id, content)
      VALUES (new.id, new.chat_id, new.content);
    END;
    """)
    con.execute("""
    CREATE TRIGGER IF NOT EXISTS messages_ad
    AFTER DELETE ON messages
    BEGIN
      DELETE FROM messages_fts WHERE rowid = old.id;
    END;
    """)
    con.execute("""
    CREATE TRIGGER IF NOT EXISTS messages_au
    AFTER UPDATE OF content, chat_id ON messages
    BEGIN
      UPDATE messages_fts
         SET chat_id=new.chat_id,
             content=new.content
       WHERE rowid=new.id;
    END;
    """)

    con.execute("""
    INSERT INTO messages_fts(rowid, chat_id, content)
    SELECT m.id, m.chat_id, m.content
      FROM messages m
     WHERE m.id NOT IN (SELECT rowid FROM messages_fts);
    """)

def _migrate_4_prefs_and_forks(con: sqlite3.Connection):
    cols = {r["name"] for r in con.execute("PRAGMA table_info(chats);").fetchall()}
    if "parent_chat_id" not in cols:
        con.execute("ALTER TABLE chats ADD COLUMN parent_chat_id TEXT;")
        con.execute("CREATE INDEX IF NOT EXISTS idx_chats_parent ON chats(parent_chat_id);")

    con.execute("""
    CREATE TABLE IF NOT EXISTS chat_prefs (
      chat_id TEXT PRIMARY KEY,
      rag_enabled INTEGER NOT NULL DEFAULT 0,
      doc_ids_json TEXT, -- NULL means "all docs"
      updated_at INTEGER NOT NULL,
      FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
    );
    """)

def _migrate_5_tags_and_settings(con: sqlite3.Connection):
    con.execute("""
    CREATE TABLE IF NOT EXISTS chat_tags (
      chat_id TEXT NOT NULL,
      tag TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      PRIMARY KEY(chat_id, tag),
      FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
    );
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_chat_tags_tag ON chat_tags(tag);")

    con.execute("""
    CREATE TABLE IF NOT EXISTS chat_settings (
      chat_id TEXT PRIMARY KEY,
      model TEXT,
      temperature REAL,
      num_ctx INTEGER,
      top_k INTEGER,
      use_mmr INTEGER NOT NULL DEFAULT 0,
      mmr_lambda REAL,
      updated_at INTEGER NOT NULL,
      FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
    );
    """)

def _migrate_7_token_count(con: sqlite3.Connection):
    cols = {r["name"] for r in con.execute("PRAGMA table_info(messages);").fetchall()}
    if "token_count" not in cols:
        con.execute("ALTER TABLE messages ADD COLUMN token_count INTEGER DEFAULT 0;")

def _migrate_6_autosummary(con: sqlite3.Connection):
    cols = {r["name"] for r in con.execute("PRAGMA table_info(chat_settings);").fetchall()}
    if "autosummary_enabled" not in cols:
        con.execute("ALTER TABLE chat_settings ADD COLUMN autosummary_enabled INTEGER NOT NULL DEFAULT 0;")
    if "autosummary_every" not in cols:
        con.execute("ALTER TABLE chat_settings ADD COLUMN autosummary_every INTEGER NOT NULL DEFAULT 12;")
    if "autosummary_last_msg_id" not in cols:
        con.execute("ALTER TABLE chat_settings ADD COLUMN autosummary_last_msg_id INTEGER;")

def _normalize_title(title: str) -> str:
    t = (title or "").strip()
    return (t[:200] if t else "New Chat")

def _normalize_meta(meta: Any) -> Optional[str]:
    if meta is None:
        return None
    if isinstance(meta, str):
        return meta
    try:
        return json.dumps(meta, ensure_ascii=False)
    except Exception:
        return json.dumps({"meta": str(meta)}, ensure_ascii=False)

def create_chat(title: str = "New Chat", parent_chat_id: Optional[str] = None) -> dict[str, Any]:
    chat_id = str(uuid.uuid4())
    ts = _now()
    title = _normalize_title(title)

    with _db() as con:
        con.execute(
            "INSERT INTO chats(id,title,created_at,updated_at,archived,pinned,last_message_id,parent_chat_id) VALUES(?,?,?,?,0,0,NULL,?)",
            (chat_id, title, ts, ts, parent_chat_id),
        )
        con.execute(
            "INSERT OR IGNORE INTO chat_prefs(chat_id, rag_enabled, doc_ids_json, updated_at) VALUES(?,0,NULL,?)",
            (chat_id, ts),
        )
        con.execute(
            "INSERT OR IGNORE INTO chat_settings(chat_id, updated_at) VALUES(?,?)",
            (chat_id, ts),
        )

    return {"id": chat_id, "title": title, "created_at": ts, "updated_at": ts, "archived": 0, "pinned": 0, "last_message_id": None, "parent_chat_id": parent_chat_id}

# --- FTS sanitizing (prevents MATCH errors) ---
_word = re.compile(r"[A-Za-z0-9_]{2,}")
def _fts_safe_query(q: str) -> str:
    toks = _word.findall((q or "").lower())
    if not toks:
        return ""
    return " OR ".join(toks[:24])

def list_chats(include_archived: bool = False, q: Optional[str] = None, tag: Optional[str] = None, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    q = (q or "").strip()
    tag = (tag or "").strip().lower()

    where = []
    params: list[Any] = []

    if not include_archived:
        where.append("c.archived = 0")

    if tag:
        where.append("EXISTS(SELECT 1 FROM chat_tags t WHERE t.chat_id=c.id AND t.tag=?)")
        params.append(tag)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    base_sql = f"""
    SELECT
      c.id, c.title, c.created_at, c.updated_at, c.archived, c.pinned,
      substr(COALESCE(m.content,''),1,180) AS last_preview,
      c.parent_chat_id
    FROM chats c
    LEFT JOIN messages m ON m.id = c.last_message_id
    {where_sql}
    """

    order_sql = " ORDER BY c.pinned DESC, c.updated_at DESC LIMIT ? OFFSET ?;"

    with _db() as con:
        if not q:
            cur = con.execute(base_sql + order_sql, (*params, limit, offset))
            return [dict(r) for r in cur.fetchall()]

        try:
            sql = base_sql + """
              AND (
                c.title LIKE ?
                OR c.id IN (SELECT DISTINCT chat_id FROM messages_fts WHERE messages_fts MATCH ?)
              )
            """ + order_sql
            cur = con.execute(sql, (*params, f"%{q}%", q, limit, offset))
            return [dict(r) for r in cur.fetchall()]
        except sqlite3.OperationalError:
            safe = _fts_safe_query(q)
            if not safe:
                cur = con.execute(base_sql + " AND c.title LIKE ? " + order_sql, (*params, f"%{q}%", limit, offset))
                return [dict(r) for r in cur.fetchall()]
            sql = base_sql + """
              AND (
                c.title LIKE ?
                OR c.id IN (SELECT DISTINCT chat_id FROM messages_fts WHERE messages_fts MATCH ?)
              )
            """ + order_sql
            cur = con.execute(sql, (*params, f"%{q}%", safe, limit, offset))
            return [dict(r) for r in cur.fetchall()]

def get_chat(chat_id: str, limit: int = 2000, offset: int = 0) -> dict[str, Any]:
    limit = max(1, min(int(limit), 5000))
    offset = max(0, int(offset))

    with _db() as con:
        chat = con.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat:
            raise KeyError("chat not found")

        cur = con.execute("""
          SELECT id, role, content, created_at, model, meta_json, token_count
            FROM messages
           WHERE chat_id=?
           ORDER BY created_at ASC, id ASC
           LIMIT ? OFFSET ?;
        """, (chat_id, limit, offset))
        msgs = [dict(r) for r in cur.fetchall()]
        return {"chat": dict(chat), "messages": msgs}

def rename_chat(chat_id: str, title: str):
    title = _normalize_title(title)
    with _db() as con:
        con.execute("UPDATE chats SET title=?, updated_at=? WHERE id=?", (title, _now(), chat_id))

def set_archived(chat_id: str, archived: bool):
    with _db() as con:
        con.execute("UPDATE chats SET archived=?, updated_at=? WHERE id=?", (1 if archived else 0, _now(), chat_id))

def set_pinned(chat_id: str, pinned: bool):
    with _db() as con:
        con.execute("UPDATE chats SET pinned=?, updated_at=? WHERE id=?", (1 if pinned else 0, _now(), chat_id))

def toggle_archived(chat_id: str) -> dict[str, Any]:
    with _db() as con:
        row = con.execute("SELECT archived FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not row:
            raise KeyError("chat not found")
        newv = 0 if int(row["archived"]) else 1
        con.execute("UPDATE chats SET archived=?, updated_at=? WHERE id=?", (newv, _now(), chat_id))
        return {"archived": newv}

def toggle_pinned(chat_id: str) -> dict[str, Any]:
    with _db() as con:
        row = con.execute("SELECT pinned FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not row:
            raise KeyError("chat not found")
        newv = 0 if int(row["pinned"]) else 1
        con.execute("UPDATE chats SET pinned=?, updated_at=? WHERE id=?", (newv, _now(), chat_id))
        return {"pinned": newv}

def delete_chat(chat_id: str):
    with _db() as con:
        con.execute("DELETE FROM chats WHERE id=?", (chat_id,))

def clear_chat(chat_id: str):
    with _db() as con:
        con.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
        con.execute("UPDATE chats SET last_message_id=NULL, updated_at=? WHERE id=?", (_now(), chat_id))

def append_messages(chat_id: str, items: list[dict[str, Any]]):
    ts = _now()
    with _db() as con:
        row = con.execute("SELECT title FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not row:
            raise KeyError("chat not found")

        wrote_any = False
        last_id: Optional[int] = None

        for it in items or []:
            role = (it.get("role") or "").strip()
            if role not in VALID_ROLES:
                continue
            content = (it.get("content") or "").strip()
            if not content:
                continue

            msg_ts = _now()
            model = it.get("model")
            meta = _normalize_meta(it.get("meta_json"))
            token_count = len(content.split())  # Simple token count

            cur = con.execute(
                "INSERT INTO messages(chat_id,role,content,created_at,model,meta_json,token_count) VALUES(?,?,?,?,?,?,?)",
                (chat_id, role, content, msg_ts, model, meta, token_count),
            )
            last_id = int(cur.lastrowid) if cur.lastrowid is not None else None
            wrote_any = True

        if not wrote_any:
            return

        if row["title"] == "New Chat":
            first_user = next((it for it in items if it.get("role") == "user" and (it.get("content") or "").strip()), None)
            if first_user:
                words = first_user["content"].strip().split()
                new_title = (" ".join(words[:7])[:60]).strip() or "New Chat"
                con.execute("UPDATE chats SET title=?, updated_at=?, last_message_id=? WHERE id=?", (new_title, ts, last_id, chat_id))
            else:
                con.execute("UPDATE chats SET updated_at=?, last_message_id=? WHERE id=?", (ts, last_id, chat_id))
        else:
            con.execute("UPDATE chats SET updated_at=?, last_message_id=? WHERE id=?", (ts, last_id, chat_id))

def trim_after(chat_id: str, msg_id: int):
    with _db() as con:
        con.execute("DELETE FROM messages WHERE chat_id=? AND id>?", (chat_id, int(msg_id)))
        exists = con.execute("SELECT id FROM messages WHERE chat_id=? AND id=?", (chat_id, int(msg_id))).fetchone()
        last_id = int(exists["id"]) if exists else None
        con.execute("UPDATE chats SET last_message_id=?, updated_at=? WHERE id=?", (last_id, _now(), chat_id))

def update_message_content(chat_id: str, msg_id: int, new_content: str):
    with _db() as con:
        con.execute("UPDATE messages SET content=? WHERE chat_id=? AND id=?", (new_content.strip(), chat_id, int(msg_id)))
        con.execute("UPDATE chats SET updated_at=? WHERE id=?", (_now(), chat_id))

def export_chat_markdown(chat_id: str) -> str:
    data = get_chat(chat_id, limit=5000, offset=0)
    chat = data["chat"]
    msgs = data["messages"]

    lines = [f"# {chat.get('title','Chat')}", ""]
    for m in msgs:
        role = (m.get("role") or "").upper()
        ts = m.get("created_at")
        lines.append(f"## {role} ({ts})")
        lines.append("")
        lines.append(m.get("content") or "")
        lines.append("")
    return "\n".join(lines)

# -------- prefs (DB doc selection per chat) --------

def get_prefs(chat_id: str) -> dict[str, Any]:
    with _db() as con:
        row = con.execute("SELECT * FROM chat_prefs WHERE chat_id=?", (chat_id,)).fetchone()
        if not row:
            c = con.execute("SELECT id FROM chats WHERE id=?", (chat_id,)).fetchone()
            if not c:
                raise KeyError("chat not found")
            ts = _now()
            con.execute("INSERT INTO chat_prefs(chat_id, rag_enabled, doc_ids_json, updated_at) VALUES(?,0,NULL,?)", (chat_id, ts))
            return {"chat_id": chat_id, "rag_enabled": 0, "doc_ids": None, "updated_at": ts}
        doc_ids = None
        if row["doc_ids_json"] is not None:
            try:
                v = json.loads(row["doc_ids_json"])
                if isinstance(v, list):
                    doc_ids = [int(x) for x in v if x is not None and str(x).isdigit()]
            except Exception:
                doc_ids = []
        return {"chat_id": chat_id, "rag_enabled": int(row["rag_enabled"]), "doc_ids": doc_ids, "updated_at": int(row["updated_at"])}

def set_prefs(chat_id: str, rag_enabled: Optional[bool] = None, doc_ids: Any = "__nochange__"):
    ts = _now()
    with _db() as con:
        c = con.execute("SELECT id FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not c:
            raise KeyError("chat not found")

        cur = con.execute("SELECT * FROM chat_prefs WHERE chat_id=?", (chat_id,)).fetchone()
        if not cur:
            con.execute("INSERT INTO chat_prefs(chat_id, rag_enabled, doc_ids_json, updated_at) VALUES(?,0,NULL,?)", (chat_id, ts))

        updates = []
        params: list[Any] = []

        if rag_enabled is not None:
            updates.append("rag_enabled=?")
            params.append(1 if rag_enabled else 0)

        if doc_ids != "__nochange__":
            if doc_ids is None:
                updates.append("doc_ids_json=NULL")
            else:
                if isinstance(doc_ids, list):
                    cleaned = []
                    for x in doc_ids:
                        try:
                            cleaned.append(int(x))
                        except Exception:
                            pass
                    updates.append("doc_ids_json=?")
                    params.append(json.dumps(sorted(set(cleaned)), ensure_ascii=False))
                else:
                    updates.append("doc_ids_json=?")
                    params.append(json.dumps([], ensure_ascii=False))

        updates.append("updated_at=?")
        params.append(ts)

        sql = "UPDATE chat_prefs SET " + ", ".join(updates) + " WHERE chat_id=?"
        params.append(chat_id)
        con.execute(sql, params)

# -------- fork/branch --------

def fork_chat(chat_id: str, upto_msg_id: int) -> dict[str, Any]:
    upto_msg_id = int(upto_msg_id)
    with _db() as con:
        base = con.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not base:
            raise KeyError("chat not found")

        rows = con.execute("""
          SELECT role, content, created_at, model, meta_json
            FROM messages
           WHERE chat_id=? AND id<=?
           ORDER BY created_at ASC, id ASC
        """, (chat_id, upto_msg_id)).fetchall()

    new_title = f"Fork: {base['title']}"
    new = create_chat(new_title, parent_chat_id=chat_id)

    prefs = get_prefs(chat_id)
    set_prefs(new["id"], rag_enabled=bool(prefs.get("rag_enabled")), doc_ids=prefs.get("doc_ids"))

    append_messages(new["id"], [{
        "role": r["role"],
        "content": r["content"],
        "model": r["model"],
        "meta_json": r["meta_json"],
    } for r in rows])

    return new

# -------- search (FTS) --------

def search_messages(q: str, chat_id: Optional[str] = None, limit: int = 25, offset: int = 0) -> list[dict[str, Any]]:
    q = (q or "").strip()
    if not q:
        return [] 

    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset)) 

    safe_q = _fts_safe_query(q)
    if not safe_q:
        return []

    with _db() as con:
        params: list[Any] = []
        where = ""
        if chat_id:
            where = " AND m.chat_id=? "
            params.append(chat_id) 

        sql = f"""
        SELECT
          m.id AS msg_id,
          m.chat_id,
          c.title AS chat_title,
          m.role,
          m.created_at,
          snippet(messages_fts, 1, '[', ']', '…', 14) AS snippet
        FROM messages_fts
        JOIN messages m ON m.id = messages_fts.rowid
        JOIN chats c ON c.id = m.chat_id
        WHERE messages_fts MATCH ?
        {where}
        ORDER BY m.created_at DESC, m.id DESC
        LIMIT ? OFFSET ?;
        """
        params2 = [safe_q] + params + [limit, offset]
        return [dict(r) for r in con.execute(sql, params2).fetchall()]

# -------- tags --------

def add_tag(chat_id: str, tag: str):
    t = (tag or "").strip().lower()
    if not t:
        return
    with _db() as con:
        con.execute("INSERT OR IGNORE INTO chat_tags(chat_id, tag, created_at) VALUES(?,?,?)", (chat_id, t, _now()))

def remove_tag(chat_id: str, tag: str):
    t = (tag or "").strip().lower()
    if not t:
        return
    with _db() as con:
        con.execute("DELETE FROM chat_tags WHERE chat_id=? AND tag=?", (chat_id, t))

def list_tags(chat_id: str) -> list[str]:
    with _db() as con:
        rows = con.execute("SELECT tag FROM chat_tags WHERE chat_id=? ORDER BY tag ASC", (chat_id,)).fetchall()
        return [r["tag"] for r in rows]

# -------- chat settings --------

def get_settings(chat_id: str) -> dict[str, Any]:
    with _db() as con:
        row = con.execute("SELECT * FROM chat_settings WHERE chat_id=?", (chat_id,)).fetchone()
        if not row:
            return {"chat_id": chat_id}
        return dict(row)

def set_settings(chat_id: str, **kwargs):
    allowed = {"model", "temperature", "num_ctx", "top_k", "use_mmr", "mmr_lambda", "autosummary_enabled", "autosummary_every", "autosummary_last_msg_id"}
    patch = {k: v for k, v in kwargs.items() if k in allowed}

    if not patch:
        return

    ts = _now()
    with _db() as con:
        con.execute("INSERT OR IGNORE INTO chat_settings(chat_id, updated_at) VALUES(?,?)", (chat_id, ts))

        sets = []
        params: list[Any] = []
        for k, v in patch.items():
            sets.append(f"{k}=?")
            if k in ("use_mmr", "autosummary_enabled"):
                params.append(1 if bool(v) else 0)
            else:
                params.append(v)
        sets.append("updated_at=?")
        params.append(ts)
        params.append(chat_id)

        con.execute("UPDATE chat_settings SET " + ", ".join(sets) + " WHERE chat_id=?", params)

# -------- message context (jump) --------

def get_message_context(chat_id: str, msg_id: int, span: int = 20) -> dict[str, Any]:
    span = max(1, min(int(span), 200))
    msg_id = int(msg_id)

    with _db() as con:
        anchor = con.execute("SELECT id, created_at FROM messages WHERE chat_id=? AND id=?", (chat_id, msg_id)).fetchone()
        if not anchor:
            raise KeyError("message not found")

        rows = con.execute("""
          SELECT id, role, content, created_at, model, meta_json
          FROM messages
          WHERE chat_id=?
          ORDER BY created_at ASC, id ASC
        """, (chat_id,)).fetchall()

    ids = [r["id"] for r in rows]
    try:
        idx = ids.index(msg_id)
    except ValueError:
        raise KeyError("message not found")

    lo = max(0, idx - span)
    hi = min(len(rows), idx + span + 1)
    return {"anchor_id": msg_id, "messages": [dict(r) for r in rows[lo:hi]]}

async def trim_after_async(chat_id: str, msg_id: int):
    await asyncio.to_thread(trim_after, chat_id, msg_id)

async def update_message_content_async(chat_id: str, msg_id: int, new_content: str):
    await asyncio.to_thread(update_message_content, chat_id, msg_id, new_content)
