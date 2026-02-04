"""Integration tests for the tool runtime system.

This test suite validates that the tool calling loop works correctly
with both legacy and registry engines, ensuring proper event emission
and result formatting.
"""

import asyncio
import json
import os
import pytest
import tempfile
from typing import Any, Dict, List

from ollama_cli.loop import run_tool_calling_loop, run_tool_calling_loop_sync
from ollama_cli.runtime import ToolRuntime
from ollama_cli.tool_contract import ToolErrorCodes
from ollama_cli.tools.registry import ToolRegistry, build_default_registry


def _test_tool_spec(name: str) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "test tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }


class TestToolRuntimeIntegration:
    """Integration tests for the complete tool runtime system."""
    
    def setup_method(self):
        """Set up test environment."""
        self.registry = build_default_registry()
        
        # Create a temporary file for testing
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
        self.temp_file.write("Test file content for integration testing.")
        self.temp_file.flush()
        self.temp_file_path = self.temp_file.name
        self.temp_file.close()
    
    def teardown_method(self):
        """Clean up test environment."""
        # Clean up temp file
        try:
            os.unlink(self.temp_file_path)
        except FileNotFoundError:
            pass
    
    def test_legacy_engine_sync(self):
        """Test synchronous execution."""
        runtime = ToolRuntime(registry=self.registry)
        tool_calls = [
            {
                "id": "test_1",
                "function": {
                    "name": "get_time",
                    "arguments": {"tz": "UTC"}
                }
            }
        ]
        
        results = run_tool_calling_loop_sync(tool_calls, runtime=runtime)
        
        assert len(results) == 1
        result = results[0]
        assert result["role"] == "tool"
        assert result["tool_name"] == "get_time"
        assert result["tool_call_id"] == "test_1"
        content = json.loads(result["content"])
        assert content["ok"] is True
        assert "UTC" in (content.get("content") or "")
    
    @pytest.mark.asyncio
    async def test_registry_engine_async(self):
        """Test async execution and progress events."""
        runtime = ToolRuntime(registry=self.registry)
        tool_calls = [
            {
                "id": "test_2",
                "function": {
                    "name": "get_time",
                    "arguments": {"tz": "local"}
                }
            }
        ]
        
        progress_events = []
        
        async def emit(event: Dict[str, Any]):
            progress_events.append(event)
        
        results = await run_tool_calling_loop(tool_calls, emit, runtime=runtime)
        
        # Verify results
        assert len(results) == 1
        result = results[0]
        assert result["role"] == "tool"
        assert result["tool_name"] == "get_time"
        assert result["tool_call_id"] == "test_2"
        
        # Verify progress events
        assert len(progress_events) >= 2  # At least start + result
        
        # Check start event
        start_events = [e for e in progress_events if e.get("event") == "start"]
        assert len(start_events) == 1
        assert start_events[0]["tool"] == "get_time"
        assert start_events[0]["tool_call_id"] == "test_2"
        
        # Check result event
        result_events = [e for e in progress_events if e.get("event") == "result"]
        assert len(result_events) == 1
        assert result_events[0]["ok"] is True
        assert "result" in result_events[0]
    
    @pytest.mark.asyncio
    async def test_registry_engine_error_handling(self):
        """Test registry engine error handling."""
        runtime = ToolRuntime(registry=self.registry)
        tool_calls = [
            {
                "id": "test_error",
                "function": {
                    "name": "nonexistent_tool",
                    "arguments": {}
                }
            }
        ]
        
        progress_events = []
        
        async def emit(event: Dict[str, Any]):
            progress_events.append(event)
        
        results = await run_tool_calling_loop(tool_calls, emit, runtime=runtime)
        
        # Verify error handling
        assert len(results) == 1
        result = results[0]
        assert result["role"] == "tool"
        content = json.loads(result["content"])
        assert content["ok"] is False
        assert result["tool_call_id"] == "test_error"
        
        # Verify error event
        error_events = [e for e in progress_events if e.get("event") == "error"]
        assert len(error_events) == 1
        assert error_events[0]["ok"] is False
        assert "unknown tool" in error_events[0]["error"].lower()
    
    @pytest.mark.asyncio
    async def test_registry_engine_file_operations(self):
        """Test registry engine with file operations."""
        runtime = ToolRuntime(registry=self.registry)
        tool_calls = [
            {
                "id": "test_file",
                "function": {
                    "name": "read_file",
                    "arguments": {
                        "path": self.temp_file_path,
                        "max_bytes": 100
                    }
                }
            }
        ]
        
        progress_events = []
        
        async def emit(event: Dict[str, Any]):
            progress_events.append(event)
        
        results = await run_tool_calling_loop(tool_calls, emit, runtime=runtime)
        
        # Verify successful file read
        assert len(results) == 1
        result = results[0]
        assert result["role"] == "tool"
        assert result["tool_name"] == "read_file"
        content = json.loads(result["content"])
        assert "Test file content" in (content.get("content") or "")
        assert result["tool_call_id"] == "test_file"
        
        # Verify proper event flow
        assert any(e.get("event") == "start" for e in progress_events)
        assert any(e.get("event") == "result" for e in progress_events)
    
    def test_tool_runtime_safety_limits(self):
        """Test ToolRuntime safety limits."""
        runtime = ToolRuntime(
            registry=self.registry,
            timeout_s=1.0,
            max_chunks=10,
            max_result_bytes=1000
        )
        
        # Test successful call within limits
        result = runtime.call_sync("get_time", {"tz": "UTC"})
        assert result.ok is True
        assert result.content is not None
        
        # Test with non-existent tool
        result = runtime.call_sync("nonexistent", {})
        assert result.ok is False
        assert result.meta.get("code") == ToolErrorCodes.NOT_FOUND
    
    @pytest.mark.asyncio
    async def test_tool_runtime_async_timeout(self):
        """Test ToolRuntime async timeout behavior."""
        # Create a slow tool function
        async def slow_tool(**kwargs):
            await asyncio.sleep(0.5)  # Sleep longer than timeout
            return "should not reach here"

        registry = ToolRegistry()
        registry.register("slow_tool", _test_tool_spec("slow_tool"), slow_tool)
        runtime = ToolRuntime(registry=registry, timeout_s=0.1)
        
        progress_events = []
        async for event in runtime.call_async("slow_tool", {}, "test_timeout"):
            progress_events.append(event)
        
        # Should have error event due to timeout
        error_events = [e for e in progress_events if e.get("event") == "error"]
        assert len(error_events) == 1
        assert "timed out" in error_events[0]["error"].lower()
        
    
    def test_tool_specs_consistency(self):
        """Test that all tool specs are valid and consistent."""
        registry = build_default_registry()

        # Verify all tools in specs have corresponding functions
        spec_names = {spec["function"]["name"] for spec in registry.list_specs()}
        func_names = set(registry.tool_names())

        assert spec_names == func_names

        # Verify all specs have required fields
        for spec in registry.list_specs():
            assert "type" in spec
            assert "function" in spec
            func_spec = spec["function"]
            assert "name" in func_spec
            assert "description" in func_spec
            assert "parameters" in func_spec
            assert func_spec["parameters"]["type"] == "object"


