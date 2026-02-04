"""Tool execution exceptions.

This module provides typed exceptions for tool execution
with proper error codes instead of string matching.
"""

from typing import Optional, Any, Dict


class ToolError(Exception):
    """Base exception for tool execution with error codes."""
    
    def __init__(self, message: str, code: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class InvalidToolArgsError(ToolError):
    """Invalid tool arguments."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "invalid_args", details)


class ToolNotFoundError(ToolError):
    """Tool not found."""
    def __init__(self, message: str, tool_name: str):
        super().__init__(message, "not_found", {"tool_name": tool_name})


class ToolTimeoutError(ToolError):
    """Tool execution timeout."""
    def __init__(self, message: str, timeout_s: float):
        super().__init__(message, "timeout", {"timeout_s": timeout_s})


class ToolOutputTooLargeError(ToolError):
    """Tool output exceeds size limits."""
    def __init__(self, message: str, size_bytes: int, limit_bytes: int):
        super().__init__(message, "output_too_large", {
            "size_bytes": size_bytes,
            "limit_bytes": limit_bytes
        })


class ToolMaxChunksExceededError(ToolError):
    """Tool exceeded maximum chunk limit."""
    def __init__(self, message: str, chunks: int, limit: int):
        super().__init__(message, "max_chunks_exceeded", {
            "chunks": chunks,
            "limit": limit
        })


class ToolNoResultError(ToolError):
    """Streaming tool did not produce final result."""
    def __init__(self, message: str):
        super().__init__(message, "no_result")