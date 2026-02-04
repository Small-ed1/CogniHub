"""Core models for tool system with streaming support.

This module defines the standardized data structures for tool execution
with streaming capabilities and unified error handling.
"""

from pydantic import BaseModel, Field
from typing import Any, Optional, Literal, Dict


class ToolProgress(BaseModel):
    """Progress update from tool execution."""
    type: Literal["progress"] = "progress"
    step: str
    current: int
    total: int
    message: Optional[str] = None


class ToolResult(BaseModel):
    """Unified result envelope for all tool executions."""
    ok: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    code: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)
    tool: Optional[str] = None  # Mutable for audit trail