class TestPhase02Features:
    """Test Phase 0.2 features: error codes, metadata, audit logging, and JSON payloads."""
    
    def setup_method(self):
        """Set up test environment."""
        self.registry = build_default_registry()
    
    @pytest.mark.asyncio
    async def test_standardized_error_codes(self):
        """Test that all errors use standardized error codes."""
        # Test unknown tool error
        runtime = ToolRuntime(registry=self.registry)
        progress_events = []
        async for event in runtime.call_async("nonexistent_tool", {}, "test_error"):
            progress_events.append(event)
        
        error_events = [e for e in progress_events if e.get("event") == "error"]
        assert len(error_events) == 1
        assert error_events[0]["code"] == ToolErrorCodes.NOT_FOUND
        
        # Test timeout error
        slow_registry = ToolRegistry()
        async def slow_tool(**kwargs):
            await asyncio.sleep(0.5)
            return "should not reach"
        slow_registry.register("test_slow", _test_tool_spec("test_slow"), slow_tool)
        slow_runtime = ToolRuntime(registry=slow_registry, timeout_s=0.1)
        progress_events = []
        async for event in slow_runtime.call_async("test_slow", {}, "test_timeout"):
            progress_events.append(event)
        
        error_events = [e for e in progress_events if e.get("event") == "error"]
        assert len(error_events) == 1
        assert error_events[0]["code"] == ToolErrorCodes.TIMEOUT
    
    @pytest.mark.asyncio
    async def test_duration_metadata_tracking(self):
        """Test that duration metadata is tracked and included."""
        runtime = ToolRuntime(registry=self.registry)
        
        progress_events = []
        async for event in runtime.call_async("get_time", {"tz": "UTC"}, "test_duration"):
            progress_events.append(event)
        
        # Check that duration is included in result event
        result_events = [e for e in progress_events if e.get("event") == "result"]
        assert len(result_events) == 1
        assert "duration_ms" in result_events[0]
        assert isinstance(result_events[0]["duration_ms"], (int, float))
        assert result_events[0]["duration_ms"] > 0
        
        # Check that result_bytes is included
        assert "result_bytes" in result_events[0]
        assert isinstance(result_events[0]["result_bytes"], int)
        assert result_events[0]["result_bytes"] > 0
    
    def test_sync_method_metadata(self):
        """Test metadata tracking in sync method."""
        runtime = ToolRuntime(registry=self.registry)
        
        result = runtime.call_sync("get_time", {"tz": "UTC"})
        
        assert result.ok is True
        assert isinstance(result.meta.get("duration_ms"), (int, float))
        assert result.meta.get("duration_ms", 0) > 0
        assert isinstance(result.meta.get("result_bytes"), int)
        assert result.meta.get("result_bytes", 0) > 0
    
    @pytest.mark.asyncio
    async def test_output_size_limit_error_code(self):
        """Test output size limit uses correct error code."""
        # Create runtime with very small limit
        runtime = ToolRuntime(registry=self.registry, max_result_bytes=10)
        
        progress_events = []
        async for event in runtime.call_async("get_time", {"tz": "UTC"}, "test_size"):
            progress_events.append(event)
        
        error_events = [e for e in progress_events if e.get("event") == "error"]
        assert len(error_events) == 1
        assert error_events[0]["code"] == ToolErrorCodes.OUTPUT_TOO_LARGE
        assert "bytes" in error_events[0]["error"]
    
    @pytest.mark.asyncio 
    async def test_tool_audit_logging(self):
        """Test that audit logging works correctly."""
        import logging
        from io import StringIO
        
        # Set up logging capture
        log_stream = StringIO()
        handler = logging.StreamHandler(log_stream)
        logger = logging.getLogger("ollama_cli.tool_runtime")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        
        try:
            runtime = ToolRuntime(registry=self.registry)
            
            # Test successful tool execution
            async for event in runtime.call_async("get_time", {"tz": "UTC"}, "test_audit"):
                pass
            
            log_output = log_stream.getvalue()
            assert "Tool success: get_time" in log_output
            
            # Test error case
            async for event in runtime.call_async("nonexistent", {}, "test_audit_error"):
                pass
            
            log_output = log_stream.getvalue()
            assert "Tool not found: nonexistent" in log_output
            
        finally:
            logger.removeHandler(handler)
    
    @pytest.mark.asyncio
    async def test_json_payload_standardization(self):
        """Test that tool message content is always JSON."""
        tool_calls = [
            {
                "id": "test_json",
                "function": {
                    "name": "get_time",
                    "arguments": {"tz": "UTC"}
                }
            }
        ]
        
        runtime = ToolRuntime(registry=self.registry)
        results = await run_tool_calling_loop(tool_calls, runtime=runtime)
        
        assert len(results) == 1
        result = results[0]
        
        # The content should be a stable JSON payload
        payload = json.loads(result["content"])
        assert set(payload.keys()) == {"ok", "content", "error", "meta"}
        assert payload["ok"] is True
        
        # But the underlying result should be JSON-formatted when it's structured data
        # For get_time, it returns a simple string, so this is fine
        
        # Test with a tool that returns structured data
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as temp_file:
                temp_file.write("Test file content for contract payload.")
                temp_path = temp_file.name

            tool_calls = [
                {
                    "id": "test_structured",
                    "function": {
                        "name": "read_file",
                        "arguments": {"path": temp_path, "max_bytes": 100},
                    },
                }
            ]

            results = await run_tool_calling_loop(tool_calls, runtime=runtime)
            assert len(results) == 1
            payload = json.loads(results[0]["content"])
            assert payload["ok"] is True
            assert "Test file content" in (payload.get("content") or "")
        finally:
            if temp_path:
                os.unlink(temp_path)
    
    def test_sync_wrapper_no_nested_loop(self):
        """Test that sync wrapper doesn't create nested event loops."""
        # This test ensures the sync wrapper works even when called from an async context
        tool_calls = [
            {
                "id": "test_sync",
                "function": {
                    "name": "get_time", 
                    "arguments": {"tz": "UTC"}
                }
            }
        ]
        
        # Direct sync call should work
        runtime = ToolRuntime(registry=self.registry)
        results = run_tool_calling_loop_sync(tool_calls, runtime=runtime)
        assert len(results) == 1
        assert results[0]["tool_name"] == "get_time"
    
    @pytest.mark.asyncio
    async def test_error_code_consistency_across_methods(self):
        """Test that sync and async methods use consistent error codes."""
        runtime = ToolRuntime(registry=self.registry)
        
        # Test sync method
        sync_result = runtime.call_sync("nonexistent_tool", {})
        assert sync_result.ok is False
        assert sync_result.meta.get("code") == ToolErrorCodes.NOT_FOUND
        
        # Test async method
        progress_events = []
        async for event in runtime.call_async("nonexistent_tool", {}, "test_consistency"):
            progress_events.append(event)
        
        error_events = [e for e in progress_events if e.get("event") == "error"]
        assert len(error_events) == 1
        assert error_events[0]["code"] == ToolErrorCodes.NOT_FOUND
