"""Contract tests for tool loop payload stability."""

import json

import pytest

from ollama_cli.loop import run_tool_calling_loop
from ollama_cli.runtime import ToolRuntime
from ollama_cli.tools.registry import build_default_registry


@pytest.mark.asyncio
async def test_tool_loop_contract_shape():
    registry = build_default_registry()
    runtime = ToolRuntime(registry=registry)
    tool_calls = [
        {
            "id": "contract_1",
            "function": {"name": "get_time", "arguments": {"tz": "UTC"}},
        }
    ]

    results = await run_tool_calling_loop(tool_calls, runtime=runtime)
    assert len(results) == 1

    payload = json.loads(results[0]["content"])
    assert set(payload.keys()) == {"ok", "content", "error", "meta"}
    assert isinstance(payload["meta"], dict)
