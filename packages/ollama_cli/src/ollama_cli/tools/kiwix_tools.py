"""Kiwix tools for offline content access.

This module provides tools for accessing offline content via Kiwix ZIM files,
using text_extract utilities to avoid circular dependencies with WebTools.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote
import xml.etree.ElementTree as ET

import requests  # type: ignore

from ..config import (
    DEFAULT_KIWIX_MAX_CHARS,
    DEFAULT_KIWIX_SEARCH_COUNT,
    DEFAULT_KIWIX_URL,
    DEFAULT_KIWIX_ZIM_DIR,
)
from ..errors import ToolTimeoutError
from ..text_extract import html_to_text, clean_ws
from .core import KiwixToolError, SearchResult


class KiwixTools:
    """Kiwix integration via kiwix-serve HTTP.
    
    Provides access to offline content in ZIM files through kiwix-serve.
    """
    
    def __init__(self, kiwix_url: str = DEFAULT_KIWIX_URL, timeout: int = 10,
                 min_delay_s: float = 0.2, cache_minutes: int = 30):
        """Initialize Kiwix tools.
        
        Args:
            kiwix_url: Base URL for kiwix-serve instance
            timeout: Request timeout in seconds
            min_delay_s: Minimum delay between requests (rate limiting)
            cache_minutes: Cache duration for requests
        """
        self.kiwix_url = kiwix_url.rstrip("/")
        self.timeout = timeout
        self.min_delay_s = min_delay_s
        self._last_req_at = 0.0
        self._cache_minutes = cache_minutes
        self._cache: Dict[str, Tuple[float, Any]] = {}
        
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ollama-cli-kiwix/1.0"})

    def ping(self) -> bool:
        """Return True if the configured kiwix-serve is reachable."""
        try:
            r = self.session.get(f"{self.kiwix_url}/", timeout=min(self.timeout, 3))
            return 200 <= r.status_code < 500
        except Exception:
            return False

    def catalog_search_books(self, query: str, count: int = 10) -> List[Dict[str, Any]]:
        """Search the OPDS catalog for available books.

        Returns:
            List of dicts: {"title": str, "zim_id": str}
        """
        self._rate_limit()
        q = (query or "").strip()
        if not q:
            raise KiwixToolError("query cannot be empty")

        count = min(max(int(count), 1), 50)
        cache_key = self._cache_key("catalog_search", {"query": q, "count": count})
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        try:
            r = self.session.get(
                f"{self.kiwix_url}/catalog/search",
                params={"query": q, "count": count},  # type: ignore[arg-type]
                timeout=self.timeout,
            )
            r.raise_for_status()
        except requests.Timeout as e:
            raise ToolTimeoutError(f"kiwix catalog search timed out: {e}") from e
        except requests.RequestException as e:
            raise KiwixToolError(f"catalog search request failed: {e}") from e

        try:
            root = ET.fromstring(r.text)
        except ET.ParseError as e:
            raise KiwixToolError(f"invalid OPDS XML: {e}") from e

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        out: List[Dict[str, Any]] = []
        for entry in root.findall("atom:entry", ns):
            title = (entry.findtext("atom:title", "", ns) or "").strip()
            zim_id: Optional[str] = None
            for link in entry.findall("atom:link", ns):
                href = (link.get("href") or "").strip()
                if href.startswith("/content/"):
                    zim_id = href.split("/content/", 1)[1].strip("/")
                    break
            if not zim_id:
                continue
            out.append({"title": title, "zim_id": zim_id})

        self._set_cached(cache_key, out)
        return out

    def search_rss(self, query: str, zim: Optional[str], count: int = 8, start: int = 0) -> List[Dict[str, Any]]:
        """Search via kiwix-serve /search RSS endpoint.

        Args:
            query: Search query
            zim: Optional content id to restrict search (None = search across library)
            count: Number of results
            start: Start offset

        Returns:
            List of dicts: {"title": str, "zim": str, "path": str, "snippet": str}
        """
        self._rate_limit()
        q = (query or "").strip()
        if not q:
            raise KiwixToolError("query cannot be empty")

        count = min(max(int(count), 1), 50)
        start = max(int(start), 0)

        cache_key = self._cache_key(
            "search_rss",
            {"query": q, "zim": zim or "", "count": count, "start": start},
        )
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        params: Dict[str, Any] = {
            "pattern": q,
            "format": "xml",
            "pageLength": count,
            "start": start,
        }
        if zim:
            params["content"] = zim

        try:
            r = self.session.get(
                f"{self.kiwix_url}/search",
                params=params,  # type: ignore[arg-type]
                timeout=self.timeout,
            )
            r.raise_for_status()
        except requests.Timeout as e:
            raise ToolTimeoutError(f"kiwix search timed out: {e}") from e
        except requests.RequestException as e:
            raise KiwixToolError(f"search request failed: {e}") from e

        try:
            root = ET.fromstring(r.text)
        except ET.ParseError as e:
            raise KiwixToolError(f"invalid RSS XML: {e}") from e

        out: List[Dict[str, Any]] = []
        for item in root.findall("./channel/item"):
            title = (item.findtext("title", "") or "").strip()
            link = (item.findtext("link", "") or "").strip()
            desc = (item.findtext("description", "") or "").strip()
            if not title or not link:
                continue

            zim_id = ""
            path = ""
            if link.startswith("/content/"):
                rest = link.split("/content/", 1)[1]
                parts = rest.split("/", 1)
                if len(parts) == 2:
                    zim_id, path = parts[0].strip(), unquote(parts[1].strip())
                else:
                    # Best-effort
                    path = unquote(rest.strip())
                    zim_id = (zim or "").strip()
            else:
                # Unknown shape; treat as path-only within requested ZIM.
                path = unquote(link)
                zim_id = (zim or "").strip()

            if not zim_id or not path:
                continue

            out.append(
                {
                    "title": title,
                    "zim": zim_id,
                    "path": path,
                    "snippet": self._clean_ws(desc)[:350],
                }
            )

        self._set_cached(cache_key, out)
        return out
    
    def _rate_limit(self):
        """Apply rate limiting between requests."""
        dt = time.time() - self._last_req_at
        if dt < self.min_delay_s:
            time.sleep(self.min_delay_s - dt)
        self._last_req_at = time.time()
    
    def _cache_key(self, endpoint: str, params: Dict[str, Any]) -> str:
        """Generate cache key for request."""
        key = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
        import hashlib
        return hashlib.md5(key.encode()).hexdigest()
    
    def _get_cached(self, cache_key: str) -> Optional[Any]:
        """Get cached response if valid."""
        if cache_key in self._cache:
            timestamp, data = self._cache[cache_key]
            if time.time() - timestamp < self._cache_minutes * 60:
                return data
            else:
                del self._cache[cache_key]
        return None
    
    def _set_cached(self, cache_key: str, data: Any):
        """Cache response with timestamp."""
        self._cache[cache_key] = (time.time(), data)
    
    def suggest(self, zim: str, term: str, count: int = 8) -> List[Dict[str, Any]]:
        """Get suggestions for content completion.
        
        Args:
            zim: ZIM file name
            term: Term to complete
            count: Number of suggestions
            
        Returns:
            List of suggestion items from Kiwix
        """
        self._rate_limit()
        if not zim or not term:
            raise KiwixToolError("zim and term are required")
        
        cache_key = self._cache_key("suggest", {"zim": zim, "term": term, "count": count})
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        
        try:
            response = self.session.get(
                f"{self.kiwix_url}/suggest",
                params={"content": zim, "term": term, "count": count},  # type: ignore[arg-type]
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise KiwixToolError("suggest returned unexpected JSON shape")
            self._set_cached(cache_key, data)
            return data
        except requests.Timeout as e:
            raise ToolTimeoutError(f"kiwix suggest timed out: {e}") from e
        except requests.RequestException as e:
            raise KiwixToolError(f"suggest failed: {e}") from e
        except ValueError as e:
            raise KiwixToolError(f"suggest returned invalid JSON: {e}") from e
    
    def search_xml(self, query: str, zim: str, count: int = 8, start: int = 0) -> List[SearchResult]:
        """Search ZIM content.

        Notes:
            Prefer the kiwix-serve `/search` RSS endpoint when available.
            Fall back to `/suggest` if `/search` is unavailable.

        Args:
            query: Search query
            zim: Kiwix content id (usually ZIM filename without .zim)
            count: Number of results
            start: Start index for pagination

        Returns:
            List of search results (title + content path)
        """
        self._rate_limit()
        if not query.strip():
            raise KiwixToolError("query cannot be empty")
        if not zim:
            raise KiwixToolError("zim is required")

        # Limit count to reasonable range
        count = min(max(count, 1), 50)
        start = max(start, 0)

        cache_key = self._cache_key("search", {"query": query, "zim": zim, "count": count, "start": start})
        cached = self._get_cached(cache_key)
        if cached:
            return [SearchResult(**r) for r in cached.get("results", [])]

        # 1) Try RSS /search endpoint
        try:
            rows = self.search_rss(query, zim=zim, count=count, start=start)
            results = [SearchResult(title=r["title"], url=r["path"], snippet=r.get("snippet", "")) for r in rows]
            self._set_cached(cache_key, {"results": [r.__dict__ for r in results]})
            return results
        except Exception:
            pass

        # 2) Fallback: suggest (prefix-oriented)
        terms: List[str] = []
        q = query.strip()
        terms.append(q)
        if " " in q:
            parts = [p for p in q.split(" ") if p]
            if parts:
                terms.append(parts[-1])
                terms.extend(parts)

        seen_paths: set[str] = set()
        results2: List[SearchResult] = []
        for term in terms:
            try:
                suggestions = self.suggest(zim, term, count + start)
            except Exception:
                continue
            for item in suggestions or []:
                path = (item.get("path") or "").strip()
                if not path or path in seen_paths:
                    continue
                seen_paths.add(path)
                title = (item.get("value") or "").strip() or (item.get("label") or "").strip()
                title = title.replace("<b>", "").replace("</b>", "")
                results2.append(SearchResult(title=title, url=path, snippet=""))
                if len(results2) >= count + start:
                    break
            if len(results2) >= count + start:
                break

        sliced = results2[start:start + count]
        self._set_cached(cache_key, {"results": [r.__dict__ for r in sliced]})
        return sliced
    
    def open_raw(self, zim: str, path: str, max_chars: int = 12000) -> Dict[str, Any]:
        """Fetch raw content from ZIM file.
        
        Args:
            zim: ZIM file name
            path: Content path within ZIM
            max_chars: Maximum characters to extract
            
        Returns:
            Dictionary with content and metadata
        """
        self._rate_limit()
        if not zim or not path:
            raise KiwixToolError("zim and path are required")
        
        cache_key = self._cache_key("open", {"zim": zim, "path": path, "max_chars": max_chars})
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        try:
            # kiwix-serve content paths are served as:
            #   /content/<content-id>/<article-path>
            # The old /content?content=...&url=... endpoint is not supported
            # by current kiwix-serve releases.
            safe_zim = quote(zim, safe="-._~")
            safe_path = quote(path.lstrip("/"), safe="/-._~")
            url = f"{self.kiwix_url}/content/{safe_zim}/{safe_path}"
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            # Get content and metadata
            body = response.text
            content_type = response.headers.get('content-type', 'text/plain')
            
            # Extract readable text if HTML
            text = body
            if "text/html" in content_type.lower():
                # Use text_extract utilities to avoid circular dependency
                text = html_to_text(body)
            
            # Truncate if necessary
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]
            
            result = {
                "zim": zim,
                "path": path,
                "url": url,
                "content_type": content_type,
                "content": text,
                "size": len(text),
                "truncated": truncated,
            }
            
            self._set_cached(cache_key, result)
            return result
            
        except requests.Timeout as e:
            raise ToolTimeoutError(f"kiwix open timed out: {e}") from e
        except requests.RequestException as e:
            raise KiwixToolError(f"open request failed: {e}") from e
    
    def list_zims(self, zim_dir: str) -> List[Dict[str, Any]]:
        """List available ZIM files from a directory.

        This does not require kiwix-serve to be running.

        Args:
            zim_dir: Directory containing ZIM files (and optionally library.xml)

        Returns:
            List of ZIM file information.
        """
        if not zim_dir:
            raise KiwixToolError("zim_dir is required")

        p = Path(os.path.expanduser(zim_dir))
        if not p.exists() or not p.is_dir():
            raise KiwixToolError(f"zim_dir not found or not a directory: {zim_dir}")

        lib_meta: Dict[str, Dict[str, Any]] = {}
        lib_path = p / "library.xml"
        if lib_path.exists() and lib_path.is_file():
            try:
                root = ET.parse(str(lib_path)).getroot()
                for book in root.findall("book"):
                    path_attr = (book.get("path") or "").strip()
                    if not path_attr:
                        continue
                    file_name = os.path.basename(path_attr)
                    lib_meta[file_name] = {
                        "title": (book.get("title") or "").strip(),
                        "description": (book.get("description") or "").strip(),
                        "language": (book.get("language") or "").strip(),
                        "creator": (book.get("creator") or "").strip(),
                        "publisher": (book.get("publisher") or "").strip(),
                        "tags": (book.get("tags") or "").strip(),
                        "article_count": _safe_int(book.get("articleCount")),
                        "zim_size_kib": _safe_int(book.get("size")),
                    }
            except Exception:
                # Best-effort enrichment only; listing should still work.
                lib_meta = {}

        results: List[Dict[str, Any]] = []
        for zim_file in sorted(p.glob("*.zim"), key=lambda x: x.name.lower()):
            stat = zim_file.stat()
            zim_id = zim_file.stem

            entry: Dict[str, Any] = {
                "zim_id": zim_id,
                "file_name": zim_file.name,
                "path": str(zim_file),
                "size_bytes": stat.st_size,
                "mtime_s": int(stat.st_mtime),
            }

            meta = lib_meta.get(zim_file.name)
            if meta:
                entry.update({k: v for k, v in meta.items() if v not in (None, "")})

            results.append(entry)

        return results
    
    def _clean_ws(self, s: str) -> str:
        """Clean whitespace (alias for text_extract.clean_ws)."""
        return clean_ws(s)


def tool_kiwix_search(
    kiwix_tools: KiwixTools,
    query: str,
    zim: str,
    count: int = DEFAULT_KIWIX_SEARCH_COUNT,
    start: int = 0,
) -> str:
    """Tool wrapper for Kiwix search.
    
    Args:
        kiwix_tools: KiwixTools instance
        query: Search query
        zim: ZIM file name
        count: Number of results (default 8)
        start: Start index for pagination (default 0)
        
    Returns:
        JSON string with search results
    """
    results = kiwix_tools.search_xml(query, zim, count, start)

    return json.dumps(
        {
            "query": query,
            "zim": zim,
            "results": [result.__dict__ for result in results],
            "count": len(results),
            "start": start,
        },
        indent=2,
        ensure_ascii=False,
    )


def tool_kiwix_open(
    kiwix_tools: KiwixTools,
    zim: str,
    path: str,
    max_chars: int = DEFAULT_KIWIX_MAX_CHARS,
) -> str:
    """Tool wrapper for opening Kiwix content.
    
    Args:
        kiwix_tools: KiwixTools instance
        zim: ZIM file name
        path: Content path within ZIM
        max_chars: Maximum characters to extract (default 12000)
        
    Returns:
        JSON string with content
    """
    result = kiwix_tools.open_raw(zim, path, max_chars)
    return json.dumps(result, indent=2, ensure_ascii=False)


def tool_kiwix_suggest(kiwix_tools: KiwixTools, zim: str, term: str, count: int = 8) -> str:
    """Tool wrapper for Kiwix suggestions.
    
    Args:
        kiwix_tools: KiwixTools instance
        zim: ZIM file name
        term: Term to complete
        count: Number of suggestions (default 8)
        
    Returns:
        JSON string with suggestions
    """
    result = kiwix_tools.suggest(zim, term, count)
    return json.dumps(result, indent=2, ensure_ascii=False)


def tool_kiwix_list_zims(kiwix_tools: KiwixTools, zim_dir: str = DEFAULT_KIWIX_ZIM_DIR) -> str:
    """Tool wrapper for listing ZIM files.
    
    Args:
        kiwix_tools: KiwixTools instance
        zim_dir: Directory containing ZIM files (default '~/zims')
        
    Returns:
        JSON string with ZIM file list
    """
    results = kiwix_tools.list_zims(zim_dir)
    return json.dumps(
        {
            "zim_dir": zim_dir,
            "zims": results,
            "count": len(results),
        },
        indent=2,
        ensure_ascii=False,
    )


def _safe_int(v: Optional[str]) -> Optional[int]:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None
