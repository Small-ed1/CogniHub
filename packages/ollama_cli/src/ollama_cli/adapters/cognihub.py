"""CogniHub adapter helpers."""

from typing import Any, Dict, List

from ..tool_contract import ToolCall
from ..tools.registry import ToolRegistry


def to_tool_specs(registry: ToolRegistry) -> List[Dict[str, Any]]:
    """Convert a ToolRegistry into a list of tool spec dicts."""
    return registry.list_specs()


def from_ollama_tool_calls(resp: Dict[str, Any]) -> List[ToolCall]:
    """Extract ToolCall objects from an Ollama response dict."""
    if not isinstance(resp, dict):
        return []
    message = resp.get("message") or {}
    tool_calls = message.get("tool_calls") or resp.get("tool_calls") or []
    calls: List[ToolCall] = []
    for tool_call in tool_calls:
        try:
            calls.append(ToolCall.from_ollama(tool_call))
        except Exception:
            continue
    return calls
