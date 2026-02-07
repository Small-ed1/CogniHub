from __future__ import annotations
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


class ConfigError(RuntimeError):
    pass


def _default_config_dir() -> Path:
    # Windows: prefer %APPDATA%\contextharbor; fallback to ~/.config/contextharbor
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "contextharbor"
    return Path.home() / ".config" / "contextharbor"


def get_config_dir() -> Path:
    raw = (os.getenv("CONTEXTHARBOR_CONFIG_DIR") or "").strip()
    if raw:
        return Path(os.path.expanduser(raw))
    return _default_config_dir()


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib  # py3.11+
    except Exception as exc:  # pragma: no cover
        raise ConfigError(f"TOML support unavailable: {exc}")

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(
            f"Missing config file: {path}. Run `contextharbor run` to generate defaults."
        )
    except Exception as exc:
        raise ConfigError(f"Failed to parse TOML: {path}: {exc}")

    return data if isinstance(data, dict) else {}


def ensure_default_config_files(config_dir: Path) -> list[Path]:
    """Create default core/tools/search TOML files if missing.

    Returns list of created paths.
    """

    config_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    core_path = config_dir / "core.toml"
    tools_path = config_dir / "tools.toml"
    search_path = config_dir / "search.toml"

    if not core_path.exists():
        core_path.write_text(
            """# ContextHarbor core configuration (v1.0)\n\n[core]\nhost = \"0.0.0.0\"\nport = 8000\nreload = false\n\n[models]\nollama_url = \"http://127.0.0.1:11434\"\n# Use the exact tag name shown by `ollama list` (often ends with :latest).\nchat_model = \"llama3.1:latest\"\nembed_model = \"nomic-embed-text:latest\"\n\n[sources]\n# Optional: offline sources + local libraries\n# Leave kiwix_url blank to disable kiwix tools\nkiwix_url = \"\"\nkiwix_zim_dir = \"~/zims\"\nebooks_dir = \"~/Ebooks\"\n\n[paths]\n# data_dir controls where ContextHarbor stores its sqlite DBs\ndata_dir = \"~/.contextharbor/data\"\n\n[limits]\nmax_upload_bytes = 10485760\nmax_research_rounds = 6\nmax_pages_per_round = 12\nmax_web_queries = 6\nmax_doc_queries = 6\nmax_json_parse_size = 100000\n\n""",
            encoding="utf-8",
        )
        created.append(core_path)

    if not tools_path.exists():
        tools_path.write_text(
            """# ContextHarbor tool configuration (v1.0)\n\n[tools]\n# Enable/disable tools by name\nenabled = [\"web_search\", \"doc_search\", \"local_file_read\"]\n# Optional: additional python modules that register tools\nplugin_modules = []\n# Example plugin:\n# plugin_modules = [\"contextharbor_example_plugin\"]\n\n[tools.local_file_read]\n# Allowed roots for local_file_read (expanduser supported)\nroots = [\"~\"]\nmax_bytes = 200000\n\n[tools.shell_exec]\n# When enabling, also add \"shell_exec\" to tools.enabled.\nenabled = false\n# When enabled, shell_exec requires an explicit confirmation token\nrequires_confirmation = true\n# Allowed commands (first argv element)\nallow = [\"git\", \"python\", \"python3\"]\n\n""",
            encoding="utf-8",
        )
        created.append(tools_path)

    if not search_path.exists():
        search_path.write_text(
            """# ContextHarbor web search configuration (v1.0)\n\n[search]\nenabled = true\nprovider = \"ddg\"\n# User-Agent sent for search requests\nuser_agent = \"ContextHarbor/1.0\"\n# Minimum seconds between provider requests\nmin_interval_seconds = 2.0\n# Optional SSRF safety controls\nallowed_hosts = []\nblocked_hosts = []\n\n""",
            encoding="utf-8",
        )
        created.append(search_path)

    return created


