#!/usr/bin/env python3
"""Tiny Ollama API CLI with interactive setup.

A modular Python CLI application that provides command-line access to Ollama API
with additional tool capabilities including web search via SearxNG and offline
content access via Kiwix.
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import replace
from typing import Any, Dict, List, Optional

# Import core components
from .client import OllamaClient
from .config import AppConfig, DEFAULT_BASE_URL, DEFAULT_CONFIG_FILE, load_config_from_env, resolve_config_file
from .loop import run_tool_calling_loop_sync
from .runtime import ToolRuntime
from .tools.registry import ToolRegistry, build_default_registry


def _use_advanced_interactive() -> bool:
    """Return True if advanced interactive mode is enabled via environment variable.

    This enables the hybrid (Plan C) richer interactive flow behind a flag.
    """
    val = os.getenv("OLLAMA_CLI_INTERACTIVE_ADVANCED", "0").lower()
    return val in ("1", "true", "yes", "on")


def _get_app_config(args: argparse.Namespace) -> AppConfig:
    """Get application configuration for CLI commands."""
    config = getattr(args, "_app_config", None)
    if isinstance(config, AppConfig):
        return config
    return load_config_from_env()


def _apply_cli_overrides(app_config: AppConfig, args: argparse.Namespace) -> AppConfig:
    """Apply CLI overrides to config loaded from environment.

    The config dataclasses are frozen, so we use dataclasses.replace.
    """
    tools_cfg = app_config.tools
    client_cfg = app_config.client

    searxng_url = getattr(args, "searxng_url", None)
    if searxng_url:
        tools_cfg = replace(tools_cfg, searxng_url=str(searxng_url))

    kiwix_url = getattr(args, "kiwix_url", None)
    if kiwix_url:
        tools_cfg = replace(tools_cfg, kiwix_url=str(kiwix_url))

    kiwix_zim_dir = getattr(args, "kiwix_zim_dir", None)
    if kiwix_zim_dir:
        tools_cfg = replace(tools_cfg, kiwix_zim_dir=str(kiwix_zim_dir))

    timeout = getattr(args, "timeout", None)
    if timeout is not None:
        client_cfg = replace(client_cfg, timeout_s=int(timeout))
        tools_cfg = replace(tools_cfg, timeout_s=int(timeout))

    return replace(app_config, client=client_cfg, tools=tools_cfg)


def _build_client(args: argparse.Namespace, app_config: AppConfig) -> OllamaClient:
    """Construct OllamaClient using resolved config + CLI overrides."""
    base_url = getattr(args, "host", None) or app_config.client.base_url or DEFAULT_BASE_URL
    return OllamaClient(
        base_url=str(base_url),
        timeout=app_config.client.timeout_s,
        api_key=app_config.client.api_key,
    )


def normalize_tools_arg(args) -> Optional[List[str]]:
    """Normalize tools argument from command line."""
    tool_list = getattr(args, 'tool', None)
    if tool_list:
        return tool_list

    # Support interactive configuration objects
    tools_list = getattr(args, 'tools_list', None)
    if tools_list:
        return tools_list
    elif getattr(args, 'tools', False):
        return ["get_time", "read_file", "web_search", "web_open"]
    return None


def _select_tools_from_list(tool_names: List[str], registry: ToolRegistry) -> List[Dict[str, Any]]:
    """Select tool definitions from tool_names list."""
    available_tools = {spec["function"]["name"]: spec for spec in registry.list_specs()}
    selected_tools = []
    
    for tool_name in tool_names:
        if tool_name in available_tools:
            selected_tools.append(available_tools[tool_name])
        else:
            print(f"Warning: Tool '{tool_name}' not found, skipping", file=sys.stderr)
    
    return selected_tools


def cmd_list(args: argparse.Namespace) -> None:
    """List available models."""
    try:
        app_config = _get_app_config(args)
        if getattr(args, "debug_tools", False):
            logging.basicConfig(level=logging.DEBUG)

        client = _build_client(args, app_config)
        data = client.tags()
        models = data.get("models", [])
        if not models:
            print("No models found")
            return
        
        for model in models:
            size = model.get("details", {}).get("parameter_size", "")
            digest = model.get("digest", "")[:12] if model.get("digest") else ""
            size_info = f" [{size}]" if size else ""
            digest_info = f" {digest}" if digest else ""
            print(f"- {model['name']}{size_info}{digest_info}")
    except Exception as e:
        print(f"Error listing models: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_pull(args: argparse.Namespace) -> None:
    """Pull a model."""
    try:
        app_config = _get_app_config(args)
        if getattr(args, "debug_tools", False):
            logging.basicConfig(level=logging.DEBUG)

        client = _build_client(args, app_config)
        for chunk in client.pull(args.model):
            status = chunk.get("status", "")
            digest = chunk.get("digest", "")[:12] if chunk.get("digest") else ""
            print(f"{status} {digest}")
    except Exception as e:
        print(f"Error pulling model: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_gen(args: argparse.Namespace) -> None:
    """Generate text."""
    try:
        app_config = _get_app_config(args)

        client = _build_client(args, app_config)
        
        # Build request
        options = None
        if args.think:
            options = {"thinking": args.think}
        
        # Handle streaming
        if args.stream:
            # Stream response
            for chunk in client.generate(args.model, args.prompt, options=options, stream=True):
                piece = chunk.get("response", "")
                print(piece, end="", flush=True)
            print()  # New line
        else:
            # Get single response
            for chunk in client.generate(args.model, args.prompt, options=options, stream=False):
                full_response = chunk.get("response", "")
                print(full_response)
    except Exception as e:
        print(f"Error generating text: {e}", file=sys.stderr)
        sys.exit(1)


def _pick_default_model(client: OllamaClient, requested: Optional[str] = None) -> str:
    if requested:
        return requested

    env_model = os.getenv("OLLAMA_MODEL")
    if env_model:
        return env_model

    try:
        data = client.tags()
        models = [m.get("name") for m in data.get("models", []) if m.get("name")]
    except Exception:
        models = []

    preferred = [
        "llama3.1:latest",
        "llama3.2:latest",
        "llama3:latest",
        "deepseek-r1:8b",
        "phi3:mini",
    ]
    for name in preferred:
        if name in models:
            return name
    if models:
        return models[0]

    raise RuntimeError("No models available. Try: ollama-cli pull <model>")


def cmd_research(args: argparse.Namespace) -> None:
    """Run deep research (search + open + synthesize)."""
    try:
        from .research_pipeline import run_deep_research

        app_config = _get_app_config(args)
        client = _build_client(args, app_config)
        model = _pick_default_model(client, getattr(args, "model", None))
        preset = getattr(args, "preset", "standard")
        seed_urls = getattr(args, "url", None)
        searxng_url = app_config.tools.searxng_url
        kiwix_url = app_config.tools.kiwix_url

        out = run_deep_research(
            client=client,
            model=model,
            query=args.query,
            preset_name=preset,
            seed_urls=seed_urls,
            searxng_url=searxng_url,
            kiwix_url=kiwix_url,
        )
        print(out)
    except Exception as e:
        print(f"Error in research: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_chat(args: argparse.Namespace) -> None:
    """Interactive chat with tools."""
    try:
        app_config = _get_app_config(args)

        client = _build_client(args, app_config)

        # Set up tool registry and runtime for tool calling
        registry = build_default_registry(app_config.tools)
        runtime = ToolRuntime(registry=registry, runtime_config=app_config.runtime)

        # If no model provided, try to use saved configuration.
        if not getattr(args, "model", None):
            try:
                from .interactive import load_configuration
                saved = load_configuration() or {}
            except Exception:
                saved = {}

            if saved.get("model"):
                args.model = saved.get("model")
            if getattr(args, "system", None) is None and saved.get("system"):
                args.system = saved.get("system")
            if getattr(args, "temperature", None) is None and saved.get("temperature") is not None:
                args.temperature = saved.get("temperature")
            if getattr(args, "think", None) is None and saved.get("thinking"):
                args.think = saved.get("thinking")

            # Only apply saved tools if user didn't explicitly specify tools.
            if not getattr(args, "tool", None) and not getattr(args, "tools", False) and saved.get("tools"):
                args.tools_list = saved.get("tools")

        if not getattr(args, "model", None):
            args.model = _pick_default_model(client)

        model: str = str(getattr(args, "model"))

        # Chat options (temperature, thinking, etc.)
        chat_options: Dict[str, Any] = {}
        temperature = getattr(args, "temperature", None)
        if temperature is not None:
            chat_options["temperature"] = temperature
        think = getattr(args, "think", None)
        if think:
            chat_options["thinking"] = think
        options = chat_options or None
        
        # Normalize tools first
        tools_list = normalize_tools_arg(args)
        tools = None
        if tools_list:
            tools = _select_tools_from_list(tools_list, registry)
        
        # Set up file access controls for security
        file_security: Dict[str, Any] = {
            "allowed_paths": getattr(args, "allowed_read_paths", None),
            "unsafe_mode": getattr(args, "unsafe_read", False),
        }
        
        # Build messages
        messages: List[Dict[str, Any]] = []
        if args.system:
            messages.append({"role": "system", "content": args.system})
        
        print("Starting chat (Ctrl+D to exit)")

        tool_output_mode = getattr(args, "tool_output", "summary")
        debug_tools = bool(getattr(args, "debug_tools", False))

        def _print_tool_result(tool_msg: Dict[str, Any]) -> None:
            tool_name = str(tool_msg.get("tool_name") or "")
            content = tool_msg.get("content")
            if not isinstance(content, str):
                content = str(content or "")

            if tool_output_mode == "raw":
                print(f"Tool result ({tool_name}): {content}")
                return

            try:
                data = json.loads(content)
            except Exception:
                print(f"Tool result ({tool_name}): <unparseable>")
                return

            ok = bool(data.get("ok"))
            if ok:
                print(f"Tool ok: {tool_name}")
            else:
                err = data.get("error")
                print(f"Tool error: {tool_name}: {err}")
        
        while True:
            try:
                user_input = input("You: ")
                cmd = user_input.strip().lower()
                
                # Check for exit commands
                if cmd in {"/exit", "/quit", "/q"}:
                    print("Goodbye!")
                    break
                
                # Add user message
                messages.append({"role": "user", "content": user_input})
                
                # Call model with tools
                tool_calls: List[Dict[str, Any]] = []
                assistant_content = ""
                
                # First, get initial assistant response (may include tool calls)
                for chunk in client.chat(messages, model, tools=tools, stream=False, options=options):
                    if "message" in chunk:
                        message = chunk["message"]
                        
                        # Handle tool calls
                        if "tool_calls" in message:
                            tool_calls.extend(message["tool_calls"])

                        # Accumulate assistant content
                        if "content" in message and message["content"]:
                            assistant_content += message["content"]

                if assistant_content:
                    print(f"Assistant: {assistant_content}")

                # Add assistant message to history (include tool_calls if present)
                assistant_msg: Dict[str, Any] = {"role": "assistant", "content": assistant_content}
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                messages.append(assistant_msg)
                
                # Execute tools if any were called
                if tool_calls and tools:
                    if debug_tools:
                        for tc in tool_calls:
                            fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                            name = fn.get("name")
                            arguments = fn.get("arguments")
                            print(f"Tool call: {name} args={arguments}")

                    tool_results = run_tool_calling_loop_sync(
                        tool_calls,
                        tool_context=file_security,
                        runtime=runtime,
                    )

                    for tool_msg in tool_results:
                        _print_tool_result(tool_msg)
                     
                    # Add tool results to conversation
                    for result in tool_results:
                        messages.append(result)
                    
                    # Get final assistant response after tool execution
                    final_response = ""
                    for chunk in client.chat(messages, model, tools=tools, stream=False, options=options):
                        if "message" in chunk and "content" in chunk["message"]:
                            content = chunk["message"]["content"]
                            final_response += content
                    
                    # Print final response and add to history
                    if final_response:
                        print(f"Assistant: {final_response}")
                        messages.append({"role": "assistant", "content": final_response})
                
                
            except EOFError:
                print("\nGoodbye!")
                break
            except KeyboardInterrupt:
                print("\nInterrupted. Use /exit to quit.")
                continue
                
    except Exception as e:
        print(f"Error in chat: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_interactive(args):
    """Command for interactive mode."""
    if getattr(args, "advanced", False):
        from .interactive import start_interactive
        start_interactive()
        return 0

    from .interactive import interactive_or_saved_config, save_configuration, start_interactive
    
    app_config = _get_app_config(args)
    base_url = args.host or app_config.client.base_url or DEFAULT_BASE_URL
    client = OllamaClient(
        base_url=base_url,
        timeout=app_config.client.timeout_s,
        api_key=app_config.client.api_key,
    )
    config = interactive_or_saved_config(client)
    
    if not config:
        return 1
    
    if config.get("save"):
        save_configuration(config)
    
    start_interactive(config)
    return 0


def _run_default_interactive(app_config: AppConfig, base_url: str) -> int:
    """Run interactive setup flow (used when no subcommand is provided)."""
    if _use_advanced_interactive():
        from .interactive import start_interactive

        start_interactive()
        return 0

    from .interactive import interactive_or_saved_config, save_configuration, start_interactive

    client = OllamaClient(
        base_url=base_url,
        timeout=app_config.client.timeout_s,
        api_key=app_config.client.api_key,
    )
    config = interactive_or_saved_config(client)

    if not config:
        return 1

    if config.get("save"):
        save_configuration(config)

    start_interactive(config)
    return 0


def cmd_tools(args: argparse.Namespace) -> None:
    """List known tool names (and descriptions)."""
    app_config = _get_app_config(args)
    registry = build_default_registry(app_config.tools)
    specs = registry.list_specs()
    for spec in specs:
        fn = spec.get("function") or {}
        name = fn.get("name") or ""
        desc = fn.get("description") or ""
        if getattr(args, "quiet", False):
            print(str(name))
        else:
            print(f"- {name}: {desc}")


def build_parser():
    """Build main argument parser."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", help="Ollama base URL (default: OLLAMA_BASE_URL or http://localhost:11434)")
    common.add_argument("--timeout", type=int, help="Request timeout in seconds (overrides OLLAMA_TIMEOUT)")

    tool_cfg_group = common.add_argument_group("tool backends")
    tool_cfg_group.add_argument("--searxng-url", dest="searxng_url", help="Override SearxNG base URL (default: SEARXNG_URL)")
    tool_cfg_group.add_argument("--kiwix-url", dest="kiwix_url", help="Override Kiwix base URL (default: KIWIX_URL)")
    tool_cfg_group.add_argument("--kiwix-zim-dir", dest="kiwix_zim_dir", help="Override local ZIM directory (default: KIWIX_ZIM_DIR)")

    parser = argparse.ArgumentParser(
        description="Tiny Ollama API CLI with interactive setup",
        epilog="Run with no arguments for interactive mode",
        parents=[common],
    )

    parser.add_argument("--no-interactive", action="store_true", help="Skip interactive setup")
    parser.add_argument("--reset-config", action="store_true", help="Reset saved configuration")
    
    subparsers = parser.add_subparsers(dest="command", required=False)
    
    # List command
    sub_list = subparsers.add_parser("list", help="List local models (/api/tags)", parents=[common])
    sub_list.set_defaults(func=cmd_list)
    
    # Pull command
    sub_pull = subparsers.add_parser("pull", help="Pull a model (/api/pull)", parents=[common])
    sub_pull.add_argument("model", help="Model name to pull")
    sub_pull.set_defaults(func=cmd_pull)
    
    # Generate command
    sub_gen = subparsers.add_parser("gen", help="Generate text (/api/generate)", parents=[common])
    sub_gen.add_argument("model", help="Model name")
    sub_gen.add_argument("prompt", help="Prompt text")
    sub_gen.add_argument("--stream", action="store_true", help="Stream response")
    sub_gen.add_argument("--think", help="Enable thinking output (true/false/high/medium/low)")
    sub_gen.set_defaults(func=cmd_gen)

    # Research command
    sub_research = subparsers.add_parser("research", help="Deep research with citations", parents=[common])
    sub_research.add_argument("query", help="Research query")
    sub_research.add_argument("--model", help="Model name (defaults to OLLAMA_MODEL or first available)")
    sub_research.add_argument("--preset", choices=["quick", "standard", "deep"], default="standard")
    sub_research.add_argument("--url", action="append", help="Seed URL to include (repeatable). Skips search if provided.")
    sub_research.set_defaults(func=cmd_research)
    
    # Chat command
    sub_chat = subparsers.add_parser("chat", help="Interactive chat (/api/chat)", parents=[common])
    sub_chat.add_argument("model", nargs="?", help="Model name (optional if configured)")
    sub_chat.add_argument("--system", help="System prompt")
    sub_chat.add_argument("--temperature", type=float, help="Sampling temperature")
    sub_chat.add_argument("--think", help="Enable thinking output (true/false/high/medium/low)")
    sub_chat.add_argument("--tools", action="store_true", help="Enable default tool calling (get_time, read_file, web_search, web_open)")
    sub_chat.add_argument("--tool", action="append", help="Enable a specific tool (repeatable). Overrides default tools.")
    sub_chat.add_argument(
        "--allowed-read-path",
        action="append",
        dest="allowed_read_paths",
        help="Allow read_file access under this path (repeatable)",
    )
    sub_chat.add_argument("--unsafe-read", action="store_true", help="Disable read path restrictions (DANGEROUS)")
    sub_chat.add_argument("--debug-tools", action="store_true", help="Debug tool execution")
    sub_chat.add_argument("--tool-output", choices=["raw", "summary"], default="summary", help="Tool output format")
    sub_chat.set_defaults(func=cmd_chat)

    # Tools command
    sub_tools = subparsers.add_parser("tools", help="List available tools", parents=[common])
    sub_tools.add_argument("--quiet", action="store_true", help="Only print tool names")
    sub_tools.set_defaults(func=cmd_tools)
    
    # Interactive command
    sub_interactive = subparsers.add_parser("interactive", help="Run interactive setup + chat", parents=[common])
    sub_interactive.add_argument("--advanced", action="store_true", help="Launch the advanced interactive shell")
    sub_interactive.set_defaults(func=cmd_interactive)

    return parser


def main():
    """Main entry point with full interactive support."""
    # Check for reset config flag first
    if "--reset-config" in sys.argv:
        try:
            config_path = resolve_config_file(DEFAULT_CONFIG_FILE)
            os.remove(config_path)
            print("Configuration reset successfully")
        except Exception as e:
            print(f"Failed to reset configuration: {e}")
        return 0
    # Parse args. If no subcommand is provided, default to interactive mode.
    parser = build_parser()
    args = parser.parse_args()

    app_config = load_config_from_env()
    app_config = _apply_cli_overrides(app_config, args)
    args._app_config = app_config

    # Prefer CLI argument for base URL, fallback to env config
    args.host = args.host or app_config.client.base_url or DEFAULT_BASE_URL

    if not getattr(args, "command", None):
        if getattr(args, "no_interactive", False):
            parser.print_help()
            return 1
        return _run_default_interactive(app_config, str(args.host))
    
    # Execute command
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
