from __future__ import annotations

import os, sqlite3, hashlib, math, time, re
from array import array
from typing import Optional, Any
from contextlib import contextmanager
import httpx

DB_PATH = os.getenv("RAG_DB", os.path.join(os.path.dirname(__file__), "../../../data/rag.sqlite3"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_EMBED_MODEL = os.getenv("EMBED_MODEL", "embeddinggemma")

MAX_DOC_BYTES = int(os.getenv("RAG_MAX_DOC_BYTES", str(10 * 1024 * 1024)))
MAX_TOP_K = int(os.getenv("RAG_MAX_TOPK", "20"))
EMBED_BATCH = int(os.getenv("RAG_EMBED_BATCH", "48"))

PREFILTER_LIMIT = int(os.getenv("RAG_PREFILTER_LIMIT", "1500"))
PER_DOC_CAP = int(os.getenv("RAG_PER_DOC_CAP", "40"))
USE_PREFILTER = os.getenv("RAG_USE_PREFILTER", "1") == "1"

USE_MMR_DEFAULT = os.getenv("RAG_USE_MMR", "0") == "1"
MMR_LAMBDA = float(os.getenv("RAG_MMR_LAMBDA", "0.75"))

_http: httpx.AsyncClient | None = None

def _now() -> int:
    return int(time.time())

def _conn():
    c = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA synchronous=NORMAL;")
    c.execute("PRAGMA foreign_keys=ON;")
    c.execute("PRAGMA busy_timeout=5000;")
    c.execute("PRAGMA temp_store=MEMORY;")
    c.execute("PRAGMA cache_size=-20000;")
    return c

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
            _migrate_1_baseline(con); _set_user_version(con, 1); v = 1
        if v < 2:
            _migrate_2_dim_and_hash(con); _set_user_version(con, 2); v = 2
        if v < 3:
            _migrate_3_fts_prefilter(con); _set_user_version(con, 3); v = 3
        if v < 4:
            _migrate_4_doc_meta(con); _set_user_version(con, 4); v = 4

def _migrate_1_baseline(con: sqlite3.Connection):
    con.execute("""
    CREATE TABLE IF NOT EXISTS docs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      filename TEXT NOT NULL,
      sha256 TEXT NOT NULL,
      created_at INTEGER NOT NULL
    );
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      doc_id INTEGER NOT NULL,
      chunk_index INTEGER NOT NULL,
      text TEXT NOT NULL,
      emb BLOB NOT NULL,
      norm REAL NOT NULL,
      FOREIGN KEY(doc_id) REFERENCES docs(id) ON DELETE CASCADE
    );
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_docs_sha ON docs(sha256);")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_chunks_doc_idx ON chunks(doc_id, chunk_index);")

def _migrate_2_dim_and_hash(con: sqlite3.Connection):
    cols_docs = {r["name"] for r in con.execute("PRAGMA table_info(docs);").fetchall()}
    if "embed_model" not in cols_docs:
        con.execute("ALTER TABLE docs ADD COLUMN embed_model TEXT;")
    if "embed_dim" not in cols_docs:
        con.execute("ALTER TABLE docs ADD COLUMN embed_dim INTEGER;")

    cols_chunks = {r["name"] for r in con.execute("PRAGMA table_info(chunks);").fetchall()}
    if "chunk_sha" not in cols_chunks:
        con.execute("ALTER TABLE chunks ADD COLUMN chunk_sha TEXT;")
    con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_sha ON chunks(chunk_sha);")

def _migrate_3_fts_prefilter(con: sqlite3.Connection):
    con.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
    USING fts5(
      chunk_id UNINDEXED,
      doc_id UNINDEXED,
      text,
      tokenize='unicode61'
    );
    """)
    con.execute("DROP TRIGGER IF EXISTS chunks_ai;")
    con.execute("DROP TRIGGER IF EXISTS chunks_ad;")
    con.execute("DROP TRIGGER IF EXISTS chunks_au;")

    con.execute("""
    CREATE TRIGGER IF NOT EXISTS chunks_ai
    AFTER INSERT ON chunks
    BEGIN
      INSERT INTO chunks_fts(rowid, chunk_id, doc_id, text)
      VALUES (new.id, new.id, new.doc_id, new.text);
    END;
    """)
    con.execute("""
    CREATE TRIGGER IF NOT EXISTS chunks_ad
    AFTER DELETE ON chunks
    BEGIN
      DELETE FROM chunks_fts WHERE rowid = old.id;
    END;
    """)
    con.execute("""
    CREATE TRIGGER IF NOT EXISTS chunks_au
    AFTER UPDATE OF text, doc_id ON chunks
    BEGIN
      UPDATE chunks_fts
         SET chunk_id=new.id,
             doc_id=new.doc_id,
             text=new.text
       WHERE rowid=new.id;
    END;
    """)
    con.execute("""
    INSERT INTO chunks_fts(rowid, chunk_id, doc_id, text)
    SELECT c.id, c.id, c.doc_id, c.text
      FROM chunks c
     WHERE c.id NOT IN (SELECT rowid FROM chunks_fts);
    """)

def _migrate_4_doc_meta(con: sqlite3.Connection):
    cols = {r["name"] for r in con.execute("PRAGMA table_info(docs);").fetchall()}
    if "weight" not in cols:
        con.execute("ALTER TABLE docs ADD COLUMN weight REAL NOT NULL DEFAULT 1.0;")
    if "group_name" not in cols:
        con.execute("ALTER TABLE docs ADD COLUMN group_name TEXT;")
    con.execute("CREATE INDEX IF NOT EXISTS idx_docs_group ON docs(group_name);")

def _client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
        _http = httpx.AsyncClient(timeout=None, limits=limits)
    return _http

async def embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    model = model or DEFAULT_EMBED_MODEL
    embeddings = []
    for text in texts:
        r = await _client().post(f"{OLLAMA_URL}/api/embeddings", json={"model": model, "prompt": text})
        r.raise_for_status()
        emb = r.json().get("embedding")
        if emb:
            embeddings.append(emb)
    return embeddings

def _pack(vec: list[float]) -> bytes:
    return array("f", vec).tobytes()

def _unpack(blob: bytes) -> list[float]:
    a = array("f"); a.frombytes(blob); return a.tolist()

def _norm(v: list[float]) -> float:
    return math.sqrt(sum(x*x for x in v)) or 1e-12

def _dot(a: list[float], b: list[float]) -> float:
    return sum(x*y for x, y in zip(a, b))

def _cosine(q: list[float], qn: float, v: list[float], vn: float) -> float:
    return _dot(q, v) / (qn * vn + 1e-12)

def _sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8", errors="ignore")).hexdigest()

def embedding_to_array(emb) -> array:
    if isinstance(emb, array):
        return emb
    return array("f", [float(x) for x in emb])

def embedding_to_blob(emb) -> bytes:
    a = embedding_to_array(emb)
    return a.tobytes()

def embedding_blob_to_array(blob: bytes) -> array:
    a = array("f")
    a.frombytes(blob)
    return a

def cosine(a: array, b: array) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += float(x) * float(y)
        na += float(x) * float(x)
        nb += float(y) * float(y)
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))

