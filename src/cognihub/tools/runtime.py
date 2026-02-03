"""Tool registry with streaming runtime support.

This module provides the core tool execution engine that supports
sync, async, sync generator, and async generator handlers
with unified result streaming and safety constraints.
"""

import asyncio
import inspect
import os
import sys
import time
from typing import AsyncGenerator, Any, Dict, Optional

from .models import ToolResult, ToolProgress


class ToolSpec:
    """Specification for a tool in the registry."""
    
    def __init__(
        self,
        name: str,
        description: str,
        args_schema,
        handler,
    ):
        self.name = name
        self.description = description
        self.args_schema = args_schema
        self.handler = handler


class ToolRegistry:
    """Registry for tool specifications with async execution support."""
    
    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}
    
    def register(self, tool: ToolSpec) -> None:
        """Register a tool in the registry."""
        self._tools[tool.name] = tool
    
    def get(self, name: str) -> Optional[ToolSpec]:
        """Get a tool specification by name."""
        return self._tools.get(name)
    
    def list_tools(self) -> Dict[str, ToolSpec]:
        """Get all registered tools."""
        return dict(self._tools)
    
    def schema_for_prompt(self) -> list[dict]:
        """Export tool schemas for LLM prompts."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.args_schema.model_json_schema()
            }
            for t in self._tools.values()
        ]


class ToolRuntime:
    """Streaming tool execution runtime with safety constraints."""
    
    def __init__(
        self, 
        registry: ToolRegistry,
        *,
        timeout_s: Optional[float] = None,
        max_chunks: Optional[int] = None,
        max_result_bytes: Optional[int] = None,
    ):
        self.registry = registry
        # Safety limits
        self.timeout_s = timeout_s or float(os.getenv("TOOL_TIMEOUT_S", "12.0"))
        self.max_chunks = max_chunks or int(os.getenv("TOOL_MAX_CHUNKS", "100"))
        self.max_result_bytes = max_result_bytes or int(os.getenv("TOOL_MAX_RESULT_BYTES", str(4 * 1024 * 1024)))  # 4MB
    
    async def _execute_tool_safely(self, tool, validated, name):
        """Execute tool with all the type-specific logic."""
        out = tool.handler(validated)
        
        # Handle awaitable results
        if inspect.isawaitable(out):
            out = await out
        
        return out
    
    async def call_async(self, name: str, args: dict) -> AsyncGenerator[ToolResult, None]:
        """Execute a tool and stream results with safety constraints."""
        start_time = time.time()
        chunk_count = 0
        
        tool = self.registry.get(name)
        if not tool:
            yield ToolResult(
                ok=False, 
                error=f"Unknown tool: {name}", 
                code="not_found", 
                tool=name
            )
            return

        try:
            validated = tool.args_schema.model_validate(args)
        except Exception as e:
            yield ToolResult(
                ok=False,
                error=str(e),
                code="invalid_args",
                meta={"type": type(e).__name__},
                tool=name,
            )
            return

        def _check_result_size(result: Any) -> bool:
            """Check if result exceeds size limit."""
            if result is None:
                return True
            try:
                size = len(str(result).encode('utf-8'))
                return size <= self.max_result_bytes
            except Exception:
                return True  # If we can't measure, allow it
        
        try:
            # Execute tool with timeout protection
            out = await asyncio.wait_for(
                self._execute_tool_safely(tool, validated, name),
                timeout=self.timeout_s
            )

            # Handle async generator with proper timeout
            if inspect.isasyncgen(out):
                final_result = None
                try:
                    async with asyncio.timeout(self.timeout_s):
                        async for chunk in out:
                            chunk_count += 1
                            if chunk_count > self.max_chunks:
                                yield ToolResult(
                                    ok=False,
                                    error=f"Tool exceeded maximum chunks limit: {self.max_chunks}",
                                    code="max_chunks_exceeded",
                                    tool=name,
                                )
                                return
                            
                            if isinstance(chunk, ToolResult):
                                # Ensure tool name is set
                                if chunk.tool is None:
                                    chunk = chunk.model_copy(update={"tool": name})
                                
                                # Check final result size
                                if chunk.ok and chunk.result is not None and not isinstance(chunk.result, ToolProgress):
                                    if not _check_result_size(chunk.result):
                                        yield ToolResult(
                                            ok=False,
                                            error="Tool result exceeds maximum size limit",
                                            code="output_too_large",
                                            tool=name,
                                        )
                                        return
                                    final_result = chunk.result
                                
                                yield chunk
                            else:
                                # Raw streaming chunk
                                if not _check_result_size(chunk):
                                    yield ToolResult(
                                        ok=False,
                                        error="Tool result exceeds maximum size limit",
                                        code="output_too_large",
                                        tool=name,
                                    )
                                    return
                                yield ToolResult(ok=True, result=chunk, tool=name)
                
                except asyncio.TimeoutError:
                    yield ToolResult(
                        ok=False,
                        error=f"Tool execution exceeded {self.timeout_s}s timeout",
                        code="timeout",
                        tool=name,
                    )
                    return
                
                # Ensure streaming tools produce final result
                if final_result is None:
                    yield ToolResult(
                        ok=False,
                        error="Streaming tool did not produce a final result",
                        code="no_result",
                        tool=name,
                    )
                return

            # Handle sync generator (strict detection)
            if inspect.isgenerator(out):
                final_result = None
                for chunk in out:
                    chunk_count += 1
                    if chunk_count > self.max_chunks:
                        yield ToolResult(
                            ok=False,
                            error=f"Tool exceeded maximum chunks limit: {self.max_chunks}",
                            code="max_chunks_exceeded",
                            tool=name,
                        )
                        return
                    
                    if isinstance(chunk, ToolResult):
                        if chunk.tool is None:
                            chunk = chunk.model_copy(update={"tool": name})
                        
                        # Check final result size
                        if chunk.ok and chunk.result is not None and not isinstance(chunk.result, ToolProgress):
                            if not _check_result_size(chunk.result):
                                yield ToolResult(
                                    ok=False,
                                    error="Tool result exceeds maximum size limit",
                                    code="output_too_large",
                                    tool=name,
                                )
                                return
                            final_result = chunk.result
                        
                        yield chunk
                    else:
                        # Check raw chunk size
                        if not _check_result_size(chunk):
                            yield ToolResult(
                                ok=False,
                                error="Tool result exceeds maximum size limit",
                                code="output_too_large",
                                tool=name,
                            )
                            return
                        
                        yield ToolResult(ok=True, result=chunk, tool=name)
                
                # Ensure we have a final result for streaming tools
                if final_result is None:
                    yield ToolResult(
                        ok=False,
                        error="Streaming tool did not produce a final result",
                        code="no_result",
                        tool=name,
                    )
                return

            # Handle direct result
            if not _check_result_size(out):
                yield ToolResult(
                    ok=False,
                    error="Tool result exceeds maximum size limit",
                    code="output_too_large", 
                    tool=name,
                )
                return
            
            yield ToolResult(ok=True, result=out, tool=name)

        except asyncio.TimeoutError as e:
            yield ToolResult(
                ok=False,
                error=str(e),
                code="timeout",
                meta={"timeout_s": self.timeout_s},
                tool=name,
            )
        except Exception as e:
            yield ToolResult(
                ok=False,
                error=str(e),
                code="exception",
                meta={"type": type(e).__name__},
                tool=name,
            )