#!/usr/bin/env python3

from __future__ import annotations

import os

import requests

from scripts.ollama_tool_agent import AgentConfig, ToolCallingAgent, build_registry


def _ollama_reachable(ollama_host: str) -> bool:
    try:
        r = requests.get(ollama_host.rstrip("/") + "/api/version", timeout=1.0)
        return r.status_code < 500
    except Exception:
        return False


def main() -> int:
    # Set environment if needed
    os.environ.setdefault("OLLAMA_HOST", "http://localhost:11434")
    os.environ.setdefault("OLLAMA_MODEL", "qwen3:8b")
    os.environ.setdefault("DEBUG_AGENT", "1")

    ollama_host = os.environ["OLLAMA_HOST"]
    if not _ollama_reachable(ollama_host):
        print(f"SKIP Ollama not reachable: {ollama_host}")
        return 0

    cfg = AgentConfig()
    agent = ToolCallingAgent(cfg, build_registry())

    # Smoke test prompt
    prompt = "what is 2+2"
    print(f"Testing prompt: {prompt}")
    result = agent.run(prompt)
    print("Result:")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
