from __future__ import annotations

import os
import logging
from typing import Dict, List, Tuple

import httpx
from bs4 import BeautifulSoup

from ..stores import webstore
from .. import config as ch_config
from .search_cache import get_search_cache, get_rate_limiter

logger = logging.getLogger(__name__)


class SearchError(Exception):
    """Raised when search provider blocks or fails."""
    pass


async def ddg_search(http: httpx.AsyncClient, query: str, n: int = 8) -> list[str]:
    """DuckDuckGo HTML search with proper failure detection."""
    q = (query or "").strip()
    if not q:
        return []
    
    url = "https://html.duckduckgo.com/html/"  # Use the final redirect target
    headers = {
        "User-Agent": str(ch_config.config.web_user_agent or "ContextHarbor/1.0"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://duckduckgo.com",
        "Referer": "https://duckduckgo.com/",
    }
    
    try:
        r = await http.post(
            url, 
            data={"q": q}, 
            headers=headers, 
            timeout=15.0, 
            follow_redirects=False  # Don't auto-follow redirects
        )
        
        # Log response details for debugging
        logger.info(
            f"DDG response: status={r.status_code}, url={str(r.url)}, "
            f"content_len={len(r.text)}, location={r.headers.get('Location', 'None')}"
        )
        
        # Check for redirects that go outside DDG (likely blocking)
        if r.status_code in (301, 302, 303, 307, 308):
            location = r.headers.get("Location", "")
            if location and "duckduckgo.com" not in location.lower():
                raise SearchError(
                    f"DDG redirected to external site (likely blocked): status={r.status_code}, location={location}"
                )
        
        # Check for non-200 responses
        if r.status_code != 200:
            raise SearchError(
                f"DDG returned non-200 status: {r.status_code}"
            )
        
        # Check for tiny responses or captcha/redirect pages
        if len(r.text) < 1000:
            if any(phrase in r.text.lower() for phrase in ["captcha", "robot", "blocked", "access denied"]):
                raise SearchError(
                    f"DDG returned blocking page: {len(r.text)} bytes"
                )
            else:
                logger.warning(f"DDG returned suspiciously small response: {len(r.text)} bytes")
        
        # Parse HTML
        soup = BeautifulSoup(r.text, "lxml")
        links: list[str] = []
        for a in soup.select("a.result__a"):
            href = str(a.get("href", ""))
            if href and href.startswith("http") and not webstore._is_blocked_url(href):
                links.append(href)
            if len(links) >= n:
                break
        
        return links
        
    except httpx.HTTPStatusError as e:
        raise SearchError(f"DDG HTTP error: {e}")
    except httpx.RequestError as e:
        raise SearchError(f"DDG request failed: {e}")


async def web_search_with_fallback(
    http: httpx.AsyncClient, 
    query: str, 
    n: int = 8
) -> tuple[list[str], str]:
    """Single-provider web search with caching + rate limiting."""
    
    # Check cache first
    cache = get_search_cache()
    cached_results = cache.get(query, n)
    if cached_results is not None:
        logger.info(f"Returning cached results for query: {query[:50]}...")
        return cached_results, "cache_success"
    
    provider = str(ch_config.config.search_provider or "ddg").strip().lower()
    
    rate_limiter = get_rate_limiter()
    
    if provider != "ddg":
        raise SearchError(f"Unsupported search provider: {provider}")

    try:
        await rate_limiter.wait_if_needed(provider)
        results = await ddg_search(http, query, n)
    except SearchError:
        raise
    except Exception as exc:
        raise SearchError(f"Search failed: {exc}")

    if results:
        cache.set(query, n, results)
    return results, "ddg_success"
