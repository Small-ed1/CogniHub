"""Interactive mode functionality.

This module provides all interactive UI/UX functionality including configuration
wizards, user prompts, and chat orchestration.
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from .client import OllamaClient
from .config import DEFAULT_BASE_URL, load_config_from_env, resolve_config_file


def _coerce_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s if s else None
    s = str(value).strip()
    return s if s else None


def _coerce_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append(s)
    return out


def _coerce_optional_str_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    return _coerce_str_list(value)


def _coerce_optional_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_optional_thinking(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    s = value.strip().lower()
    if s in {"low", "medium", "high", "true", "false"}:
        return s
    return None


def _print_advanced_help() -> None:
    print("\nCommands:")
    print("  help                     Show this help")
    print("  list | models             List local models")
    print("  pull <model>              Pull a model")
    print("  gen [model] <prompt>      One-shot generation")
    print("  chat [model]              Start interactive chat")
    print("  research <query>          Deep research with citations")
    print("  config                    Run configuration wizard")
    print("  defaults                  Show current defaults")
    print("  exit | /exit | /quit | /q  Quit")


def _safe_input(prompt: str) -> Optional[str]:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        # Treat Ctrl-D / Ctrl-C as end-of-input in the interactive loop
        return None


def _pick_model_interactively(client: OllamaClient, current: Optional[str] = None) -> Optional[str]:
    try:
        data = client.tags()
        names = [m.get("name") for m in data.get("models", []) if m.get("name")]
    except Exception:
        names = []

    if not names:
        print("No models found. Try: ollama-cli pull <model>")
        return None

    default_idx = 0
    if current and current in names:
        default_idx = names.index(current)

    idx = get_user_choice("Select model:", names, default=default_idx)
    return names[idx]


def get_user_choice(question: str, options: List[str], default: Optional[int] = None) -> int:
    """Get user choice from numbered list.
    
    Args:
        question: Prompt question
        options: List of option descriptions
        default: Default option index
        
    Returns:
        Selected option index
    """
    print(f"\n{question}")
    for i, option in enumerate(options):
        marker = f" {i}> " if i != default else f"*{i}> "
        print(f"{marker}{option}")
    
    while True:
        try:
            choice = input(f"Choice (0-{len(options)-1}): ").strip()
            if not choice and default is not None:
                return default
            
            idx = int(choice)
            if 0 <= idx < len(options):
                return idx
            
            print(f"Please enter a number between 0 and {len(options)-1}")
        except (ValueError, KeyboardInterrupt, EOFError):
            if default is not None:
                print(f"Using default choice: {default}")
                return default
            print("Please enter a valid number")


def interactive_startup(client: OllamaClient) -> Dict[str, Any]:
    """Run interactive configuration wizard.
    
    Args:
        client: OllamaClient instance
        
    Returns:
        Configuration dictionary
    """
    print("=== Ollama CLI Interactive Setup ===")
    
    # Get available models
    try:
        models_data = client.tags()
        model_names = [model["name"] for model in models_data.get("models", [])]
    except Exception:
        model_names = ["gemma3", "llama3.2:3b", "mistral"]  # Fallback options
    
    if not model_names:
        model_names = ["gemma3"]  # Ultimate fallback
    
    model_idx = get_user_choice(
        "Select model:",
        model_names,
        default=0
    )
    selected_model = model_names[model_idx]
    
    # Tool selection
    tool_level = get_user_choice(
        "Select tool level:",
        [
            "No tools",
            "Basic tools (get_time, read_file)",
            "Web tools (basic + web_search, web_open)",
            "All tools (web + kiwix tools)"
        ],
        default=2
    )
    
    tool_mapping = {
        0: [],
        1: ["get_time", "read_file"],
        2: ["get_time", "read_file", "web_search", "web_open"],
        3: ["get_time", "read_file", "web_search", "web_open", 
              "kiwix_search", "kiwix_open", "kiwix_suggest", "kiwix_list_zims"]
    }
    selected_tools = tool_mapping[tool_level]
    
    # System prompt
    system_prompt = input("\nSystem prompt (press Enter for default): ").strip()
    if not system_prompt:
        system_prompt = "You are a helpful AI assistant."
    
    # Temperature settings
    temperature_choice = get_user_choice(
        "Select temperature:",
        [
            "Low (0.1) - More focused",
            "Medium (0.7) - Balanced (default)",
            "High (1.0) - More creative"
        ],
        default=1
    )
    temp_mapping = {0: 0.1, 1: 0.7, 2: 1.0}
    temperature = temp_mapping[temperature_choice]
    
    # Thinking mode
    thinking_choice = get_user_choice(
        "Enable thinking mode:",
        [
            "No thinking",
            "Low verbosity",
            "Medium verbosity", 
            "High verbosity"
        ],
        default=0
    )
    think_mapping = {0: False, 1: "low", 2: "medium", 3: "high"}
    thinking = think_mapping[thinking_choice]
    
    # Save configuration
    save_config = get_user_choice(
        "Save configuration for next time?",
        ["No", "Yes"],
        default=1
    ) == 1
    
    return {
        "model": selected_model,
        "tools": selected_tools,
        "system": system_prompt,
        "temperature": temperature,
        "thinking": thinking,
        "debug_tools": False,
        "tool_output": "raw",
        "save": save_config
    }


def save_configuration(config: Dict[str, Any]):
    """Save configuration to file.
    
    Args:
        config: Configuration dictionary
    """
    try:
        from .config import DEFAULT_CONFIG_FILE
        config_file = resolve_config_file(DEFAULT_CONFIG_FILE)
        config_dir = os.path.dirname(config_file)
        
        # Ensure config directory exists
        os.makedirs(config_dir, exist_ok=True)
        
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        print(f"Configuration saved to {config_file}")
    except Exception as e:
        print(f"Error saving configuration: {e}", file=sys.stderr)


def load_configuration() -> Optional[Dict[str, Any]]:
    """Load configuration from file.
    
    Returns:
        Configuration dictionary or None if not found
    """
    try:
        from .config import DEFAULT_CONFIG_FILE
        config_file = resolve_config_file(DEFAULT_CONFIG_FILE)
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        return None


def interactive_or_saved_config(client: OllamaClient) -> Optional[Dict[str, Any]]:
    """Load saved config or run interactive setup.
    
    Args:
        client: OllamaClient instance
        
    Returns:
        Configuration dictionary or None if failed
    """
    # Try to load saved configuration
    config = load_configuration()
    
    if config:
        use_saved = get_user_choice(
            "Found saved configuration:",
            [
                f"Use saved: {config.get('model', 'unknown')} with {len(config.get('tools', []))} tools",
                "Create new configuration"
            ],
            default=0
        ) == 0
        
        if not use_saved:
            config = None
    
    # Run interactive setup if no config or user chose new
    if not config:
        config = interactive_startup(client)
    
    return config


def config_to_args(config: Dict[str, Any]) -> argparse.Namespace:
    """Convert config dict to argparse.Namespace compatible with cmd_chat.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        argparse.Namespace with equivalent fields
    """
    args = argparse.Namespace()
    
    # Required fields
    args.model = config["model"]
    args.tools_list = config.get("tools", [])
    
    # Optional fields
    args.system = config.get("system")
    args.temperature = config.get("temperature")
    args.think = config.get("thinking")
    args.debug_tools = config.get("debug_tools", False)
    args.tool_output = config.get("tool_output", "raw")
    args.allowed_read_paths = config.get("allowed_read_paths")
    args.unsafe_read = config.get("unsafe_read", False)
    
    # Other required fields for cmd_chat
    app_config = load_config_from_env()
    args.host = app_config.client.base_url or DEFAULT_BASE_URL
    args._app_config = app_config
    args.timeout = 60
    args.api_key = None
    
    return args


def start_configured_chat(client: OllamaClient, config: Dict[str, Any]):
    """Start chat with pre-configured settings using cmd_chat.
    
    Args:
        client: OllamaClient instance
        config: Configuration dictionary
    """
    from .cli import cmd_chat
    
    # Convert config to args and use the same chat logic as CLI
    args = config_to_args(config)
    return cmd_chat(args)


def start_interactive(config_override: Optional[Dict[str, Any]] = None) -> None:
    """Hybrid interactive shell (Plan C).

    This guided shell routes users to the right action without requiring
    subcommands. It is used when advanced interactive is enabled.
    """
    from .cli import cmd_chat, cmd_gen, cmd_list, cmd_pull
    from .research_pipeline import run_deep_research

    app_config = load_config_from_env()
    base_url = app_config.client.base_url or DEFAULT_BASE_URL
    client = OllamaClient(
        base_url=base_url,
        timeout=app_config.client.timeout_s,
        api_key=app_config.client.api_key,
    )

    if config_override is not None:
        config = config_override
    else:
        config = load_configuration() or {}
    current_model: Optional[str] = _coerce_optional_str(config.get("model"))
    current_tools: List[str] = _coerce_str_list(config.get("tools"))
    current_system: Optional[str] = _coerce_optional_str(config.get("system"))
    current_temperature: Optional[float] = _coerce_optional_float(config.get("temperature"))
    current_think: Optional[str] = _coerce_optional_thinking(config.get("thinking"))
    current_allowed_read_paths: Optional[List[str]] = _coerce_optional_str_list(
        config.get("allowed_read_paths")
    )
    current_unsafe_read: bool = bool(config.get("unsafe_read", False))

    print("ollama-cli interactive (advanced)")
    if current_model:
        print(f"Defaults: model={current_model} tools={len(current_tools)}")
    else:
        print("Defaults: model=<not set> (type 'config' to set defaults)")
    print("Type 'help' for commands. Ctrl+D or 'exit' to quit.\n")

    first_choice = get_user_choice(
        "What do you want to do?",
        [
            "Chat",
            "Generate text",
            "Deep research",
            "List models",
            "Pull a model",
            "Configure defaults",
            "Exit",
        ],
        default=0,
    )
    menu_to_command = {
        0: "chat",
        1: "gen",
        2: "research",
        3: "list",
        4: "pull",
        5: "config",
        6: "exit",
    }
    pending_line = menu_to_command.get(first_choice)

    while True:
        line: Optional[str]
        if pending_line is not None:
            line = pending_line
            pending_line = None
        else:
            line = _safe_input("ollama> ")
        if line is None:
            print("\nGoodbye!")
            return

        line = line.strip()
        if not line:
            continue

        lowered = line.lower()
        if lowered in {"exit", "quit", "q", "/exit", "/quit", "/q"}:
            print("Goodbye!")
            return

        if lowered in {"help", "?"}:
            _print_advanced_help()
            continue

        if lowered in {"defaults", "show"}:
            print("\nCurrent defaults:")
            print(f"  base_url: {base_url}")
            print(f"  model: {current_model or '<not set>'}")
            print(f"  tools: {', '.join(current_tools) if current_tools else '<none>'}")
            print(f"  system: {current_system or '<none>'}")
            print(f"  temperature: {current_temperature if current_temperature is not None else '<default>'}")
            print(f"  thinking: {current_think if current_think else '<off>'}")
            print(f"  allowed_read_paths: {current_allowed_read_paths or '<none>'}")
            print(f"  unsafe_read: {bool(current_unsafe_read)}\n")
            continue

        # Config wizard (updates defaults and can persist)
        if lowered in {"config", "setup"}:
            new_cfg = interactive_startup(client)
            if new_cfg.get("save"):
                save_configuration(new_cfg)
            config = new_cfg
            current_model = _coerce_optional_str(config.get("model"))
            current_tools = _coerce_str_list(config.get("tools"))
            current_system = _coerce_optional_str(config.get("system"))
            current_temperature = _coerce_optional_float(config.get("temperature"))
            current_think = _coerce_optional_thinking(config.get("thinking"))
            current_allowed_read_paths = _coerce_optional_str_list(config.get("allowed_read_paths"))
            current_unsafe_read = bool(config.get("unsafe_read", False))
            continue

        parts = line.split()
        cmd = parts[0].lower()
        rest = parts[1:]

        if cmd in {"list", "models"}:
            try:
                cmd_list(argparse.Namespace(host=base_url))
            except SystemExit:
                pass
            continue

        if cmd == "pull":
            pull_model = rest[0] if rest else ""
            if not pull_model:
                pull_model = (_safe_input("Model (name:tag): ") or "").strip()
            pull_model = (pull_model or "").strip()
            if not pull_model:
                continue
            try:
                cmd_pull(argparse.Namespace(host=base_url, model=pull_model))
            except SystemExit:
                pass
            continue

        if cmd == "gen":
            gen_model: Optional[str] = None
            prompt = ""
            if rest:
                if len(rest) >= 2:
                    gen_model = rest[0]
                    prompt = " ".join(rest[1:]).strip()
                else:
                    prompt = " ".join(rest).strip()

            if not prompt:
                prompt_input = _safe_input("Prompt: ")
                prompt = (prompt_input or "").strip()
            if not prompt:
                continue

            if not gen_model or gen_model == "-":
                gen_model = current_model
            if not gen_model:
                picked = _pick_model_interactively(client, current_model)
                if not picked:
                    continue
                gen_model = picked

            try:
                cmd_gen(
                    argparse.Namespace(
                        host=base_url,
                        model=str(gen_model),
                        prompt=prompt,
                        stream=False,
                        think=current_think,
                    )
                )
            except SystemExit:
                pass
            continue

        if cmd == "chat":
            chat_model: Optional[str] = rest[0] if rest else current_model
            if not chat_model:
                picked = _pick_model_interactively(client, current_model)
                if not picked:
                    continue
                chat_model = picked

            args = argparse.Namespace(
                host=base_url,
                model=str(chat_model),
                system=current_system,
                tools_list=current_tools,
                tools=False,
                tool=None,
                temperature=current_temperature,
                think=current_think,
                allowed_read_paths=current_allowed_read_paths,
                unsafe_read=bool(current_unsafe_read),
                debug_tools=False,
                tool_output="summary",
            )
            try:
                cmd_chat(args)
            except SystemExit:
                pass
            continue

        if cmd in {"research", "r"}:
            query = " ".join(rest).strip() if rest else ""
            if not query:
                query = (_safe_input("Research query: ") or "").strip()
            if not query:
                continue

            research_model = current_model
            if not research_model:
                picked = _pick_model_interactively(client, current_model)
                if not picked:
                    continue
                research_model = picked

            preset_idx = get_user_choice("Research depth:", ["quick", "standard", "deep"], default=1)
            preset = ["quick", "standard", "deep"][preset_idx]

            try:
                out = run_deep_research(
                    client=client,
                    model=research_model,
                    query=query,
                    preset_name=preset,
                    seed_urls=None,
                    searxng_url=app_config.tools.searxng_url,
                    kiwix_url=app_config.tools.kiwix_url,
                )
                print("\n" + out + "\n")
            except Exception as e:
                print(f"Deep research failed: {e}")
                urls = (_safe_input("Paste URLs to research instead (comma-separated, blank to cancel): ") or "").strip()
                if not urls:
                    continue
                seed_urls = [u.strip() for u in urls.split(",") if u.strip()]
                try:
                    out = run_deep_research(
                        client=client,
                        model=research_model,
                        query=query,
                        preset_name=preset,
                        seed_urls=seed_urls,
                        searxng_url=app_config.tools.searxng_url,
                        kiwix_url=app_config.tools.kiwix_url,
                    )
                    print("\n" + out + "\n")
                except Exception as e2:
                    print(f"Research failed again: {e2}")
            continue

        # Fallback: ask how to route
        route = get_user_choice(
            "Route this input as:",
            ["Quick answer (chat)", "Deep research (with citations)", "Cancel"],
            default=0,
        )
        if route == 2:
            continue

        fallback_model = current_model
        if not fallback_model:
            picked = _pick_model_interactively(client, current_model)
            if not picked:
                continue
            fallback_model = picked

        if route == 1:
            preset_idx = get_user_choice("Research depth:", ["quick", "standard", "deep"], default=1)
            preset = ["quick", "standard", "deep"][preset_idx]
            try:
                out = run_deep_research(
                    client=client,
                    model=fallback_model,
                    query=line,
                    preset_name=preset,
                    seed_urls=None,
                    searxng_url=app_config.tools.searxng_url,
                    kiwix_url=app_config.tools.kiwix_url,
                )
                print("\n" + out + "\n")
            except Exception as e:
                print(f"Research failed: {e}")
            continue

        # Quick answer
        one_shot_messages: List[Dict[str, Any]] = []
        if current_system:
            one_shot_messages.append({"role": "system", "content": current_system})
        one_shot_messages.append({"role": "user", "content": line})

        options: Optional[Dict[str, Any]] = None
        if current_temperature is not None:
            options = {"temperature": current_temperature}
        if current_think:
            options = (options or {})
            options["thinking"] = current_think

        try:
            resp: Dict[str, Any] = {}
            for chunk in client.chat(one_shot_messages, str(fallback_model), stream=False, options=options):
                resp = chunk
            msg = (resp.get("message", {}) or {}).get("content") or ""
            print("\n" + msg.strip() + "\n")
        except Exception as e:
            print(f"Chat failed: {e}")
