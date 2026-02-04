"""Adapter helpers for external integrations."""

from .cognihub import from_ollama_tool_calls, to_tool_specs

__all__ = ["from_ollama_tool_calls", "to_tool_specs"]
