#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Check if API is running
if ! curl -sf http://127.0.0.1:8000/health 2>/dev/null; then
    echo "Warning: API server may not be running."
    echo "Start with: scripts/servers.sh start"
    echo "Or run manually: uvicorn contextharbor.app:app --reload --host 0.0.0.0 --port 8000"
    echo ""
fi

# Activate venv and run TUI
cd "$APP_DIR"

if [ -d ".venv" ]; then
    source .venv/bin/activate
    contextharbor-tui
else
    echo "Virtual environment not found. Create it with:"
    echo "  python3 -m venv .venv"
    echo "  source .venv/bin/activate"
    echo "  python -m pip install -e \"packages/ollama_cli[dev]\" -e \"packages/contextharbor[dev]\""
fi
