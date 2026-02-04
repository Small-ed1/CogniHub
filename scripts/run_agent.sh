#!/usr/bin/env bash
set -euo pipefail

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
else
  echo "Virtual environment not found. Create it with: python3 -m venv .venv"
  exit 1
fi

export OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3}"
export OLLAMA_SUPERVISOR="${OLLAMA_SUPERVISOR:-}"
export API_BASE="${API_BASE:-http://localhost:8000}"

# optional: web search backend
# export SEARXNG_URL="${SEARXNG_URL:-http://localhost:8080/search}"

python scripts/ollama_tool_agent.py
