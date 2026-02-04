from __future__ import annotations

import os
import logging
from typing import Dict, List, Tuple

import httpx
from bs4 import BeautifulSoup

from ..stores import webstore
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
        "User-Agent": os.getenv(
            "WEB_UA",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ),
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


async def searxng_search(http: httpx.AsyncClient, query: str, n: int = 8) -> list[str]:
    """SearxNG JSON search fallback."""
    searxng_url = os.getenv("SEARXNG_URL", "http://localhost:8080")
    
    try:
        params = {
            "q": query,
            "format": "json",
            "engines": "duckduckgo,google,bing",  # Use multiple engines
        }
        
        r = await http.get(
            f"{searxng_url}/search",
            params=params,
            timeout=15.0,
            headers={"User-Agent": os.getenv("WEB_UA", "")}
        )
        
        logger.info(f"SearxNG response: status={r.status_code}, content_len={len(r.text)}")
        
        if r.status_code != 200:
            raise SearchError(f"SearxNG returned status: {r.status_code}")
        
        data = r.json()
        links: list[str] = []
        
        for result in data.get("results", []):
            url = result.get("url", "")
            if url and not webstore._is_blocked_url(url):
                links.append(url)
            if len(links) >= n:
                break
        
        return links
        
    except Exception as e:
        raise SearchError(f"SearxNG search failed: {e}")


async def web_search_with_fallback(
    http: httpx.AsyncClient, 
    query: str, 
    n: int = 8
) -> tuple[list[str], str]:
    """Try search providers in order of preference with caching and rate limiting."""
    
    # Check cache first
    cache = get_search_cache()
    cached_results = cache.get(query, n)
    if cached_results is not None:
        logger.info(f"Returning cached results for query: {query[:50]}...")
        return cached_results, "cache_success"
    
    provider = os.getenv("COGNIHUB_SEARCH_PROVIDER", "ddg,searxng")
    providers = [p.strip() for p in provider.split(",")]
    
    rate_limiter = get_rate_limiter()
    
    for prov in providers:
        try:
            # Apply rate limiting
            await rate_limiter.wait_if_needed(prov)
            
            if prov == "ddg":
                results = await ddg_search(http, query, n)
            elif prov == "searxng":
                results = await searxng_search(http, query, n)
            else:
                logger.warning(f"Unknown provider: {prov}")
                continue
            
            # Cache successful non-empty results only
            if results:
                cache.set(query, n, results)
            return results, f"{prov}_success"
            
        except SearchError as e:
            logger.warning(f"Search provider {prov} failed: {e}")
            continue
        except Exception as e:
            logger.error(f"Unexpected error from {prov}: {e}")
            continue
    
    # All providers failed
    raise SearchError(f"All search providers failed for query: {query}")
