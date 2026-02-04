from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


@dataclass
class ModelInfo:
    name: str
    size: int


class ModelRegistry:
    def __init__(self, base_url: str, ttl_seconds: int = 30):
        self._base_url = base_url.rstrip("/")
        self._ttl = ttl_seconds
        self._cache: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def _fetch_tags(self, http: httpx.AsyncClient) -> dict[str, Any]:
        r = await http.get(f"{self._base_url}/api/tags", timeout=3.0)
        r.raise_for_status()
        return r.json()

    async def list_models(self, http: httpx.AsyncClient) -> list[ModelInfo]:
        async with self._lock:
            now = time.time()
            cached = self._cache.get("models")
            if cached and now - cached["ts"] < self._ttl:
                return cached["data"]

            data = await self._fetch_tags(http)
            models = []
            for m in data.get("models", []):
                name = m.get("name")
                if not name:
                    continue
                models.append(ModelInfo(name=name, size=int(m.get("size") or 0)))
            models.sort(key=lambda x: x.size)
            self._cache["models"] = {"ts": now, "data": models}
            return models

    async def available_model_names(self, http: httpx.AsyncClient) -> list[str]:
        models = await self.list_models(http)
        return [m.name for m in models if "embed" not in m.name.lower()]

    async def available_embed_models(self, http: httpx.AsyncClient) -> list[str]:
        models = await self.list_models(http)
        return [m.name for m in models if "embed" in m.name.lower()]

    async def validate_model(self, http: httpx.AsyncClient, model: str) -> None:
        allowed = await self.available_model_names(http)
        if model not in allowed:
            raise ValueError(f"Model '{model}' not available. Available models: {', '.join(allowed)}")

    async def validate_embed_model(self, http: httpx.AsyncClient, model: str) -> None:
        allowed = await self.available_embed_models(http)
        if model not in allowed:
            raise ValueError(f"Embed model '{model}' not available. Available models: {', '.join(allowed)}")