@dataclass(frozen=True)
class Config:
    # core
    host: str
    port: int
    reload: bool

    # models
    ollama_url: str
    default_chat_model: str
    default_embed_model: str

    # sources (library)
    kiwix_url: str
    kiwix_zim_dir: str
    ebooks_dir: str

    # search
    web_user_agent: str
    web_allowed_hosts: str
    web_blocked_hosts: str
    search_enabled: bool
    search_provider: str
    search_min_interval_seconds: float

    # tools
    enabled_tools: list[str]
    tool_plugin_modules: list[str]
    local_file_roots: list[str]
    local_file_max_bytes: int
    shell_exec_enabled: bool
    shell_exec_allow: list[str]
    shell_exec_requires_confirmation: bool

    # paths
    data_dir: str
    rag_db: str
    chat_db: str
    web_db: str
    research_db: str
    tool_db: str

    # limits
    max_upload_bytes: int
    max_research_rounds: int
    max_pages_per_round: int
    max_web_queries: int
    max_doc_queries: int
    max_json_parse_size: int


def _expand_path(p: str) -> str:
    return str(Path(os.path.expanduser(p)).resolve())


def _as_dict(val: Any) -> dict[str, Any]:
    return val if isinstance(val, dict) else {}


def load_config(*, config_dir: Path | None = None) -> Config:
    cfg_dir = config_dir or get_config_dir()
    core: dict[str, Any] = _read_toml(cfg_dir / "core.toml")
    tools: dict[str, Any] = _read_toml(cfg_dir / "tools.toml")
    search: dict[str, Any] = _read_toml(cfg_dir / "search.toml")

    core_core = _as_dict(core.get("core"))
    core_models = _as_dict(core.get("models"))
    core_paths = _as_dict(core.get("paths"))
    core_sources = _as_dict(core.get("sources"))
    core_limits = _as_dict(core.get("limits"))

    tools_sec = _as_dict(tools.get("tools"))
    tools_local = _as_dict(tools_sec.get("local_file_read"))
    tools_shell = _as_dict(tools_sec.get("shell_exec"))

    search_sec = _as_dict(search.get("search"))

    host_raw = str(core_core.get("host") or "0.0.0.0").strip()
    # Always bind the server to all interfaces by default.
    # Treat common loopback values as aliases so restarts behave consistently.
    host = "0.0.0.0" if host_raw in {"", "127.0.0.1", "localhost"} else host_raw
    port = int(core_core.get("port") or 8000)
    reload = bool(core_core.get("reload") or False)

    ollama_url = str(core_models.get("ollama_url") or "http://127.0.0.1:11434").rstrip("/")
    chat_model = str(core_models.get("chat_model") or "llama3.1")
    embed_model = str(core_models.get("embed_model") or "nomic-embed-text")

    # Sources / library
    # Prefer config file; fallback to env for backwards compatibility.
    kiwix_url = str(core_sources.get("kiwix_url") or os.getenv("KIWIX_URL") or "").rstrip("/")
    kiwix_zim_dir_raw = str(core_sources.get("kiwix_zim_dir") or os.getenv("KIWIX_ZIM_DIR") or "~/zims")
    ebooks_dir_raw = str(core_sources.get("ebooks_dir") or os.getenv("EBOOKS_DIR") or "~/Ebooks")
    kiwix_zim_dir = _expand_path(kiwix_zim_dir_raw)
    ebooks_dir = _expand_path(ebooks_dir_raw)

    data_dir_raw = str(core_paths.get("data_dir") or "~/.contextharbor/data")
    data_dir = _expand_path(data_dir_raw)
    Path(data_dir).mkdir(parents=True, exist_ok=True)

    max_upload_bytes = int(core_limits.get("max_upload_bytes") or (10 * 1024 * 1024))
    max_research_rounds = int(core_limits.get("max_research_rounds") or 6)
    max_pages_per_round = int(core_limits.get("max_pages_per_round") or 12)
    max_web_queries = int(core_limits.get("max_web_queries") or 6)
    max_doc_queries = int(core_limits.get("max_doc_queries") or 6)
    max_json_parse_size = int(core_limits.get("max_json_parse_size") or 100000)

    search_enabled = bool(search_sec.get("enabled") if "enabled" in search_sec else True)
    search_provider = str(search_sec.get("provider") or "ddg")
    web_user_agent = str(search_sec.get("user_agent") or "ContextHarbor/1.0")
    search_min_interval_seconds = float(search_sec.get("min_interval_seconds") or 2.0)

    enabled_tools_raw = tools_sec.get("enabled")
    enabled_tools = [str(x) for x in enabled_tools_raw] if isinstance(enabled_tools_raw, list) else []

    plugin_raw = tools_sec.get("plugin_modules")
    tool_plugin_modules = [str(x) for x in plugin_raw] if isinstance(plugin_raw, list) else []

    roots_raw = tools_local.get("roots")
    local_file_roots = [str(x) for x in roots_raw] if isinstance(roots_raw, list) else []
    local_file_max_bytes = int(tools_local.get("max_bytes") or 200000)

    shell_exec_enabled = bool(tools_shell.get("enabled") or False)
    shell_exec_requires_confirmation = bool(tools_shell.get("requires_confirmation") if "requires_confirmation" in tools_shell else True)
    shell_allow_raw = tools_shell.get("allow")
    shell_exec_allow = [str(x) for x in shell_allow_raw] if isinstance(shell_allow_raw, list) else []

    # SSRF safety lists are enforced in webstore/web_fetch; keep as comma-joined for legacy callers.
    allowed_hosts = search_sec.get("allowed_hosts")
    blocked_hosts = search_sec.get("blocked_hosts")
    web_allowed_hosts = ",".join([str(x) for x in allowed_hosts]) if isinstance(allowed_hosts, list) else ""
    web_blocked_hosts = ",".join([str(x) for x in blocked_hosts]) if isinstance(blocked_hosts, list) else ""

    return Config(
        host=host,
        port=port,
        reload=reload,
        ollama_url=ollama_url,
        default_chat_model=chat_model,
        default_embed_model=embed_model,
        kiwix_url=kiwix_url,
        kiwix_zim_dir=kiwix_zim_dir,
        ebooks_dir=ebooks_dir,
        web_user_agent=web_user_agent,
        web_allowed_hosts=web_allowed_hosts,
        web_blocked_hosts=web_blocked_hosts,
        search_enabled=search_enabled,
        search_provider=search_provider,
        search_min_interval_seconds=search_min_interval_seconds,
        enabled_tools=enabled_tools,
        tool_plugin_modules=tool_plugin_modules,
        local_file_roots=local_file_roots,
        local_file_max_bytes=local_file_max_bytes,
        shell_exec_enabled=shell_exec_enabled,
        shell_exec_allow=shell_exec_allow,
        shell_exec_requires_confirmation=shell_exec_requires_confirmation,
        data_dir=data_dir,
        rag_db=str(Path(data_dir) / "rag.sqlite3"),
        chat_db=str(Path(data_dir) / "chat.sqlite3"),
        web_db=str(Path(data_dir) / "web.sqlite3"),
        research_db=str(Path(data_dir) / "research.sqlite3"),
        tool_db=str(Path(data_dir) / "tool.sqlite3"),
        max_upload_bytes=max_upload_bytes,
        max_research_rounds=max_research_rounds,
        max_pages_per_round=max_pages_per_round,
        max_web_queries=max_web_queries,
        max_doc_queries=max_doc_queries,
        max_json_parse_size=max_json_parse_size,
    )


class _ConfigHandle:
    """Lazy config loader.

    Importing `contextharbor.config` should not immediately require config files.
    The first attribute access triggers a load.
    """

    def __init__(self) -> None:
        self._cfg: Config | None = None

    def reload_from_disk(self) -> Config:
        self._cfg = load_config()
        return self._cfg

    def _ensure(self) -> Config:
        if self._cfg is None:
            self._cfg = load_config()
        return self._cfg

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ensure(), name)


# Singleton used across the codebase: `from contextharbor import config; config.config.ollama_url`
config = _ConfigHandle()
