"""CogniHub CLI - Command-line interface for CogniHub.

This CLI talks to the actual CogniHub server endpoints
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


class CogniHubCLI:
    """CLI client for CogniHub."""
    
    def __init__(self, host: str = "localhost", port: int = 8000, model: str = "llama3.1"):
        self.base_url = f"http://{host}:{port}"
        self.model = model
        self.session = None
        
    async def __aenter__(self):
        self.session = httpx.AsyncClient(timeout=60.0)
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
            raise RuntimeError(f"Chat request failed: {e}")
            
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
            if not isinstance(m, dict):
                continue
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

    def load_config(self) -> Dict[str, Any]:
        """Load configuration from file."""
        config_path = Path.home() / ".config" / "cognihub" / "config.json"

        defaults: Dict[str, Any] = {
            "host": "localhost",
            "port": 8000,
            "model": "llama3.1",
            "stream": True,
        }

        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    user_config = json.load(f)
                    if isinstance(user_config, dict):
                        defaults.update(user_config)
            except Exception:
                # Use defaults if config is broken
                pass

        return defaults

    def save_config(self, config: Dict[str, Any]) -> None:
        """Save configuration to file."""
        config_path = Path.home() / ".config" / "cognihub" / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Warning: Failed to save config: {e}", file=sys.stderr)


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


async def run_one_shot(args: argparse.Namespace, cli: CogniHubCLI):
    """Run a single chat query."""
    try:
        print(f"🤖 {args.model}: ", end="", flush=True)
        await cli.chat_once(args.prompt, args.options)
        print()  # New line after response
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


async def run_repl(args: argparse.Namespace, cli: CogniHubCLI):
    """Run interactive REPL mode."""
    print(f"🚀 CogniHub CLI - Connected to {cli.base_url}")
    print(f"📝 Model: {cli.model}")
    print("💡 Type /help for commands, /exit to quit")
    print()
    
    # Setup signal handling for graceful exit
    def signal_handler(signum, frame):
        print("\n👋 Goodbye!")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    while True:
        try:
            if READLINE_AVAILABLE:
                prompt = "❓ You: "
            else:
                prompt = "❓ You: "
            
            user_input = input(prompt).strip()
            
            if not user_input:
                continue
                
            # Handle commands
            if user_input.startswith('/'):
                command = user_input[1:].split()[0]
                args_list = user_input[1:].split()[1:] if len(user_input.split()) > 1 else []
                
                if command in {"exit", "quit"}:
                    print("👋 Goodbye!")
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
                        print(f"🔄 Switched to model: {new_model}")
                        # Save to config
                        config = cli.load_config()
                        config["model"] = new_model
                        cli.save_config(config)
                    else:
                        print(f"📝 Current model: {cli.model}")
                else:
                    print(f"❌ Unknown command: /{command}")
                    print("💡 Type /help for available commands")
                continue
            
            # Regular chat message
            try:
                print(f"🤖 {cli.model}: ", end="", flush=True)
                await cli.chat_once(user_input, args.options)
                print()  # New line after response
            except RuntimeError as e:
                print(f"\n❌ Error: {e}")
                print("💡 Make sure the CogniHub server is running with: cognihub-app")
                
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
        except EOFError:
            print("\n👋 Goodbye!")
            break


def print_help():
    """Print help information."""
    print("""
🔧 Available commands:
  /exit, /quit    - Exit the CLI
  /help           - Show this help message
  /clear          - Clear the screen
  /model <name>   - Switch to a different model

💡 Tips:
  • Use arrow keys to navigate command history (if available)
  • Press Ctrl+C to exit at any time
  • Configuration is saved to ~/.config/cognihub/config.json

🚀 To start the server: 
    cognihub-app
    """)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="CogniHub CLI - Command-line interface for CogniHub")
    parser.add_argument("prompt", nargs="?", help="Prompt for one-shot mode (optional)")
    parser.add_argument("--host", default="localhost", help="CogniHub server host (default: localhost)")
    parser.add_argument("--port", type=int, default=8000, help="CogniHub server port (default: 8000)")
    parser.add_argument("--model", default="llama3.1", help="Model to use (default: llama3.1)")
    parser.add_argument("--options", type=json.loads, help="Model options as JSON string")
    
    args = parser.parse_args()
    
    # Load config and override with CLI args
    cli_config = CogniHubCLI().load_config()
    cli_config.update({
        "host": args.host,
        "port": args.port,
        "model": args.model
    })
    
    async def run():
        async with CogniHubCLI(host=cli_config["host"], port=cli_config["port"], model=cli_config["model"]) as cli:
            if args.prompt:
                # One-shot mode
                await run_one_shot(args, cli)
            else:
                # REPL mode
                await run_repl(args, cli)
    
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
