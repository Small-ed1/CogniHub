"""Web tools for web search and content extraction.

This module provides web-based tools including search via SearxNG and
content extraction from web pages, using the text_extract utilities
to avoid circular dependencies.
"""

import json
import hashlib
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests  # type: ignore

from ..config import DEFAULT_SEARXNG_URL, DEFAULT_WEB_MAX_CHARS, DEFAULT_WEB_SEARCH_COUNT
from ..errors import ToolTimeoutError
from ..text_extract import html_to_text, clean_ws
from .core import WebToolError, SearchResult



class WebTools:
    """Web search and content extraction tools."""
    
    @staticmethod
    def _time_range(recency_days: int) -> Optional[str]:
        """Convert recency days to time_range format for SearxNG.
        
        Args:
            recency_days: Number of days
            
        Returns:
            Time range string or None
        """
        if recency_days <= 0:
            return None
        if recency_days <= 1:
            return "day"
        if recency_days <= 7:
            return "week"
        if recency_days <= 31:
            return "month"
        return "year"
    
    def __init__(self, searxng_url: str = DEFAULT_SEARXNG_URL, timeout: int = 10, cache_minutes: int = 30):
        """Initialize web tools.
        
        Args:
            searxng_url: Base URL for SearxNG instance
            timeout: Request timeout in seconds
            cache_minutes: Cache duration for requests
        """
        # Normalize URL (remove trailing slash and ensure consistent format)
        self.searxng_url = searxng_url.rstrip("/")
        self.timeout = timeout
        self.cache_minutes = cache_minutes
        self._cache: Dict[str, Tuple[float, Any]] = {}
        
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ollama-cli-web/1.0"})
    
    def _cache_key(self, endpoint: str, params: Dict[str, Any]) -> str:
        """Generate cache key for request."""
        key = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
        return hashlib.md5(key.encode()).hexdigest()
    
    def _get_cached(self, cache_key: str) -> Optional[Any]:
        """Get cached response if valid."""
        if cache_key in self._cache:
            timestamp, data = self._cache[cache_key]
            if time.time() - timestamp < self.cache_minutes * 60:
                return data
            else:
                del self._cache[cache_key]
        return None
    
    def _set_cached(self, cache_key: str, data: Any):
        """Cache response with timestamp."""
        self._cache[cache_key] = (time.time(), data)
    
    def search(self, query: str, count: int = 8, recency_days: int = 365, 
              source: str = "auto") -> List[SearchResult]:
        """Search web using SearxNG with caching."""
        if not query.strip():
            raise WebToolError("Query cannot be empty")
        
        # Limit count to reasonable range
        count = min(max(count, 1), 20)
        
        # Build search parameters
        params = {
            "q": query,
            "format": "json",
            "engines": "",
            "language": "en",
            "count": count,
        }
        
        # Add recency filter if specified
        time_range = self._time_range(recency_days)
        if time_range:
            params["time_range"] = time_range
        
        # Add source preference
        if source != "auto":
            params["engines"] = source
        
        # Check cache first
        cache_key = self._cache_key("search", params)
        cached = self._get_cached(cache_key)
        if cached:
            return [SearchResult(**r) for r in cached.get("results", [])]
        
        try:
            # Accept either base URL (http://host:port) or full endpoint (http://host:port/search)
            endpoint = self.searxng_url
            if not endpoint.endswith("/search"):
                endpoint = f"{endpoint}/search"

            response = self.session.get(
                endpoint,
                params=params,  # type: ignore[arg-type]
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            
            # Extract and cache results
            results = []
            for result in data.get("results", []):
                results.append(SearchResult(
                    title=result.get("title", ""),
                    url=result.get("url", ""),
                    snippet=self._clean_ws(result.get("content", ""))[:350],
                ))
            
            # Cache the results
            self._set_cached(cache_key, {"results": [r.__dict__ for r in results]})
            return results
            
        except requests.Timeout as e:
            raise ToolTimeoutError(f"Web search timed out: {e}") from e
        except requests.RequestException as e:
            raise WebToolError(f"Web search failed: {e}") from e
        except (KeyError, ValueError) as e:
            raise WebToolError(f"Invalid search response format: {e}") from e
    
    def open_url(self, url: str, mode: str = "auto", max_chars: int = 12000) -> Dict[str, Any]:
        """Fetch and extract content from a URL.
        
        Args:
            url: URL to fetch
            mode: Extraction mode ('auto', 'text', 'html')
            max_chars: Maximum characters to extract
            
        Returns:
            Dictionary with extracted content and metadata
        """
        if not url:
            raise WebToolError("URL is required")
        
        # Validate URL format
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise WebToolError(f"Invalid URL: {url}")
        
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            # Get content type
            content_type = response.headers.get('content-type', '').lower()
            
            if mode == "html" or 'text/html' in content_type:
                # HTML content - extract readable text
                if mode == "html":
                    text = response.text
                else:
                    text = html_to_text(response.text)
            elif 'text/plain' in content_type:
                # Plain text content
                text = response.text
            else:
                # Binary or other content - return as-is with metadata
                text = response.text[:min(max_chars, 1000)]
                return {
                    "url": url,
                    "content_type": content_type,
                    "content": text,
                    "size": len(response.content),
                    "truncated": True,
                    "extraction_mode": "raw",
                }
            
            # Truncate if necessary
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]
            
            return {
                "url": url,
                "content_type": content_type,
                "content": text,
                "size": len(text),
                "truncated": truncated,
                "extraction_mode": "text",
            }
            
        except requests.Timeout as e:
            raise ToolTimeoutError(f"Web open timed out: {e}") from e
        except requests.RequestException as e:
            raise WebToolError(f"Failed to fetch URL {url}: {e}") from e

    def _clean_ws(self, s: str) -> str:
        """Clean whitespace (alias for text_extract.clean_ws)."""
        return clean_ws(s)


def tool_web_search(
    web_tools: WebTools,
    query: str,
    count: int = DEFAULT_WEB_SEARCH_COUNT,
    recency_days: int = 365,
    source: str = "auto",
) -> str:
    """Tool wrapper for web search.
    
    Args:
        web_tools: WebTools instance
        query: Search query
        count: Number of results (default 8, max 20)
        recency_days: Filter to recent days (default 365, 0 = no filter)
        source: Search source (default 'auto')
        
    Returns:
        JSON string with search results
    """
    results = web_tools.search(query, count, recency_days, source)

    return json.dumps(
        {
            "query": query,
            "results": [result.__dict__ for result in results],
            "count": len(results),
        },
        indent=2,
        ensure_ascii=False,
    )


def tool_web_open(
    web_tools: WebTools,
    url: str,
    mode: str = "auto",
    max_chars: int = DEFAULT_WEB_MAX_CHARS,
) -> str:
    """Tool wrapper for URL content extraction.
    
    Args:
        web_tools: WebTools instance
        url: URL to fetch
        mode: Extraction mode ('auto', 'text', 'html')
        max_chars: Maximum characters to extract (default 12000)
        
    Returns:
        JSON string with extracted content
    """
    result = web_tools.open_url(url, mode, max_chars)
    return json.dumps(result, indent=2, ensure_ascii=False)
