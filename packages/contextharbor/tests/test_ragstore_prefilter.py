from __future__ import annotations

import hashlib
import sqlite3
import time

import pytest

from contextharbor.stores import ragstore


@pytest.mark.asyncio
async def test_retrieve_prefilter_unscoped_query_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: unscoped queries must not SQL-error or full-scan all chunks."""

    ragstore.init_db()

    # Reset DB contents (tests share a workspace-scoped sqlite).
    con = sqlite3.connect(ragstore.DB_PATH, timeout=10, check_same_thread=False)
    try:
        con.execute("PRAGMA foreign_keys=ON;")
        con.execute("DELETE FROM chunks;")
        con.execute("DELETE FROM docs;")
        try:
            con.execute("DELETE FROM chunks_fts;")
        except Exception:
            pass
        con.commit()

        doc_text = "hello world\n"
        sha = hashlib.sha256(doc_text.encode("utf-8")).hexdigest()
        created_at = int(time.time())

        cur = con.execute(
            """
            INSERT INTO docs(
              filename, sha256, created_at, embed_model, embed_dim,
              weight, group_name, source, title, author, path, meta_json
            ) VALUES(?,?,?,?,?,1.0,NULL,?,?,?,?,?)
            """,
            (
                "doc",
                sha,
                created_at,
                "test-embed",
                2,
                "epub",
                "Test Title",
                "Test Author",
                "test.epub",
                None,
            ),
        )
        doc_id = int(cur.lastrowid or 0)

        emb = ragstore.embedding_to_blob([1.0, 0.0])
        con.execute(
            """
            INSERT INTO chunks(doc_id, chunk_index, section, text, emb, norm, chunk_sha)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                doc_id,
                0,
                "s",
                doc_text,
                emb,
                1.0,
                hashlib.sha256(doc_text.encode("utf-8")).hexdigest(),
            ),
        )
        con.commit()
    finally:
        con.close()

    async def _fake_embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
        # Return a stable 2d embedding for the query.
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(ragstore, "embed_texts", _fake_embed_texts)

    hits = await ragstore.retrieve("hello", top_k=1, embed_model="test-embed")
    assert hits
    assert "hello" in (hits[0].get("text") or "").lower()
