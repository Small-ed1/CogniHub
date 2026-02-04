from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from ..stores import webstore


@dataclass
class IngestResult:
    url: str
    ok: bool
    error: str | None = None
    page_id: int | None = None


class WebIngestQueue:
    def __init__(self, concurrency: int = 3):
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._concurrency = max(1, concurrency)
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()
        self._seen: set[str] = set()

    async def start(self) -> None:
        self._stop.clear()
        for _ in range(self._concurrency):
            self._tasks.append(asyncio.create_task(self._worker()))

    async def stop(self) -> None:
        self._stop.set()
        for _ in self._tasks:
            await self._queue.put("__stop__")
        for t in self._tasks:
            t.cancel()
        self._tasks = []

    async def _worker(self) -> None:
        while True:
            url = await self._queue.get()
            if url == "__stop__":
                break
            try:
                page = await webstore.upsert_page_from_url(url, force=False)
                _ = page.get("id")
            except Exception:
                pass

    async def enqueue(self, url: str) -> None:
        url = (url or "").strip()
        if not url or url in self._seen:
            return
        self._seen.add(url)
        await self._queue.put(url)
