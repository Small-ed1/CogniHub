"""Advanced tool runtime system with safety limits and progress tracking.

Internal module. Use `ollama_cli.runtime` for the supported public API.
"""

import asyncio
import inspect
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict, Optional

from .config import RuntimeConfig
from .errors import ToolError
from .tool_contract import ToolErrorCodes, ToolResult
from .tools.registry import ToolRegistry, build_default_registry

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class ToolRuntime:
    """Tool runtime with safety limits and progress support."""

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        runtime_config: Optional[RuntimeConfig] = None,
        timeout_s: Optional[float] = None,
        max_chunks: Optional[int] = None,
        max_result_bytes: Optional[int] = None,
    ) -> None:
        """Initialize the tool runtime with safety limits.

        Args:
            registry: ToolRegistry instance (defaults to built-in registry)
            runtime_config: RuntimeConfig for timeout and size limits
            timeout_s: Override timeout seconds
            max_chunks: Override max progress chunks
            max_result_bytes: Override max result size in bytes
        """
        config = runtime_config or RuntimeConfig()
        self.timeout_s = timeout_s if timeout_s is not None else config.timeout_s
        self.max_chunks = max_chunks if max_chunks is not None else config.max_chunks
        self.max_result_bytes = (
            max_result_bytes if max_result_bytes is not None else config.max_result_bytes
        )
        self._registry = registry or build_default_registry()

    async def call_async(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        tool_context: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute a tool call with safety limits and progress reporting."""
        start_time = time.time()
        if tool_call_id is None:
            tool_call_id = str(uuid.uuid4())

        if not self._registry.has_tool(tool_name):
            duration_ms = (time.time() - start_time) * 1000
            logger.warning("Tool not found: %s (duration: %.1fms)", tool_name, duration_ms)
            yield {
                "type": "tool",
                "event": "error",
                "tool": tool_name,
                "tool_call_id": tool_call_id,
                "error": f"Unknown tool: {tool_name}",
                "ok": False,
                "code": ToolErrorCodes.NOT_FOUND,
                "duration_ms": duration_ms,
            }
            return

        yield {
            "type": "tool",
            "event": "start",
            "tool": tool_name,
            "tool_call_id": tool_call_id,
        }

        func = self._registry.get_function(tool_name)
        call_args = tool_args
        if tool_context and hasattr(func, "__code__"):
            sig = inspect.signature(func)
            if "tool_context" in sig.parameters:
                call_args = dict(tool_args)
                call_args["tool_context"] = tool_context
            elif "file_security" in sig.parameters:
                call_args = dict(tool_args)
                call_args["file_security"] = tool_context

        final_result = None
        final_error = None
        final_code = None
        final_meta: Dict[str, Any] = {}

        try:
            if inspect.iscoroutinefunction(func):
                result = await asyncio.wait_for(func(**call_args), timeout=self.timeout_s)
            else:
                loop = asyncio.get_running_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: func(**call_args)),
                    timeout=self.timeout_s,
                )

            if not isinstance(result, str):
                result = json.dumps(result, indent=2, ensure_ascii=False)

            result_size = len(result.encode("utf-8"))
            if result_size > self.max_result_bytes:
                final_error = f"Result too large: {result_size} bytes"
                final_code = ToolErrorCodes.OUTPUT_TOO_LARGE
            else:
                final_result = result
                final_meta["result_bytes"] = result_size

        except asyncio.TimeoutError:
            final_error = f"Tool execution timed out after {self.timeout_s}s"
            final_code = ToolErrorCodes.TIMEOUT
        except ToolError as e:
            final_error = str(e)
            final_code = e.code
            final_meta.update(e.meta)
        except Exception as e:
            final_error = str(e)
            final_code = ToolErrorCodes.EXCEPTION

        duration_ms = (time.time() - start_time) * 1000
        final_meta.update({
            "tool": tool_name,
            "tool_call_id": tool_call_id,
            "duration_ms": duration_ms,
        })

        if final_result is not None:
            logger.info(
                "Tool success: %s (%d bytes, duration: %.1fms)",
                tool_name,
                final_meta.get("result_bytes", 0),
                duration_ms,
            )
            yield {
                "type": "tool",
                "event": "result",
                "tool": tool_name,
                "tool_call_id": tool_call_id,
                "result": final_result,
                "ok": True,
                "duration_ms": duration_ms,
                "result_bytes": final_meta.get("result_bytes"),
                "meta": final_meta,
            }
        else:
            if final_code:
                final_meta["code"] = final_code
            logger.warning(
                "Tool error: %s code=%s (duration: %.1fms)",
                tool_name,
                final_code,
                duration_ms,
            )
            yield {
                "type": "tool",
                "event": "error",
                "tool": tool_name,
                "tool_call_id": tool_call_id,
                "error": final_error,
                "ok": False,
                "code": final_code,
                "duration_ms": duration_ms,
                "meta": final_meta,
            }

    def call_sync(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        """Synchronous version of call_async for backward compatibility."""
        start_time = time.time()

        if not self._registry.has_tool(tool_name):
            duration_ms = (time.time() - start_time) * 1000
            return ToolResult.failure(
                f"Unknown tool: {tool_name}",
                meta={
                    "tool": tool_name,
                    "code": ToolErrorCodes.NOT_FOUND,
                    "duration_ms": duration_ms,
                },
            )

        func = self._registry.get_function(tool_name)
        call_args = tool_args
        if tool_context and hasattr(func, "__code__"):
            sig = inspect.signature(func)
            if "tool_context" in sig.parameters:
                call_args = dict(tool_args)
                call_args["tool_context"] = tool_context
            elif "file_security" in sig.parameters:
                call_args = dict(tool_args)
                call_args["file_security"] = tool_context

        try:
            result = func(**call_args)
            if not isinstance(result, str):
                result = json.dumps(result, indent=2, ensure_ascii=False)
            result_size = len(result.encode("utf-8"))
            if result_size > self.max_result_bytes:
                duration_ms = (time.time() - start_time) * 1000
                return ToolResult.failure(
                    f"Result too large: {result_size} bytes",
                    meta={
                        "tool": tool_name,
                        "code": ToolErrorCodes.OUTPUT_TOO_LARGE,
                        "duration_ms": duration_ms,
                    },
                )
            duration_ms = (time.time() - start_time) * 1000
            return ToolResult.success(
                result,
                meta={
                    "tool": tool_name,
                    "duration_ms": duration_ms,
                    "result_bytes": result_size,
                },
            )
        except ToolError as e:
            duration_ms = (time.time() - start_time) * 1000
            meta = {"tool": tool_name, "code": e.code, "duration_ms": duration_ms}
            meta.update(e.meta)
            return ToolResult.failure(str(e), meta=meta)
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return ToolResult.failure(
                str(e),
                meta={
                    "tool": tool_name,
                    "code": ToolErrorCodes.EXCEPTION,
                    "duration_ms": duration_ms,
                },
            )
