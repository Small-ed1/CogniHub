"""Custom exception hierarchy for ollama-cli."""

from typing import Any, Dict, Optional

from .tool_contract import ToolErrorCodes


class OllamaCLIError(RuntimeError):
    """Base error for ollama-cli."""


class OllamaAPIError(OllamaCLIError):
    """Raised when Ollama API requests fail."""


class OllamaNetworkError(OllamaAPIError):
    """Raised for network-related Ollama API failures."""


class OllamaTimeoutError(OllamaAPIError):
    """Raised when an Ollama API request times out."""


class ToolError(OllamaCLIError):
    """Base exception for tool-related errors."""

    def __init__(
        self,
        message: str,
        code: str = ToolErrorCodes.EXCEPTION,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.meta = meta or {}


class ToolNotFoundError(ToolError):
    """Raised when a tool is not registered."""

    def __init__(self, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, code=ToolErrorCodes.NOT_FOUND, meta=meta)


class ToolArgumentError(ToolError):
    """Raised when tool arguments are invalid."""

    def __init__(self, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, code=ToolErrorCodes.INVALID_ARGS, meta=meta)


class ToolTimeoutError(ToolError):
    """Raised when a tool operation times out."""

    def __init__(self, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, code=ToolErrorCodes.TIMEOUT, meta=meta)


class ToolOutputTooLargeError(ToolError):
    """Raised when a tool output exceeds limits."""

    def __init__(self, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, code=ToolErrorCodes.OUTPUT_TOO_LARGE, meta=meta)


class ToolAccessError(ToolError):
    """Raised when a tool access is denied."""

    def __init__(self, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, code=ToolErrorCodes.ACCESS_DENIED, meta=meta)


class ToolDependencyError(ToolError):
    """Raised when a required optional dependency is missing."""

    def __init__(self, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, code=ToolErrorCodes.DEPENDENCY_MISSING, meta=meta)


class ToolExecutionError(ToolError):
    """Raised for unexpected tool execution failures."""

    def __init__(self, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, code=ToolErrorCodes.EXCEPTION, meta=meta)


class WebToolError(ToolExecutionError):
    """Exception raised when web-based tools fail."""


class KiwixToolError(ToolExecutionError):
    """Exception raised when Kiwix-based tools fail."""


__all__ = [
    "OllamaCLIError",
    "OllamaAPIError",
    "OllamaNetworkError",
    "OllamaTimeoutError",
    "ToolError",
    "ToolNotFoundError",
    "ToolArgumentError",
    "ToolTimeoutError",
    "ToolOutputTooLargeError",
    "ToolAccessError",
    "ToolDependencyError",
    "ToolExecutionError",
    "WebToolError",
    "KiwixToolError",
]
