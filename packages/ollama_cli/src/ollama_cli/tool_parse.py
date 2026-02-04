"""Tool call parsing and execution utilities.

Internal module. Use `ollama_cli.loop` for the supported public API.
"""

import asyncio
import json
import re
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .tool_contract import ToolCall, ToolErrorCodes, ToolResult
from .tool_runtime import ToolRuntime

# Regex for extracting JSON from code blocks
_CODE_BLOCK = re.compile(r'```(?:json)?\s*(.*?)\s*```', re.DOTALL)


def coerce_tool_args(tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce and validate tool arguments to expected types.
    
    Args:
        tool_name: Name of the tool for error context
        tool_args: Raw arguments from the model
        
    Returns:
        Coerced arguments dictionary
        
    Raises:
        ValueError: If required arguments are missing or invalid
    """
    if not isinstance(tool_args, dict):
        raise ValueError(f"Tool {tool_name}: arguments must be a dictionary")
    
    # Basic validation - required args must be present and not None
    # Allow empty args for tools that don't require arguments
    return tool_args


def parse_fallback_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Parse tool calls from unstructured text using multiple strategies.
    
    This is a fallback parser that extracts tool calls when the model doesn't
    properly format them as JSON. It tries multiple extraction strategies.
    
    Args:
        text: Text potentially containing tool calls
        
    Returns:
        Tool call dictionary if found, None otherwise
    """
    # Strategy 1: Look for JSON in code blocks
    for match in _CODE_BLOCK.finditer(text):
        try:
            data = json.loads(match.group(1))
            if "function" in data and "name" in data.get("function", {}):
                return data
        except json.JSONDecodeError:
            continue
    
    # Strategy 2: Look for standalone JSON objects
    try:
        # Try parsing the entire text as JSON first
        data = json.loads(text.strip())
        if "function" in data and "name" in data.get("function", {}):
            return data
    except json.JSONDecodeError:
        pass
    
    # Strategy 3: Look for JSON-like patterns
    # Find things that look like {"function": {"name": "...", ...}}
    json_pattern = r'\{\s*"function"\s*:\s*\{[^}]*"name"\s*:\s*"[^"]+"'
    matches = re.finditer(json_pattern, text, re.DOTALL)
    
    for match in matches:
        try:
            # Try to extract a valid JSON object around this match
            start = match.start()
            # Find the closing brace for the function object
            brace_count = 0
            in_string = False
            escape_next = False
            pos = start
            
            while pos < len(text):
                char = text[pos]
                
                if escape_next:
                    escape_next = False
                    pos += 1
                    continue
                
                if char == '\\':
                    escape_next = True
                    pos += 1
                    continue
                    
                if char == '"' and not in_string:
                    in_string = True
                elif char == '"' and in_string:
                    in_string = False
                elif char == '{' and not in_string:
                    brace_count += 1
                elif char == '}' and not in_string:
                    brace_count -= 1
                    if brace_count == 0:
                        # Found complete JSON object
                        json_str = text[start:pos + 1]
                        try:
                            data = json.loads(json_str)
                            if "function" in data and "name" in data.get("function", {}):
                                return data
                        except json.JSONDecodeError:
                            pass
                        break
                pos += 1
        except Exception:
            continue
    
    return None








async def run_tool_calling_loop(
    tool_calls: List[Any],
    emit: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    tool_context: Optional[Dict[str, Any]] = None,
    runtime: Optional[ToolRuntime] = None,
) -> List[Dict[str, Any]]:
    """Run tool calling loop using the ToolRuntime system.

    Args:
        tool_calls: List of tool call dictionaries or ToolCall objects
        emit: Optional emit function for progress events
        tool_context: Optional context for tool execution
        runtime: Optional ToolRuntime instance

    Returns:
        List of tool result messages in chat API format
    """
    runtime = runtime or ToolRuntime()
    working: List[Dict[str, Any]] = []

    for raw_call in tool_calls:
        tool_call_id: str = str(uuid.uuid4())
        tool_name = "unknown"
        try:
            if isinstance(raw_call, ToolCall):
                tool_call = raw_call
            else:
                tool_call = ToolCall.from_ollama(raw_call)
            tool_call_id = tool_call.id
            tool_name = tool_call.name
        except Exception as e:
            error_msg = str(e) or "Invalid tool call"
            error_meta = {
                "tool": tool_name,
                "tool_call_id": tool_call_id,
                "code": ToolErrorCodes.INVALID_ARGS,
            }
            tool_result = ToolResult.failure(error_msg, meta=error_meta)
            if emit:
                await emit(
                    {
                        "type": "tool",
                        "event": "error",
                        "error": error_msg,
                        "tool_call_id": tool_call_id,
                        "code": ToolErrorCodes.INVALID_ARGS,
                    }
                )
            working.append(
                {
                    "role": "tool",
                    "content": tool_result.to_json(),
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                }
            )
            continue

        final_result: Optional[str] = None
        final_error: Optional[str] = None
        final_code: Optional[str] = None
        final_meta: Dict[str, Any] = {}

        async for event in runtime.call_async(
            tool_call.name,
            tool_call.arguments,
            tool_call_id=tool_call.id,
            tool_context=tool_context,
        ):
            if emit:
                await emit(event)
            if event.get("event") == "result" and event.get("ok"):
                final_result = event.get("result")
                final_meta = event.get("meta") or {}
            elif event.get("event") == "error":
                final_error = event.get("error")
                final_code = event.get("code")
                final_meta = event.get("meta") or {}

        final_meta.setdefault("tool", tool_call.name)
        final_meta.setdefault("tool_call_id", tool_call.id)
        if final_code:
            final_meta.setdefault("code", final_code)

        if final_result is not None:
            tool_result = ToolResult.success(final_result, meta=final_meta)
        else:
            if not final_code:
                final_meta.setdefault("code", ToolErrorCodes.NO_RESULT)
            tool_result = ToolResult.failure(final_error or "No result produced", meta=final_meta)

        working.append(
            {
                "role": "tool",
                "content": tool_result.to_json(),
                "tool_name": tool_call.name,
                "tool_call_id": tool_call.id,
            }
        )

    return working


def run_tool_calling_loop_sync(
    tool_calls: List[Any],
    emit: Optional[Callable[[Dict[str, Any]], Any]] = None,
    tool_context: Optional[Dict[str, Any]] = None,
    runtime: Optional[ToolRuntime] = None,
) -> List[Dict[str, Any]]:
    """Synchronous wrapper for run_tool_calling_loop."""
    try:
        # Check if we're already in an event loop
        loop = asyncio.get_running_loop()
        # If we're already in an event loop, we can't use run_until_complete
        # Run in a thread to avoid nested loop issues
        import concurrent.futures
        import threading
        
        result_container = []
        exception_container = []
        
        def run_in_thread():
            try:
                result = asyncio.run(run_tool_calling_loop(tool_calls, emit, tool_context, runtime))
                result_container.append(result)
            except Exception as e:
                exception_container.append(e)
        
        thread = threading.Thread(target=run_in_thread)
        thread.start()
        thread.join()
        
        if exception_container:
            raise exception_container[0]
        return result_container[0]
        
    except RuntimeError:
        # No running loop, use asyncio.run()
        return asyncio.run(run_tool_calling_loop(tool_calls, emit, tool_context, runtime))
