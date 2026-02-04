"""Core tool system with registry and lazy loading.

This module provides tool data structures and specifications.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List

from ..errors import ToolError, WebToolError, KiwixToolError


@dataclass
class SearchResult:
    """Search result from web or Kiwix tools."""
    title: str
    url: str
    snippet: str


def _tool_schema(name: str, description: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Create tool schema definition in OpenAI format.
    
    Args:
        name: Tool function name
        description: Tool description
        parameters: JSON schema for parameters
        
    Returns:
        Complete tool schema dictionary
    """
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


# Tool specifications (lightweight, no heavy dependencies)
TOOL_SPECS: List[Dict[str, Any]] = [
    _tool_schema(
        name="get_time",
        description="Get current time and timezone information",
        parameters={
            "type": "object",
            "properties": {
                "tz": {
                    "type": "string",
                    "description": "Timezone (e.g., 'local', 'UTC', 'America/New_York')",
                    "default": "local",
                }
            },
        },
    ),
    _tool_schema(
        name="read_file",
        description="Read the contents of a file",
        parameters={
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "max_bytes": {
                    "type": "integer",
                    "description": "Maximum bytes to read (default 8000)",
                    "default": 8000,
                },
            },
        },
    ),
    _tool_schema(
        name="web_search",
        description="Search the web for information",
        parameters={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "count": {
                    "type": "integer",
                    "description": "Number of results (default 8, max 20)",
                    "default": 8,
                },
                "recency_days": {
                    "type": "integer",
                    "description": "Filter to recent days (default 365, 0 = no filter)",
                    "default": 365,
                },
                "source": {
                    "type": "string",
                    "description": "Search source (default 'auto')",
                    "default": "auto",
                },
            },
        },
    ),
    _tool_schema(
        name="web_open",
        description="Fetch and extract content from a web page",
        parameters={
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "mode": {
                    "type": "string",
                    "description": "Extraction mode ('auto', 'text', 'html')",
                    "default": "auto",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to extract (default 12000)",
                    "default": 12000,
                },
            },
        },
    ),
    _tool_schema(
        name="kiwix_search",
        description="Search offline content in Kiwix ZIM files",
        parameters={
            "type": "object",
            "required": ["query", "zim"],
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "zim": {
                    "type": "string",
                    "description": "Kiwix content id (usually the ZIM filename without .zim)",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of results (default 8)",
                    "default": 8,
                },
                "start": {
                    "type": "integer",
                    "description": "Start index for pagination (default 0)",
                    "default": 0,
                },
            },
        },
    ),
    _tool_schema(
        name="kiwix_open",
        description="Open and extract content from Kiwix ZIM files",
        parameters={
            "type": "object",
            "required": ["zim", "path"],
            "properties": {
                "zim": {
                    "type": "string",
                    "description": "Kiwix content id (usually the ZIM filename without .zim)",
                },
                "path": {"type": "string", "description": "Content path within ZIM"},
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to extract (default 12000)",
                    "default": 12000,
                },
            },
        },
    ),
    _tool_schema(
        name="kiwix_suggest",
        description="Get suggestions for content completion from Kiwix",
        parameters={
            "type": "object",
            "required": ["zim", "term"],
            "properties": {
                "zim": {
                    "type": "string",
                    "description": "Kiwix content id (usually the ZIM filename without .zim)",
                },
                "term": {"type": "string", "description": "Term to complete"},
                "count": {
                    "type": "integer",
                    "description": "Number of suggestions (default 8)",
                    "default": 8,
                },
            },
        },
    ),
    _tool_schema(
        name="kiwix_list_zims",
        description="List available ZIM files in Kiwix library",
        parameters={
            "type": "object",
            "properties": {
                "zim_dir": {
                    "type": "string",
                    "description": "ZIM directory path (default '~/zims')",
                    "default": "~/zims",
                },
            },
        },
    ),
]

__all__ = [
    "ToolError",
    "WebToolError",
    "KiwixToolError",
    "SearchResult",
    "TOOL_SPECS",
    "_tool_schema",
]
