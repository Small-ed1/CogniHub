"""Configuration models and environment loading helpers."""

import os
from dataclasses import dataclass, field
from typing import Optional


DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_SEARXNG_URL = "http://localhost:8080/search"
DEFAULT_KIWIX_URL = "http://127.0.0.1:8081"
DEFAULT_KIWIX_ZIM_DIR = "~/zims"
DEFAULT_TIMEOUT = 60
DEFAULT_CACHE_MINUTES = 30
DEFAULT_WEB_SEARCH_COUNT = 8
DEFAULT_WEB_MAX_CHARS = 12000
DEFAULT_KIWIX_SEARCH_COUNT = 8
DEFAULT_KIWIX_MAX_CHARS = 12000
DEFAULT_CONFIG_FILE = "~/.ollama_cli_config.json"


@dataclass(frozen=True)
class ClientConfig:
    """Configuration for Ollama API client."""

    base_url: str = DEFAULT_BASE_URL
    api_key: Optional[str] = None
    timeout_s: int = DEFAULT_TIMEOUT


@dataclass(frozen=True)
class ToolConfig:
    """Configuration for tool implementations."""

    searxng_url: str = DEFAULT_SEARXNG_URL
    kiwix_url: str = DEFAULT_KIWIX_URL
    kiwix_zim_dir: str = DEFAULT_KIWIX_ZIM_DIR
    timeout_s: int = DEFAULT_TIMEOUT
    cache_minutes: int = DEFAULT_CACHE_MINUTES
    web_search_count: int = DEFAULT_WEB_SEARCH_COUNT
    web_max_chars: int = DEFAULT_WEB_MAX_CHARS
    kiwix_search_count: int = DEFAULT_KIWIX_SEARCH_COUNT
    kiwix_max_chars: int = DEFAULT_KIWIX_MAX_CHARS


@dataclass(frozen=True)
class RuntimeConfig:
    """Configuration for tool runtime limits."""

    timeout_s: float = 60.0
    max_chunks: int = 1000
    max_result_bytes: int = 100_000


@dataclass(frozen=True)
class AppConfig:
    """Aggregated configuration for CLI and integrations."""

    client: ClientConfig = field(default_factory=ClientConfig)
    tools: ToolConfig = field(default_factory=ToolConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)


def _env_int(name: str, default: int) -> int:
    """Safely get integer from environment variable."""
    env_val = os.getenv(name)
    if env_val is None:
        return default
    try:
        return int(env_val)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    """Safely get float from environment variable."""
    env_val = os.getenv(name)
    if env_val is None:
        return default
    try:
        return float(env_val)
    except ValueError:
        return default


def _normalize_api_key(api_key: Optional[str]) -> Optional[str]:
    if not api_key:
        return None
    api_key = api_key.strip()
    return api_key or None


def resolve_config_file(path: str = DEFAULT_CONFIG_FILE) -> str:
    """Expand and normalize the config file path."""
    return os.path.expanduser(path)


def _expand_path(path: str) -> str:
    return os.path.expanduser(path)


def load_config_from_env() -> AppConfig:
    """Load configuration from environment variables."""
    base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_BASE_URL)
    api_key = _normalize_api_key(os.getenv("OLLAMA_API_KEY"))
    timeout_s = _env_int("OLLAMA_TIMEOUT", DEFAULT_TIMEOUT)

    searxng_url = os.getenv("SEARXNG_URL", DEFAULT_SEARXNG_URL)
    kiwix_url = os.getenv("KIWIX_URL", DEFAULT_KIWIX_URL)
    kiwix_zim_dir = _expand_path(os.getenv("KIWIX_ZIM_DIR", DEFAULT_KIWIX_ZIM_DIR))
    cache_minutes = _env_int("OLLAMA_CACHE_MINUTES", DEFAULT_CACHE_MINUTES)

    web_search_count = _env_int("OLLAMA_WEB_SEARCH_COUNT", DEFAULT_WEB_SEARCH_COUNT)
    web_max_chars = _env_int("OLLAMA_WEB_MAX_CHARS", DEFAULT_WEB_MAX_CHARS)
    kiwix_search_count = _env_int("OLLAMA_KIWIX_SEARCH_COUNT", DEFAULT_KIWIX_SEARCH_COUNT)
    kiwix_max_chars = _env_int("OLLAMA_KIWIX_MAX_CHARS", DEFAULT_KIWIX_MAX_CHARS)

    runtime_timeout_s = _env_float("TOOL_TIMEOUT_S", 60.0)
    runtime_max_chunks = _env_int("TOOL_MAX_CHUNKS", 1000)
    runtime_max_result_bytes = _env_int("TOOL_MAX_RESULT_BYTES", 100000)

    return AppConfig(
        client=ClientConfig(base_url=base_url, api_key=api_key, timeout_s=timeout_s),
        tools=ToolConfig(
            searxng_url=searxng_url,
            kiwix_url=kiwix_url,
            kiwix_zim_dir=kiwix_zim_dir,
            timeout_s=timeout_s,
            cache_minutes=cache_minutes,
            web_search_count=web_search_count,
            web_max_chars=web_max_chars,
            kiwix_search_count=kiwix_search_count,
            kiwix_max_chars=kiwix_max_chars,
        ),
        runtime=RuntimeConfig(
            timeout_s=runtime_timeout_s,
            max_chunks=runtime_max_chunks,
            max_result_bytes=runtime_max_result_bytes,
        ),
    )
