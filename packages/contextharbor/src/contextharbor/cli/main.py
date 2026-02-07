"""ContextHarbor CLI - Command-line interface for ContextHarbor.

This CLI talks to the actual ContextHarbor server endpoints
and uses the real streaming format (ndjson).
"""

import asyncio
import inspect
import json
import os
import sys
import signal
from pathlib import Path
from typing import Optional, Dict, Any
import argparse

import httpx

try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False


class ContextHarborCLI:
    """CLI client for ContextHarbor."""
    
    def __init__(self, host: str = "localhost", port: int = 8000, model: str = "llama3.1"):
        self.base_url = f"http://{host}:{port}"
        self.model = model
        self.session = None
        
    async def __aenter__(self):
        # Tool-enabled chats can take a while (search + second model call).
        self.session = httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0))
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.aclose()
        self.session = None
    
    async def chat_once(self, prompt: str, options: Optional[Dict[str, Any]] = None) -> str:
        """Send a single message and return response."""
        if not self.session:
            raise RuntimeError("CLI not initialized - use async with")
        
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True
        }
        
        if options:
            payload["options"] = options
            
        full_response = ""
        
        try:
            async with self.session.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
                headers={"Accept": "application/x-ndjson"},
            ) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")

                # Process ndjson streaming (newline-delimited JSON)
                async for line in _aiter_lines(response.aiter_lines()):
                    full_response += _process_stream_line(line)

        except Exception as e:
            msg = str(e) or repr(e)
            raise RuntimeError(f"Chat request failed: {msg}")
            
        return full_response

    async def list_models(self) -> list[str]:
        """List available models from the server."""
        if not self.session:
            raise RuntimeError("CLI not initialized - use async with")

        resp = self.session.get(f"{self.base_url}/api/models")
        if inspect.isawaitable(resp):
            resp = await resp

        if getattr(resp, "status_code", 0) != 200:
            raise RuntimeError("Failed to list models")

        data = resp.json() if hasattr(resp, "json") else {}
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            return []

        names: list[str] = []
        for m in models:
            if isinstance(m, str) and m:
                names.append(m)
                continue
            if isinstance(m, dict):
                name = m.get("name")
                if isinstance(name, str) and name:
                    names.append(name)
        return names

    async def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Fetch tool schema definitions from the server."""
        if not self.session:
            raise RuntimeError("CLI not initialized - use async with")

        resp = self.session.get(f"{self.base_url}/api/tools/schemas")
        if inspect.isawaitable(resp):
            resp = await resp

        if getattr(resp, "status_code", 0) != 200:
            raise RuntimeError("Failed to get tool schemas")

        data = resp.json() if hasattr(resp, "json") else []
        return data if isinstance(data, list) else []

    @staticmethod
    def load_core_config() -> Dict[str, Any]:
        """Load authoritative core config (TOML)."""
        from .. import config as ch_config

        cfg_dir = ch_config.get_config_dir()
        try:
            cfg = ch_config.load_config(config_dir=cfg_dir)
        except Exception:
            # CLI can still be used against an already-running server.
            return {"host": "localhost", "port": 8000, "model": "llama3.1"}

        return {"host": cfg.host, "port": cfg.port, "model": cfg.default_chat_model}


async def _aiter_lines(lines_obj: Any):
    """Iterate either an async iterator or a plain iterable."""
    if inspect.isawaitable(lines_obj):
        lines_obj = await lines_obj
    if hasattr(lines_obj, "__aiter__"):
        async for line in lines_obj:
            yield line
    else:
        for line in lines_obj:
            yield line


def _process_stream_line(line: Any) -> str:
    line = str(line).strip()
    if not line:
        return ""

    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return ""

    if data.get("type") == "error":
        print(f"\nError: {data.get('error', 'Unknown error')}", file=sys.stderr)
        return ""
    if data.get("type") == "ids":
        return ""

    content = data.get("message", {}).get("content", "")
    if content:
        print(content, end="", flush=True)
    return str(content or "")


async def run_one_shot(args: argparse.Namespace, cli: ContextHarborCLI):
    """Run a single chat query."""
    try:
        print(f"{cli.model}: ", end="", flush=True)
        await cli.chat_once(args.prompt, args.options)
        print()  # New line after response
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


async def run_repl(args: argparse.Namespace, cli: ContextHarborCLI):
    """Run interactive REPL mode."""
    print(f"ContextHarbor CLI - Connected to {cli.base_url}")
    print(f"Model: {cli.model}")
    print("Type /help for commands, /exit to quit")
    print()
    
    # Setup signal handling for graceful exit
    def signal_handler(signum, frame):
        print("\nGoodbye!")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    while True:
        try:
            if READLINE_AVAILABLE:
                prompt = "You: "
            else:
                prompt = "You: "
            
            user_input = input(prompt).strip()
            
            if not user_input:
                continue
                
            # Handle commands
            if user_input.startswith('/'):
                command = user_input[1:].split()[0]
                args_list = user_input[1:].split()[1:] if len(user_input.split()) > 1 else []
                
                if command in {"exit", "quit"}:
                    print("Goodbye!")
                    break
                elif command == "models":
                    models = await cli.list_models()
                    print("\n".join(models) if models else "(no models)")
                elif command == "tools":
                    schemas = await cli.get_tool_schemas()
                    if not schemas:
                        print("(no tools)")
                    else:
                        for s in schemas:
                            name = s.get("name") if isinstance(s, dict) else None
                            desc = s.get("description") if isinstance(s, dict) else None
                            if name:
                                print(f"{name}: {desc or ''}")
                elif command == "help":
                    print_help()
                elif command == "clear":
                    os.system('clear' if os.name == 'posix' else 'cls')
                elif command == "model":
                    if args_list:
                        new_model = args_list[0]
                        cli.model = new_model
                        print(f"Switched to model: {new_model}")
                        print("Note: this does not persist; edit core.toml to change defaults.")
                    else:
                        print(f"Current model: {cli.model}")
                else:
                    print(f"❌ Unknown command: /{command}")
                    print("💡 Type /help for available commands")
                continue
            
            # Regular chat message
            try:
                print(f"{cli.model}: ", end="", flush=True)
                await cli.chat_once(user_input, args.options)
                print()  # New line after response
            except RuntimeError as e:
                print(f"\n❌ Error: {e}")
                print("Tip: start the server with: contextharbor run")
                
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except EOFError:
            print("\nGoodbye!")
            break


def print_help():
    """Print help information."""
    print("""
 Available commands:
  /exit, /quit    - Exit the CLI
  /help           - Show this help message
  /clear          - Clear the screen
  /model <name>   - Switch to a different model

