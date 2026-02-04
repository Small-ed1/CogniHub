"""Tests for tool runtime and registry system.

This module tests the new streaming tool execution engine
with all return types and error conditions.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from cognihub.tools.models import ToolResult, ToolProgress
from cognihub.tools.runtime import ToolRegistry, ToolSpec, ToolRuntime
from pydantic import BaseModel


# Test tool argument schemas
class SimpleArgs(BaseModel):
    message: str


class AsyncArgs(BaseModel):
    url: str


class GeneratorArgs(BaseModel):
    count: int


# Test tool handlers
def sync_handler(args: SimpleArgs) -> str:
    return f"Sync: {args.message}"


async def async_handler(args: AsyncArgs) -> dict:
    await asyncio.sleep(0.001)  # Simulate async work
    return {"url": args.url, "status": "ok"}


def sync_generator_handler(args: GeneratorArgs):
    for i in range(args.count):
        yield ToolResult(
            ok=True,
            result=f"Item {i}",
            meta={"progress": i + 1, "total": args.count}
        )


async def async_generator_handler(args: GeneratorArgs):
    for i in range(args.count):
        yield ToolProgress(step="processing", current=i + 1, total=args.count)
        await asyncio.sleep(0.001)
    
    yield ToolResult(
        ok=True,
        result=[f"Async item {i}" for i in range(args.count)],
        meta={"processed": args.count}
    )


def error_handler(args: SimpleArgs):
    raise ValueError("Test error")


def streaming_error_handler(args: GeneratorArgs):
    yield ToolProgress(step="starting", current=0, total=args.count)
    raise RuntimeError("Stream error")


class TestToolRegistry:
    """Test tool registry functionality."""
    
    def test_register_and_get_tool(self):
        registry = ToolRegistry()
        tool = ToolSpec(
            name="test_tool",
            description="Test tool",
            args_schema=SimpleArgs,
            handler=sync_handler
        )
        
        registry.register(tool)
        
        retrieved = registry.get("test_tool")
        assert retrieved is not None
        assert retrieved.name == "test_tool"
        assert retrieved.description == "Test tool"
        assert retrieved.args_schema == SimpleArgs
    
    def test_get_unknown_tool(self):
        registry = ToolRegistry()
        tool = registry.get("unknown")
        assert tool is None
    
    def test_schema_for_prompt(self):
        registry = ToolRegistry()
        registry.register(ToolSpec(
            name="test_tool",
            description="Test tool",
            args_schema=SimpleArgs,
            handler=sync_handler
        ))
        
        schemas = registry.schema_for_prompt()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "test_tool"
        assert schemas[0]["description"] == "Test tool"
        assert "properties" in schemas[0]["parameters"]


class TestToolRuntime:
    """Test tool runtime execution."""
    
    @pytest.fixture
    def registry(self):
        reg = ToolRegistry()
        reg.register(ToolSpec(
            name="sync_tool",
            description="Sync tool",
            args_schema=SimpleArgs,
            handler=sync_handler
        ))
        reg.register(ToolSpec(
            name="async_tool",
            description="Async tool",
            args_schema=AsyncArgs,
            handler=async_handler
        ))
        reg.register(ToolSpec(
            name="sync_gen_tool",
            description="Sync generator tool",
            args_schema=GeneratorArgs,
            handler=sync_generator_handler
        ))
        reg.register(ToolSpec(
            name="async_gen_tool",
            description="Async generator tool",
            args_schema=GeneratorArgs,
            handler=async_generator_handler
        ))
        reg.register(ToolSpec(
            name="error_tool",
            description="Error tool",
            args_schema=SimpleArgs,
            handler=error_handler
        ))
        reg.register(ToolSpec(
            name="stream_error_tool",
            description="Streaming error tool",
            args_schema=GeneratorArgs,
            handler=streaming_error_handler
        ))
        return reg
    
    @pytest.fixture
    def runtime(self, registry):
        return ToolRuntime(registry)
    
    @pytest.mark.asyncio
    async def test_sync_handler(self, runtime):
        results = []
        async for chunk in runtime.call_async("sync_tool", {"message": "test"}):
            results.append(chunk)
        
        assert len(results) == 1
        assert results[0].ok is True
        assert results[0].result == "Sync: test"
        assert results[0].tool == "sync_tool"
    
    @pytest.mark.asyncio
    async def test_async_handler(self, runtime):
        results = []
        async for chunk in runtime.call_async("async_tool", {"url": "http://example.com"}):
            results.append(chunk)
        
        assert len(results) == 1
        assert results[0].ok is True
        assert results[0].result["url"] == "http://example.com"
        assert results[0].tool == "async_tool"
    
    @pytest.mark.asyncio
    async def test_sync_generator_handler(self, runtime):
        results = []
        async for chunk in runtime.call_async("sync_gen_tool", {"count": 3}):
            results.append(chunk)
        
        assert len(results) == 3
        assert all(chunk.ok for chunk in results)
        assert results[0].result == "Item 0"
        assert results[1].result == "Item 1"
        assert results[2].result == "Item 2"
    
    @pytest.mark.asyncio
    async def test_async_generator_handler(self, runtime):
        results = []
        async for chunk in runtime.call_async("async_gen_tool", {"count": 2}):
            results.append(chunk)
        
        # Should have 2 progress chunks + 1 final result = 3 total
        assert len(results) == 3
        
        # First two should be progress
        assert results[0].ok is True
        assert isinstance(results[0].result, ToolProgress)
        assert results[0].result.step == "processing"
        assert results[0].result.current == 1
        
        assert results[1].ok is True
        assert isinstance(results[1].result, ToolProgress)
        assert results[1].result.current == 2
        
        # Last should be final result
        assert results[2].ok is True
        assert results[2].result == ["Async item 0", "Async item 1"]
        assert not isinstance(results[2].result, ToolProgress)
    
    @pytest.mark.asyncio
    async def test_unknown_tool(self, runtime):
        results = []
        async for chunk in runtime.call_async("unknown", {"message": "test"}):
            results.append(chunk)
        
        assert len(results) == 1
        assert results[0].ok is False
        assert results[0].code == "not_found"
        assert "Unknown tool" in results[0].error
        assert results[0].tool == "unknown"
    
    @pytest.mark.asyncio
    async def test_invalid_args(self, runtime):
        results = []
        async for chunk in runtime.call_async("sync_tool", {"invalid": "args"}):
            results.append(chunk)
        
        assert len(results) == 1
        assert results[0].ok is False
        assert results[0].code == "invalid_args"
        assert "validation" in results[0].error.lower()
        assert results[0].tool == "sync_tool"
        assert results[0].meta["type"] == "ValidationError"
    
    @pytest.mark.asyncio
    async def test_error_handler(self, runtime):
        results = []
        async for chunk in runtime.call_async("error_tool", {"message": "test"}):
            results.append(chunk)
        
        assert len(results) == 1
        assert results[0].ok is False
        assert results[0].code == "exception"
        assert "Test error" in results[0].error
        assert results[0].tool == "error_tool"
        assert results[0].meta["type"] == "ValueError"
    
    @pytest.mark.asyncio
    async def test_streaming_error_handler(self, runtime):
        results = []
        async for chunk in runtime.call_async("stream_error_tool", {"count": 3}):
            results.append(chunk)
        
        # Should have received progress before error
        assert len(results) >= 2  # At least progress + error
        
        # First should be progress
        assert results[0].ok is True
        assert isinstance(results[0].result, ToolProgress)
        
        # Last should be error result
        assert results[-1].ok is False
        assert results[-1].code == "exception"
        assert "Stream error" in results[-1].error
        assert results[-1].tool == "stream_error_tool"
        assert results[-1].meta["type"] == "RuntimeError"


class TestIntegration:
    """Integration tests with real tool functions."""
    
    @pytest.mark.asyncio
    async def test_tool_result_model_copy(self):
        """Test that tool name is properly set on copied ToolResult objects."""
        
        def handler_with_result(args):
            return ToolResult(ok=True, result="test", tool=None)
        
        registry = ToolRegistry()
        registry.register(ToolSpec(
            name="test_tool",
            description="Test",
            args_schema=SimpleArgs,
            handler=handler_with_result
        ))
        
        runtime = ToolRuntime(registry)
        results = []
        async for chunk in runtime.call_async("test_tool", {"message": "test"}):
            results.append(chunk)
        
        assert len(results) == 1
        assert results[0].tool == "test_tool"  # Tool name should be set


if __name__ == "__main__":
    pytest.main([__file__])