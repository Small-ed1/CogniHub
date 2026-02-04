#!/usr/bin/env python3
"""
CogniHub Hybrid Router - Clean Production Version

Intent-based routing between GPU and CPU Ollama backends.
"""

from __future__ import annotations

import os
import json
import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Backend:
    name: str
    url: str
    is_gpu: bool


class HybridRouter:
    def __init__(self, backends: List[Backend]) -> None:
        if not backends:
            raise ValueError("HybridRouter requires at least one backend")

        self.backends = backends
        self._health: Dict[str, bool] = {b.name: True for b in backends}
        self._lock = asyncio.Lock()
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(60.0))

        self.model_affinity: Dict[str, str] = {}

    async def close(self) -> None:
        await self.http.aclose()

    async def _ping(self, b: Backend) -> bool:
        try:
            r = await self.http.get(f"{b.url}/api/version", timeout=3.0)
            r.raise_for_status()
            return True
        except Exception:
            return False

    async def refresh_health(self) -> None:
        results = await asyncio.gather(
            *(self._ping(b) for b in self.backends),
            return_exceptions=True
        )

        async with self._lock:
            for b, ok in zip(self.backends, results):
                self._health[b.name] = (ok is True)

    def _is_vram_error(self, err: Exception) -> bool:
        s = str(err).lower()
        indicators = (
            "out of memory", "oom", "vram",
            "cuda", "cublas", "hip", "rocm",
            "vulkan", "vk_", "insufficient memory",
            "failed to allocate", "404", "not found"
        )
        return any(x in s for x in indicators)

    async def _choose_backend(self, model: str, intent: str):
        await self.refresh_health()

        gpu = None
        cpu = None
        for b in self.backends:
            if b.is_gpu and self._health.get(b.name, False):
                gpu = b
            elif not b.is_gpu and self._health.get(b.name, False):
                cpu = b

        if not gpu and not cpu:
            raise RuntimeError("No healthy backends available")

        def other_healthy(primary: Backend) -> Optional[Backend]:
            for b in self.backends:
                if b.name != primary.name and self._health.get(b.name, False):
                    return b
            return None

        if intent == "heavy":
            primary = cpu or gpu
            if not primary:
                raise RuntimeError("No healthy primary backend for heavy intent")
            return primary, other_healthy(primary)

        # fast intent
        affinity = self.model_affinity.get(model)
        if affinity and self._health.get(affinity, False):
            primary = next((b for b in self.backends if b.name == affinity), None)
            if primary and self._health.get(primary.name, False):
                return primary, other_healthy(primary)

        primary = gpu or cpu
        if not primary:
            raise RuntimeError("No healthy primary backend for fast intent")
        return primary, other_healthy(primary)

    async def chat(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        options: Optional[Dict[str, Any]] = None,
        keep_alive: Optional[str] = None,
        intent: str = "fast",
    ) -> Dict[str, Any]:
        if intent not in ("fast", "heavy"):
            intent = "fast"

        primary, fallback = await self._choose_backend(model, intent)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if tools is not None:
            payload["tools"] = tools
        if options is not None:
            payload["options"] = options
        if keep_alive:
            payload["keep_alive"] = keep_alive

        async def call_backend(b: Backend) -> Dict[str, Any]:
            r = await self.http.post(f"{b.url}/api/chat", json=payload)
            r.raise_for_status()
            return r.json()

        try:
            out = await call_backend(primary)
            if intent == "fast":
                self.model_affinity[model] = primary.name
            return out
        except Exception as e:
            logger.warning("Primary backend %s failed for model=%s: %s", primary.name, model, e)

            if primary.is_gpu and self._is_vram_error(e):
                logger.info("GPU OOM detected, pinning %s to CPU", model)
                self.model_affinity[model] = "cpu"

            if fallback:
                out = await call_backend(fallback)
                if intent == "fast":
                    self.model_affinity[model] = fallback.name
                return out

        raise RuntimeError(f"All backends failed for model={model}")

    async def health_check(self) -> Dict[str, Any]:
        health = {}
        
        for backend in self.backends:
            try:
                resp = await self.http.get(f"{backend.url}/api/version", timeout=3.0)
                version = resp.json().get("version", "unknown")
                health[backend.name] = {
                    "status": "healthy",
                    "version": version,
                    "url": backend.url,
                    "is_gpu": backend.is_gpu
                }
            except Exception as e:
                health[backend.name] = {
                    "status": "unhealthy",
                    "error": str(e),
                    "url": backend.url,
                    "is_gpu": backend.is_gpu
                }
        
        return health

    async def list_models(self) -> Dict[str, List[str]]:
        result = {}
        
        for backend in self.backends:
            try:
                resp = await self.http.get(f"{backend.url}/api/tags")
                resp.raise_for_status()
                models = [m["name"] for m in resp.json().get("models", [])]
                result[backend.name] = models
            except Exception as e:
                logger.warning("Failed to list models on %s: %s", backend.name, e)
                result[backend.name] = []
        
        return result


def _detect_backends() -> List[Backend]:
    gpu_url = os.getenv("OLLAMA_GPU_URL", "http://127.0.0.1:11434")
    cpu_url = os.getenv("OLLAMA_CPU_URL", "http://127.0.0.1:11435")

    return [
        Backend(name="gpu", url=gpu_url, is_gpu=True),
        Backend(name="cpu", url=cpu_url, is_gpu=False),
    ]


_router: Optional[HybridRouter] = None


def get_router() -> HybridRouter:
    global _router
    if _router is None:
        _router = HybridRouter(_detect_backends())
    return _router


async def smart_chat(model: str, messages: List[Dict[str, Any]], intent: str = "fast", **kwargs: Any) -> Dict[str, Any]:
    return await get_router().chat(model=model, messages=messages, intent=intent, **kwargs)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Hybrid Router CLI")
    parser.add_argument("--check", action="store_true", help="Check backend health")
    parser.add_argument("--models", action="store_true", help="List models per backend")
    args = parser.parse_args()

    async def main():
        router = get_router()
        if args.check:
            print(json.dumps(await router.health_check(), indent=2))
        elif args.models:
            print(json.dumps(await router.list_models(), indent=2))
        else:
            print("Use --check or --models")

    asyncio.run(main())