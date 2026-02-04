"""Tools package for ollama-cli."""

from .registry import ToolRegistry, build_default_registry

__all__ = [
    "ToolRegistry",
    "build_default_registry",
]
