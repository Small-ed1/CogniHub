#!/usr/bin/env python3
"""Test the tool contract implementation."""

from cognihub.tools.contract import ToolRequest, FinalAnswer, ToolCall
from cognihub.tools.registry import ToolRegistry, ToolSpec
from cognihub.tools.executor import ToolExecutor
from cognihub.toolstore import ToolStore
from pydantic import BaseModel
import asyncio


class TestArgs(BaseModel):
    message: str


async def test_handler(args: TestArgs) -> dict:
    return {"response": f"Echo: {args.message}"}


def test_contract_validation():
    """Test that the contract models validate correctly."""

    # Test tool request
    request_data = {
        "type": "tool_request",
        "id": "req_123",
        "tool_calls": [
            {
                "id": "call_01",
                "name": "test_tool",
                "arguments": {"message": "hello"}
            }
        ]
    }

    request = ToolRequest.model_validate(request_data)
    assert request.type == "tool_request"
    assert request.id == "req_123"
    assert len(request.tool_calls) == 1
    assert request.tool_calls[0].name == "test_tool"

    # Test final answer
    answer_data = {
        "type": "final",
        "id": "req_123",
        "answer": "This is the final answer."
    }

    answer = FinalAnswer.model_validate(answer_data)
    assert answer.type == "final"
    assert answer.answer == "This is the final answer."

    print("OK  Contract validation tests passed")


async def test_tool_execution():
    """Test that the tool execution system works."""

    # Create tool registry and register a test tool
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="test_tool",
        description="A test tool",
        args_model=TestArgs,
        handler=test_handler,
        side_effect="read_only",
    ))

    # Create tool store and executor
    import tempfile
    import os
    temp_db = tempfile.mktemp(suffix='.db')
    try:
        toolstore = ToolStore(temp_db)
        executor = ToolExecutor(registry, toolstore)

        # Create a tool call
        call = ToolCall(
            id="call_01",
            name="test_tool",
            arguments={"message": "hello world"}
        )

        # Execute the call
        result = await executor.run_calls([call], chat_id="test_chat", message_id="test_msg")

        # Check the result
        assert result["type"] == "tool_result"
        assert len(result["results"]) == 1
        result_data = result["results"][0]
        assert result_data["id"] == "call_01"
        assert result_data["name"] == "test_tool"
        assert result_data["ok"] is True
        assert result_data["data"]["response"] == "Echo: hello world"

        print("OK  Tool execution tests passed")
    finally:
        if os.path.exists(temp_db):
            os.unlink(temp_db)


if __name__ == "__main__":
    test_contract_validation()
    asyncio.run(test_tool_execution())
    print("All tests passed!")