_sentence_split = re.compile(r"(?<=[.!?])\s+")
_ws = re.compile(r"\s+")

def chunk_text(text: str, max_chars: int = 1200, overlap: int = 200) -> list[str]:
    """
    Split text into chunks for embedding.

    Strategy:
    1. Split by paragraphs first
    2. Combine small paragraphs into chunks near max_chars
    3. Then split chunks by sentences to avoid cutting mid-sentence
    4. Finally apply overlap between consecutive chunks

    Args:
        text: Input text to chunk
        max_chars: Maximum characters per chunk (default 1200)
        overlap: Characters to overlap between chunks (default 200)

    Returns:
        List of text chunks
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    out: list[str] = []
    buf = ""
    
    def flush(b: str):
        b = b.strip()
        if b:
            out.append(b)
    
    for p in paras:
        if len(p) <= max_chars:
            if len(buf) + len(p) + 2 <= max_chars:
                buf = (buf + "\n\n" + p).strip() if buf else p
            else:
                flush(buf); buf = p
            continue
        
        flush(buf); buf = ""
        sents = _sentence_split.split(_ws.sub(" ", p).strip())
        chunk = ""
        for s in sents:
            if not s: continue
            if len(chunk) + len(s) + 1 <= max_chars:
                chunk = (chunk + " " + s).strip() if chunk else s
            else:
                flush(chunk); chunk = s
            while len(chunk) > max_chars:
                flush(chunk[:max_chars])
                chunk = chunk[max_chars - overlap:]
        flush(chunk)
    
    flush(buf)
    
    if overlap > 0 and len(out) > 1:
        smoothed = []
        for i, ch in enumerate(out):
            if i == 0:
                smoothed.append(ch); continue
            prev = smoothed[-1]
            tail = prev[-overlap:] if len(prev) > overlap else prev
            cur = (tail + "\n" + ch).strip()
            smoothed.append(cur[:max_chars] if len(cur) > max_chars else cur)
        out = smoothed
    
    return out

async def add_document(filename: str, text: str, embed_model: str | None = None) -> int:
    text = text or ""
    if len(text.encode("utf-8", errors="ignore")) > MAX_DOC_BYTES:
        raise ValueError("Document too large")

    sha = _sha256_text(text)
    created_at = _now()
    embed_model = embed_model or DEFAULT_EMBED_MODEL

    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("No text to ingest")

    embeddings: list[list[float]] = []
    for i in range(0, len(chunks), EMBED_BATCH):
        embeddings.extend(await embed_texts(chunks[i:i + EMBED_BATCH], embed_model))

    if len(embeddings) != len(chunks):
        raise RuntimeError("Embedding count mismatch")

    embed_dim = len(embeddings[0]) if embeddings else 0
    if embed_dim <= 0:
        raise RuntimeError("Bad embedding dimension")

    with _db() as con:
        row = con.execute("SELECT id FROM docs WHERE sha256=?", (sha,)).fetchone()
        if row:
            return int(row["id"])

        cur = con.execute(
            "INSERT INTO docs(filename, sha256, created_at, embed_model, embed_dim, weight, group_name) VALUES(?,?,?,?,?,1.0,NULL)",
            (filename, sha, created_at, embed_model, embed_dim),
        )
        doc_id = int(cur.lastrowid or 0)

        for idx, (ch, emb) in enumerate(zip(chunks, embeddings)):
            n = _norm(emb)
            chunk_sha = _sha256_text(ch)
            con.execute(
                "INSERT INTO chunks(doc_id, chunk_index, text, emb, norm, chunk_sha) VALUES(?,?,?,?,?,?)",
                (doc_id, idx, ch, _pack(emb), float(n), chunk_sha),
            )
        return doc_id

def list_documents():
    with _db() as con:
        rows = con.execute("""
          SELECT d.id, d.filename, d.created_at, d.embed_model, d.embed_dim,
                 d.weight, d.group_name,
                 (SELECT COUNT(1) FROM chunks c WHERE c.doc_id=d.id) AS chunk_count
            FROM docs d
           ORDER BY d.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]

