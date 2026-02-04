"""
Ollama CLI - Command-line interface for Ollama with tool capabilities.

A modular Python CLI application that provides command-line access to Ollama API
with additional tool capabilities including web search via SearxNG and offline
content access via Kiwix.
"""

__version__ = "1.0.0"
__author__ = "Ollama CLI Contributors"


def __getattr__(name: str):
    # Lazy exports to avoid importing CLI modules at package import time.
    if name == "main":
        from .cli import main as _main
        return _main
    if name == "OllamaClient":
        from .client import OllamaClient as _OllamaClient
        return _OllamaClient
    if name == "ToolRegistry":
        from .tools import ToolRegistry as _ToolRegistry
        return _ToolRegistry
    if name == "ToolRuntime":
        from .runtime import ToolRuntime as _ToolRuntime
        return _ToolRuntime
    if name == "run_tool_calling_loop":
        from .loop import run_tool_calling_loop as _run_tool_calling_loop
        return _run_tool_calling_loop
    if name == "run_tool_calling_loop_sync":
        from .loop import run_tool_calling_loop_sync as _run_tool_calling_loop_sync
        return _run_tool_calling_loop_sync
    raise AttributeError(name)


__all__ = [
    "main",
    "OllamaClient",
    "ToolRegistry",
    "ToolRuntime",
    "run_tool_calling_loop",
    "run_tool_calling_loop_sync",
]
