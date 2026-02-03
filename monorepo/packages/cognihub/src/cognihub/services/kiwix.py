from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from typing import Any, Optional, Tuple
from urllib.parse import quote

from ollama_cli.config import DEFAULT_KIWIX_MAX_CHARS, DEFAULT_KIWIX_ZIM_DIR
from ollama_cli.tools.kiwix_tools import KiwixTools


@lru_cache(maxsize=8)
def _tools(base_url: str) -> KiwixTools:
    # KiwixTools is synchronous (requests); we call it via asyncio.to_thread.
    return KiwixTools(kiwix_url=(base_url or "").rstrip("/"))


def _parse_content_ref(path_or_url: str) -> Optional[Tuple[str, str]]:
    """Return (zim, path) from /content/<zim>/<path> reference."""
    s = (path_or_url or "").strip()
    if not s:
        return None

    # Normalize full URL -> path portion
    if s.startswith("http") and "/content/" in s:
        s = "/content/" + s.split("/content/", 1)[1]

    if not s.startswith("/content/"):
        return None

    rest = s.split("/content/", 1)[1]
    parts = rest.split("/", 1)
    if len(parts) != 2:
        return None
    zim = parts[0].strip()
    p = parts[1].strip()
    if not zim or not p:
        return None
    return (zim, p)


def _content_url(base_url: str, zim: str, path: str) -> str:
    safe_zim = quote(zim, safe="-._~")
    safe_path = quote(path.lstrip("/"), safe="/-._~")
    return f"{base_url.rstrip('/')}/content/{safe_zim}/{safe_path}"


async def search(base_url: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    base_url = (base_url or "").rstrip("/")
    q = (query or "").strip()
    if not base_url or not q:
        return []

    count = max(1, min(int(top_k), 25))
    try:
        hits = await asyncio.to_thread(_tools(base_url).search_rss, q, None, count, 0)
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for h in hits or []:
        if not isinstance(h, dict):
            continue
        title = (h.get("title") or "").strip()
        zim = (h.get("zim") or "").strip()
        p = (h.get("path") or "").strip()
        if not zim or not p:
            continue
        path_ref = f"/content/{zim}/{p.lstrip('/')}"
        out.append(
            {
                "title": title or p,
                "path": path_ref,
                "url": _content_url(base_url, zim, p),
                "snippet": (h.get("snippet") or "").strip(),
            }
        )
        if len(out) >= count:
            break
    return out


async def fetch_page(base_url: str, path: str) -> dict[str, Any] | None:
    base_url = (base_url or "").rstrip("/")
    if not base_url:
        return None
    ref = _parse_content_ref(path)
    if not ref:
        return None
    zim, p = ref

    try:
        raw = await asyncio.to_thread(_tools(base_url).open_raw, zim, p, DEFAULT_KIWIX_MAX_CHARS)
    except Exception:
        return None

    text = (raw.get("content") or "").strip() if isinstance(raw, dict) else ""
    if not text:
        return None

    url = raw.get("url") if isinstance(raw, dict) else None
    return {
        "url": str(url or _content_url(base_url, zim, p)),
        "path": f"/content/{zim}/{p.lstrip('/')}" ,
        "zim": zim,
        "text": text,
    }


async def list_zims(zim_dir: Optional[str] = None) -> list[dict[str, Any]]:
    zim_dir = os.path.expanduser((zim_dir or "").strip() or DEFAULT_KIWIX_ZIM_DIR)
    # list_zims doesn't require a running kiwix server; base_url is irrelevant.
    try:
        return await asyncio.to_thread(_tools("http://127.0.0.1:8081").list_zims, zim_dir)
    except Exception:
        return []