def update_document(doc_id: int, *, weight: Optional[float] = None, group_name: Optional[str] = None, filename: Optional[str] = None):
    sets = []
    params: list[Any] = []
    if weight is not None:
        w = float(weight)
        if w < 0.0: w = 0.0
        if w > 5.0: w = 5.0
        sets.append("weight=?"); params.append(w)
    if group_name is not None:
        g = (group_name or "").strip()
        sets.append("group_name=?"); params.append(g if g else None)
    if filename is not None:
        f = (filename or "").strip()
        if f:
            sets.append("filename=?"); params.append(f[:260])
    if not sets:
        return
    params.append(int(doc_id))
    with _db() as con:
        con.execute("UPDATE docs SET " + ", ".join(sets) + " WHERE id=?", params)

def delete_document(doc_id: int):
    with _db() as con:
        con.execute("DELETE FROM docs WHERE id=?", (doc_id,))

def get_chunk(chunk_id: int) -> dict[str, Any]:
    with _db() as con:
        row = con.execute("""
          SELECT c.id, c.doc_id, c.chunk_index, c.text, d.filename
            FROM chunks c
            JOIN docs d ON d.id=c.doc_id
           WHERE c.id=?
        """, (int(chunk_id),)).fetchone()
        if not row:
            raise KeyError("chunk not found")
        return dict(row)

def get_neighbors(chunk_id: int, span: int = 1) -> dict[str, Any]:
    span = max(1, min(int(span), 5))
    base = get_chunk(chunk_id)
    did = int(base["doc_id"])
    idx = int(base["chunk_index"])

    with _db() as con:
        rows = con.execute("""
          SELECT id, doc_id, chunk_index, text
            FROM chunks
           WHERE doc_id=? AND chunk_index BETWEEN ? AND ?
           ORDER BY chunk_index ASC
        """, (did, idx - span, idx + span)).fetchall()

    return {
        "doc_id": did,
        "filename": base["filename"],
        "center_chunk_id": int(chunk_id),
        "center_index": idx,
        "chunks": [dict(r) for r in rows],
    }

_word = re.compile(r"[A-Za-z0-9_]{2,}")
def _fts_safe_query(q: str) -> str:
    toks = _word.findall((q or "").lower())
    return " OR ".join(toks[:24])

def _prefilter_chunk_ids(con: sqlite3.Connection, query: str, doc_ids: Optional[list[int]], limit: int) -> list[int]:
    q = (query or "").strip()
    if not q:
        return []
    safe = q
    params: list[Any] = []
    where = []
    if doc_ids:
        qs = ",".join("?" for _ in doc_ids)
        where.append(f"doc_id IN ({qs})")
        params.extend(doc_ids)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    # raw first, fallback to safe
    try:
        sql = f"""
        SELECT chunk_id
          FROM chunks_fts
        {where_sql}
         AND chunks_fts MATCH ?
         LIMIT ?;
        """
        params2 = params + [safe, int(limit)]
        return [int(r[0]) for r in con.execute(sql, params2).fetchall()]
    except sqlite3.OperationalError:
        safe2 = _fts_safe_query(q)
        if not safe2:
            return []
        sql = f"""
        SELECT chunk_id
          FROM chunks_fts
        {where_sql}
         AND chunks_fts MATCH ?
         LIMIT ?;
        """
        params2 = params + [safe2, int(limit)]
        return [int(r[0]) for r in con.execute(sql, params2).fetchall()]

