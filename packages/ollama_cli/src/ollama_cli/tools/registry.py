"""Tool registry with explicit, instance-based configuration."""

import copy
from typing import Any, Callable, Dict, List, Optional

from ..config import ToolConfig
from ..errors import ToolArgumentError
from .core import TOOL_SPECS
from .kiwix_tools import KiwixTools, tool_kiwix_list_zims, tool_kiwix_open, tool_kiwix_search, tool_kiwix_suggest
from .system_tools import tool_get_time, tool_read_file
from .web_tools import WebTools, tool_web_open, tool_web_search

ToolFunc = Callable[..., Any]


class ToolRegistry:
    """Registry for tool specifications and callable implementations."""

    def __init__(self) -> None:
        self._specs: Dict[str, Dict[str, Any]] = {}
        self._funcs: Dict[str, ToolFunc] = {}

    def register(self, name: str, spec: Dict[str, Any], func: ToolFunc) -> None:
        """Register a tool with its spec and function."""
        if not name:
            raise ToolArgumentError("Tool name is required")
        self._specs[name] = spec
        self._funcs[name] = func

    def register_spec(self, spec: Dict[str, Any], func: ToolFunc) -> None:
        """Register a tool using a standard spec dict."""
        function = spec.get("function") or {}
        name = function.get("name")
        if not name:
            raise ToolArgumentError("Tool spec missing function name")
        self.register(name, spec, func)

    def has_tool(self, name: str) -> bool:
        """Return True if a tool is registered."""
        return name in self._funcs

    def get_function(self, name: str) -> ToolFunc:
        """Get a tool function by name."""
        return self._funcs[name]

    def get_spec(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a tool spec by name if registered."""
        return self._specs.get(name)

    def list_specs(self) -> List[Dict[str, Any]]:
        """Return all tool specs in registration order."""
        return list(self._specs.values())

    def select_specs(self, names: List[str]) -> List[Dict[str, Any]]:
        """Return tool specs for the requested names, skipping unknowns."""
        selected: List[Dict[str, Any]] = []
        for name in names:
            spec = self._specs.get(name)
            if spec:
                selected.append(spec)
        return selected

    def tool_names(self) -> List[str]:
        """Return registered tool names."""
        return list(self._funcs.keys())


def _configured_tool_specs(tool_config: ToolConfig) -> List[Dict[str, Any]]:
    """Return tool specs with defaults adjusted from configuration."""
    specs = copy.deepcopy(TOOL_SPECS)
    specs_map = {spec["function"]["name"]: spec for spec in specs}

    if "web_search" in specs_map:
        props = specs_map["web_search"]["function"]["parameters"]["properties"]
        props["count"]["default"] = tool_config.web_search_count
    if "web_open" in specs_map:
        props = specs_map["web_open"]["function"]["parameters"]["properties"]
        props["max_chars"]["default"] = tool_config.web_max_chars
    if "kiwix_search" in specs_map:
        props = specs_map["kiwix_search"]["function"]["parameters"]["properties"]
        props["count"]["default"] = tool_config.kiwix_search_count
    if "kiwix_open" in specs_map:
        props = specs_map["kiwix_open"]["function"]["parameters"]["properties"]
        props["max_chars"]["default"] = tool_config.kiwix_max_chars
    if "kiwix_list_zims" in specs_map:
        props = specs_map["kiwix_list_zims"]["function"]["parameters"]["properties"]
        props["zim_dir"]["default"] = tool_config.kiwix_zim_dir

    return specs


def build_default_registry(tool_config: Optional[ToolConfig] = None) -> ToolRegistry:
    """Build a registry with the standard tool set."""
    config = tool_config or ToolConfig()
    registry = ToolRegistry()
    specs = _configured_tool_specs(config)
    specs_map = {spec["function"]["name"]: spec for spec in specs}

    registry.register("get_time", specs_map["get_time"], tool_get_time)
    registry.register("read_file", specs_map["read_file"], tool_read_file)

    web_tools = WebTools(
        searxng_url=config.searxng_url,
        timeout=config.timeout_s,
        cache_minutes=config.cache_minutes,
    )

    def web_search(
        query: str,
        count: int = config.web_search_count,
        recency_days: int = 365,
        source: str = "auto",
    ) -> str:
        return tool_web_search(web_tools, query, count, recency_days, source)

    def web_open(
        url: str,
        mode: str = "auto",
        max_chars: int = config.web_max_chars,
    ) -> str:
        return tool_web_open(web_tools, url, mode, max_chars)

    registry.register("web_search", specs_map["web_search"], web_search)
    registry.register("web_open", specs_map["web_open"], web_open)

    kiwix_tools = KiwixTools(
        kiwix_url=config.kiwix_url,
        timeout=config.timeout_s,
        cache_minutes=config.cache_minutes,
    )

    def kiwix_search(
        query: str,
        zim: str,
        count: int = config.kiwix_search_count,
        start: int = 0,
    ) -> str:
        return tool_kiwix_search(kiwix_tools, query, zim, count, start)

    def kiwix_open(
        zim: str,
        path: str,
        max_chars: int = config.kiwix_max_chars,
    ) -> str:
        return tool_kiwix_open(kiwix_tools, zim, path, max_chars)

    def kiwix_suggest(zim: str, term: str, count: int = 8) -> str:
        return tool_kiwix_suggest(kiwix_tools, zim, term, count)

    def kiwix_list_zims(zim_dir: str = config.kiwix_zim_dir) -> str:
        return tool_kiwix_list_zims(kiwix_tools, zim_dir)

    registry.register("kiwix_search", specs_map["kiwix_search"], kiwix_search)
    registry.register("kiwix_open", specs_map["kiwix_open"], kiwix_open)
    registry.register("kiwix_suggest", specs_map["kiwix_suggest"], kiwix_suggest)
    registry.register("kiwix_list_zims", specs_map["kiwix_list_zims"], kiwix_list_zims)

    return registry


__all__ = ["ToolRegistry", "build_default_registry"]
