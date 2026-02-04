"""Text extraction utilities - zero tool knowledge."""

import html as _html
import importlib
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Optional dependency globals
_trafilatura: Any = None
_beautifulsoup: Any = None
_web_deps_installed = False


_RE_STRIP_BLOCKS = re.compile(r"(?is)<(script|style|noscript)\b.*?>.*?</\1>")
_RE_STRIP_HEAD = re.compile(r"(?is)<head\b.*?>.*?</head>")
_RE_STRIP_COMMENTS = re.compile(r"(?is)<!--.*?-->")
_RE_STRIP_TAGS = re.compile(r"(?is)<[^>]+>")


def _basic_html_to_text(html: str) -> str:
    """Best-effort HTML -> text without optional dependencies."""
    s = html or ""
    # Remove blocks that are almost always noise.
    s = _RE_STRIP_BLOCKS.sub(" ", s)
    s = _RE_STRIP_HEAD.sub(" ", s)
    s = _RE_STRIP_COMMENTS.sub(" ", s)
    # Strip remaining tags.
    s = _RE_STRIP_TAGS.sub(" ", s)
    # Decode entities.
    s = _html.unescape(s)
    return clean_ws(s)


def ensure_web_deps() -> bool:
    """Validate optional web dependencies without side effects."""
    global _web_deps_installed, _trafilatura, _beautifulsoup
    if _web_deps_installed:
        return True
    
    # Check if dependencies are available by importing actual modules.
    # Use importlib to keep optional deps optional for type-checking.
    missing = []
    try:
        _trafilatura_mod = importlib.import_module("trafilatura")
    except ImportError:
        _trafilatura_mod = None
        missing.append("trafilatura")
    try:
        _bs4_mod = importlib.import_module("bs4")
    except ImportError:
        _bs4_mod = None
        missing.append("beautifulsoup4")  # Package name, not import name

    if missing:
        logger.info(
            "Optional web deps missing: %s. Install with `pip install ollama-cli[web]`.",
            ", ".join(missing),
        )
        return False
    # Bind the loaded modules to the module globals for runtime use
    _trafilatura = _trafilatura_mod
    _beautifulsoup = _bs4_mod
    _web_deps_installed = True
    return True


def html_to_text(html: str) -> str:
    """Convert HTML to readable text.
    
    Extracts the main text content from HTML using trafilatura if available,
    falling back to BeautifulSoup with basic cleaning if needed.
    
    Args:
        html: HTML content to convert
        
    Returns:
        Readable text content
    """
    if not ensure_web_deps():
        return _basic_html_to_text(html)
    
    # Try trafilatura first (better at extracting main content)
    try:
        if _trafilatura:
            text = _trafilatura.extract(html, favor_precision=True)
            if text:
                return clean_ws(text)
    except Exception:
        pass
    
    # Fallback to BeautifulSoup
    try:
        if _beautifulsoup:
            BeautifulSoup = getattr(_beautifulsoup, "BeautifulSoup", None)
            if BeautifulSoup:
                soup = BeautifulSoup(html, "html.parser")
                return clean_ws(soup.get_text(" "))
        return _basic_html_to_text(html)
    except Exception:
        return _basic_html_to_text(html)


def clean_ws(s: str) -> str:
    """Clean whitespace in text.
    
    Normalizes whitespace by collapsing multiple spaces and line breaks
    into single spaces and trimming leading/trailing whitespace.
    
    Args:
        s: Text string to clean
        
    Returns:
        Text with normalized whitespace
    """
    return " ".join(s.split())
