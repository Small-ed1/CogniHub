"""Tool call and result contracts with stable serialization."""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class ToolErrorCodes:
    """Stable error codes for tool execution."""

    NOT_FOUND = "not_found"
    INVALID_ARGS = "invalid_args"
    TIMEOUT = "timeout"
    EXCEPTION = "exception"
    OUTPUT_TOO_LARGE = "output_too_large"
    NO_RESULT = "no_result"
    DEPENDENCY_MISSING = "dependency_missing"
    ACCESS_DENIED = "access_denied"


@dataclass(frozen=True)
class ToolCall:
    """Canonical tool call shape."""

    id: str
    name: str
    arguments: Dict[str, Any]

    @classmethod
    def from_ollama(cls, tool_call: Dict[str, Any]) -> "ToolCall":
        """Create ToolCall from an Ollama tool call dict."""
        if not isinstance(tool_call, dict):
            raise ValueError("Tool call must be a dictionary")

        function = tool_call.get("function") or {}
        if not isinstance(function, dict):
            raise ValueError("Tool call function must be a dictionary")

        name = function.get("name")
        if not name:
            raise ValueError("Tool call missing function name")

        arguments = function.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("Tool call arguments must be a dictionary")

        call_id = tool_call.get("id") or str(uuid.uuid4())
        return cls(id=str(call_id), name=str(name), arguments=arguments)


@dataclass(frozen=True)
class ToolResult:
    """Canonical tool result shape."""

    ok: bool
    content: Optional[str] = None
    error: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a stable dictionary shape."""
        return {
            "ok": self.ok,
            "content": self.content,
            "error": self.error,
            "meta": dict(self.meta) if self.meta is not None else {},
        }

    def to_json(self) -> str:
        """Serialize to a stable JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def success(cls, content: str, meta: Optional[Dict[str, Any]] = None) -> "ToolResult":
        """Build a successful result."""
        return cls(ok=True, content=content, error=None, meta=meta or {})

    @classmethod
    def failure(
        cls,
        error: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "ToolResult":
        """Build a failed result."""
        return cls(ok=False, content=None, error=error, meta=meta or {})


__all__ = ["ToolCall", "ToolErrorCodes", "ToolResult"]