💡 Tips:
  • Use arrow keys to navigate command history (if available)
  • Press Ctrl+C to exit at any time
  • Configuration is saved to ~/.config/contextharbor/config.json

 To start the server:
    contextharbor run
    """)


def _ollama_list_models(*, ollama_url: str) -> list[str]:
    """Return the list of installed Ollama model tags (names)."""

    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{ollama_url}/api/tags")
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        raise RuntimeError(f"Failed to list Ollama models at {ollama_url}: {exc}")

    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return []

    out: list[str] = []
    for m in models:
        if not isinstance(m, dict):
            continue
        name = m.get("name")
        if isinstance(name, str) and name:
            out.append(name)
    return out


def _preflight_models(cfg) -> None:
    installed = set(_ollama_list_models(ollama_url=cfg.ollama_url))

    missing: list[tuple[str, str]] = []
    if cfg.default_chat_model and cfg.default_chat_model not in installed:
        missing.append(("chat_model", cfg.default_chat_model))
    if cfg.default_embed_model and cfg.default_embed_model not in installed:
        missing.append(("embed_model", cfg.default_embed_model))

    if not missing:
        return

    lines = ["Configured models are not installed in Ollama:"]
    for key, val in missing:
        lines.append(f"- {key} = {val}")
        if ":" not in val:
            latest = f"{val}:latest"
            if latest in installed:
                lines.append(f"  - You have {latest} installed. Fix by setting {key} = \"{latest}\" in core.toml")
        lines.append(f"  - Install with: `ollama pull {val}`")

    lines.append("Edit your config in core.toml under [models].")
    raise RuntimeError("\n".join(lines))


def _cmd_run(args: argparse.Namespace) -> None:
    """Start the ContextHarbor server (deterministic startup)."""
    import httpx
    import uvicorn

    from .. import config as ch_config

    cfg_dir = Path(os.path.expanduser(args.config_dir)) if args.config_dir else ch_config.get_config_dir()
    created = ch_config.ensure_default_config_files(cfg_dir)
    if created:
        created_str = ", ".join(str(p) for p in created)
        print(f"Created default config: {created_str}")
        print("Edit these files and re-run `contextharbor run` if needed.")

    try:
        cfg = ch_config.load_config(config_dir=cfg_dir)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)

    # Preflight: Ollama must be reachable.
    try:
        with httpx.Client(timeout=3.0) as client:
            r = client.get(f"{cfg.ollama_url}/api/version")
            r.raise_for_status()
    except Exception as exc:
        print(
            "Ollama is unreachable. Fix this before starting ContextHarbor:\n"
            f"- Expected Ollama at: {cfg.ollama_url}\n"
            "- Start it with: `ollama serve`\n"
            f"- Error: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)

    # Preflight: configured models must exist (no silent fallback).
    try:
        _preflight_models(cfg)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)

    # Make config dir explicit for the server process.
    os.environ["CONTEXTHARBOR_CONFIG_DIR"] = str(cfg_dir)

    uvicorn.run(
        "contextharbor.app:app",
        host=cfg.host,
        port=cfg.port,
        reload=cfg.reload,
        log_level="info",
    )


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="ContextHarbor CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="Start the ContextHarbor server")
    p_run.add_argument("--config-dir", default=None, help="Config directory (default: platform user config dir)")

    p_chat = sub.add_parser("chat", help="Chat with a running ContextHarbor server")
    p_chat.add_argument("prompt", nargs="?", help="Prompt for one-shot mode (optional)")
    p_chat.add_argument("--host", default=None, help="Server host (overrides core.toml)")
    p_chat.add_argument("--port", type=int, default=None, help="Server port (overrides core.toml)")
    p_chat.add_argument("--model", default=None, help="Model to use (overrides core.toml)")
    p_chat.add_argument("--options", type=json.loads, help="Model options as JSON string")

    p_models = sub.add_parser("models", help="List available models from the server")
    p_models.add_argument("--host", default=None, help="Server host (overrides core.toml)")
    p_models.add_argument("--port", type=int, default=None, help="Server port (overrides core.toml)")

    p_tools = sub.add_parser("tools", help="List available tools (schemas) from the server")
    p_tools.add_argument("--host", default=None, help="Server host (overrides core.toml)")
    p_tools.add_argument("--port", type=int, default=None, help="Server port (overrides core.toml)")

    # Back-compat: if the first token isn't a known command, treat it as `chat`.
    if len(sys.argv) == 1:
        sys.argv.append("chat")
    elif sys.argv[1] not in {"run", "chat", "models", "tools", "-h", "--help"}:
        sys.argv.insert(1, "chat")

    args = parser.parse_args()

    if args.cmd == "run":
        _cmd_run(args)
        return

    # Default to chat
    if not args.cmd:
        args.cmd = "chat"

    cfg = ContextHarborCLI.load_core_config()
    if getattr(args, "host", None):
        cfg["host"] = args.host
    if getattr(args, "port", None):
        cfg["port"] = args.port
    if getattr(args, "model", None):
        cfg["model"] = args.model
    
    async def run():
        async with ContextHarborCLI(host=cfg["host"], port=cfg["port"], model=cfg.get("model") or "") as cli:
            if args.cmd == "models":
                models = await cli.list_models()
                print("\n".join(models) if models else "(no models)")
                return
            if args.cmd == "tools":
                schemas = await cli.get_tool_schemas()
                if not schemas:
                    print("(no tools)")
                else:
                    for s in schemas:
                        name = s.get("name")
                        desc = s.get("description")
                        print(f"{name}: {desc}")
                return

            # chat
            if args.prompt:
                await run_one_shot(args, cli)
            else:
                await run_repl(args, cli)
    
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
