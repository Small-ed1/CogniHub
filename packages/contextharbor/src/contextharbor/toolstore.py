from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Optional

from . import config


class ToolStore:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or config.config.tool_db
        # Ensure parent directory exists
        p = Path(self.db_path)
        if p.parent and str(p.parent) != ".":
            os.makedirs(p.parent, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA foreign_keys=ON;")
        return con

    def _init_db(self) -> None:
        con = self._connect()
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts DATETIME DEFAULT CURRENT_TIMESTAMP,
                    chat_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    output_excerpt TEXT NOT NULL,
                    output_sha256 TEXT NOT NULL,
                    meta_json TEXT NOT NULL
                );
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_tool_runs_chat ON tool_runs(chat_id, ts);")
            con.commit()
        finally:
            con.close()

    def _log_tool_run_sync(
        self,
        *,
        chat_id: str,
        message_id: str,
        tool_name: str,
        args_json: str,
        ok: bool,
        duration_ms: int,
        output_excerpt: str,
        output_sha256: str,
        meta_json: str,
    ) -> None:
        con = self._connect()
        try:
            con.execute(
                """
                INSERT INTO tool_runs
                (chat_id, message_id, tool_name, args_json, ok, duration_ms, output_excerpt, output_sha256, meta_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    message_id,
                    tool_name,
                    args_json,
                    1 if ok else 0,
                    duration_ms,
                    output_excerpt,
                    output_sha256,
                    meta_json,
                ),
            )
            con.commit()
        finally:
            con.close()

    async def log_tool_run(
        self,
        *,
        chat_id: str,
        message_id: str,
        tool_name: str,
        args_json: str,
        ok: bool,
        duration_ms: int,
        output_excerpt: str,
        output_sha256: str,
        meta_json: str,
    ) -> None:
        await asyncio.to_thread(
            self._log_tool_run_sync,
            chat_id=chat_id,
            message_id=message_id,
            tool_name=tool_name,
            args_json=args_json,
            ok=ok,
            duration_ms=duration_ms,
            output_excerpt=output_excerpt,
            output_sha256=output_sha256,
            meta_json=meta_json,
        )