def _load_candidates(con: sqlite3.Connection, doc_ids: Optional[list[int]], chunk_ids: Optional[list[int]]):
    if chunk_ids:
        qs = ",".join("?" for _ in chunk_ids)
        return con.execute(f"""
          SELECT c.id, c.doc_id, c.chunk_index, c.text, c.emb, c.norm, d.filename, d.weight
            FROM chunks c
            JOIN docs d ON d.id=c.doc_id
           WHERE c.id IN ({qs})
        """, tuple(chunk_ids)).fetchall()

    if doc_ids:
        qs = ",".join("?" for _ in doc_ids)
        return con.execute(f"""
          SELECT c.id, c.doc_id, c.chunk_index, c.text, c.emb, c.norm, d.filename, d.weight
            FROM chunks c
            JOIN docs d ON d.id=c.doc_id
           WHERE c.doc_id IN ({qs})
        """, tuple(doc_ids)).fetchall()

    return con.execute("""
      SELECT c.id, c.doc_id, c.chunk_index, c.text, c.emb, c.norm, d.filename, d.weight
        FROM chunks c
        JOIN docs d ON d.id=c.doc_id
    """).fetchall()

def _cap_per_doc(rows, cap: int):
    if cap <= 0: return rows
    out = []
    seen = {}
    for r in rows:
        did = int(r["doc_id"])
        n = seen.get(did, 0)
        if n >= cap: continue
        seen[did] = n + 1
        out.append(r)
    return out

def _mmr_select(scored: list[dict[str, Any]], k: int, lam: float) -> list[dict[str, Any]]:
    if not scored:
        return []
    k = max(1, min(k, len(scored)))
    lam = max(0.0, min(1.0, lam))
    scored.sort(key=lambda x: x["score"], reverse=True)

    picked = [scored[0]]
    used = {scored[0]["chunk_id"]}

    def sim(a: list[float], b: list[float]) -> float:
        an = _norm(a); bn = _norm(b)
        return _dot(a,b) / (an*bn + 1e-12)

    while len(picked) < k:
        best = None
        best_val = -1e9
        for cand in scored:
            if cand["chunk_id"] in used:
                continue
            rel = cand["score"]
            div = max(sim(cand["_vec"], p["_vec"]) for p in picked)
            val = lam * rel - (1.0 - lam) * div
            if val > best_val:
                best_val = val
                best = cand
        if best is None:
            break
        picked.append(best)
        used.add(best["chunk_id"])
    return picked

async def retrieve(
    query: str,
    top_k: int = 6,
    doc_ids: Optional[list[int]] = None,
    embed_model: str | None = None,
    use_mmr: Optional[bool] = None,
    mmr_lambda: float = MMR_LAMBDA,
):
    top_k = max(1, min(int(top_k), MAX_TOP_K))
    use_mmr = (USE_MMR_DEFAULT if use_mmr is None else bool(use_mmr))

    qv = (await embed_texts([query], embed_model))[0]
    qn = _norm(qv)
    qdim = len(qv)

    with _db() as con:
        chunk_ids = None
        if USE_PREFILTER:
            try:
                chunk_ids = _prefilter_chunk_ids(con, query, doc_ids, PREFILTER_LIMIT)
            except Exception:
                chunk_ids = None

        rows = _load_candidates(con, doc_ids, chunk_ids)
        rows = _cap_per_doc(rows, PER_DOC_CAP)

        scored: list[dict[str, Any]] = []
        for r in rows:
            v = _unpack(r["emb"])
            if len(v) != qdim:
                continue
            base = _cosine(qv, qn, v, float(r["norm"]))
            weight = float(r["weight"] if r["weight"] is not None else 1.0)
            if weight < 0.0: weight = 0.0
            if weight > 5.0: weight = 5.0

            score = base * weight

            scored.append({
                "chunk_id": int(r["id"]),
                "doc_id": int(r["doc_id"]),
                "filename": r["filename"],
                "chunk_index": int(r["chunk_index"]),
                "score": float(score),
                "text": r["text"],
                "_vec": v if use_mmr else None,
                "doc_weight": weight,
            })

    scored.sort(key=lambda x: x["score"], reverse=True)

    if use_mmr:
        picked = _mmr_select(scored, top_k, mmr_lambda)
        for p in picked:
            p.pop("_vec", None)
        return picked

    out = scored[:top_k]
    for p in out:
        p.pop("_vec", None)
    return out
