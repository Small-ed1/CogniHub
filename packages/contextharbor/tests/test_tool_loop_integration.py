"""Loop-level integration tests for tool system.

This module tests the actual tool-loop behavior with both legacy
and registry engines to ensure compatibility and correctness.
"""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict

from contextharbor.services.tooling import (
    run_tool_calling_loop,
    _tool_engine,
    _get_or_create_runtime,
    ToolLoopResult,
    ToolDocSearchReq,
    ToolWebSearchReq,
    ToolKiwixSearchReq,
)
from contextharbor.tools.models import ToolResult, ToolProgress


class TestToolLoopIntegration:
    """Test actual tool calling loop behavior."""
    
    @pytest.fixture
    def mock_http(self):
        """Mock HTTP client."""
        client = AsyncMock()
        return client
    
    @pytest.fixture
    def mock_ingest_queue(self):
        """Mock ingest queue."""
        queue = MagicMock()
        queue.enqueue = AsyncMock()
        return queue
    
    @pytest.fixture
    def sample_messages(self):
        """Sample conversation messages."""
        return [
            {"role": "user", "content": "Search for information about Python"}
        ]
    
    @pytest.fixture
    def tool_call_response(self):
        """Mock response with tool calls."""
        return {
            "message": {
                "role": "assistant",
                "content": "I'll search for information about Python.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "doc_search",
                            "arguments": json.dumps({"query": "Python", "top_k": 3})
                        }
                    }
                ]
            }
        }
    
    @pytest.fixture
    def final_response(self):
        """Mock final response after tool execution."""
        return {
            "message": {
                "role": "assistant", 
                "content": "Based on my search, Python is a programming language..."
            }
        }
    
    @pytest.mark.asyncio
    async def test_legacy_path_unchanged(
        self, 
        mock_http, 
        mock_ingest_queue, 
        sample_messages, 
        tool_call_response, 
        final_response
    ):
        """Test that legacy path produces same results as before."""
        
        # Mock HTTP responses
        mock_http.post.side_effect = [
            # First call - returns tool call
            MagicMock(json=lambda: tool_call_response, raise_for_status=MagicMock()),
            # Second call - returns final response  
            MagicMock(json=lambda: final_response, raise_for_status=MagicMock())
        ]
        
        # Mock the actual tool execution to avoid database calls
        with patch('contextharbor.services.tooling.tool_doc_search') as mock_doc_search:
            mock_doc_search.return_value = {
                "query": "Python",
                "results": [{"content": "Python is a programming language"}]
            }
            
            # Force legacy engine
            with patch('contextharbor.services.tooling._tool_engine', return_value='legacy'):
                result = await run_tool_calling_loop(
                    http=mock_http,
                    ollama_url="http://localhost:11434",
                    model="llama3.1",
                    messages=sample_messages,
                    options=None,
                    keep_alive=None,
                    embed_model="nomic-embed-text",
                    ingest_queue=mock_ingest_queue,
                    kiwix_url=None,
                    max_rounds=3
                )
        
        assert isinstance(result, ToolLoopResult)
        assert result.used_tools is True
        assert "Python is a programming language" in result.content or "Based on my search" in result.content
        assert len(result.messages) > len(sample_messages)  # Should have tool messages added
    
    @pytest.mark.asyncio
    async def test_registry_path_emits_progress(
        self, 
        mock_http, 
        mock_ingest_queue, 
        sample_messages, 
        tool_call_response, 
        final_response
    ):
        """Test that registry path emits progress events."""
        
        # Mock HTTP responses
        mock_http.post.side_effect = [
            MagicMock(json=lambda: tool_call_response, raise_for_status=MagicMock()),
            MagicMock(json=lambda: final_response, raise_for_status=MagicMock())
        ]
        
        # Track emitted events
        emitted_events = []
        
        async def capture_emit(event):
            emitted_events.append(event)
        
        # Force registry engine
        with patch('contextharbor.services.tooling._tool_engine', return_value='registry'):
            with patch('contextharbor.services.tooling.tool_doc_search') as mock_doc_search:
                mock_doc_search.return_value = {
                    "query": "Python",
                    "results": [{"content": "Python is a programming language"}]
                }
                
                result = await run_tool_calling_loop(
                    http=mock_http,
                    ollama_url="http://localhost:11434",
                    model="llama3.1",
                    messages=sample_messages,
                    options=None,
                    keep_alive=None,
                    embed_model="nomic-embed-text",
                    ingest_queue=mock_ingest_queue,
                    kiwix_url=None,
                    max_rounds=3,
                    emit=capture_emit
                )
        
        assert isinstance(result, ToolLoopResult)
        assert result.used_tools is True
        
        # Should have status and tool events
        event_types = [event.get("type") for event in emitted_events]
        assert "status" in event_types
        assert "tool" in event_types
        
        # Tool execution should be tracked
        tool_events = [e for e in emitted_events if e.get("type") == "tool"]
        assert len(tool_events) > 0
        assert tool_events[0]["name"] == "doc_search"
    
    @pytest.mark.asyncio
    async def test_error_tool_yields_ok_false_and_stops(
        self, 
        mock_http, 
        mock_ingest_queue, 
        sample_messages
    ):
        """Test that error tools produce ok=False chunk and stop cleanly."""
        
        # Mock response with tool call that will fail
        error_tool_response = {
            "message": {
                "role": "assistant",
                "content": "I'll try to execute a failing tool.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "doc_search",
                            "arguments": json.dumps({"query": "", "top_k": 3})  # Empty query should fail
                        }
                    }
                ]
            }
        }
        
        # Mock final response after error handling
        final_response = {
            "message": {
                "role": "assistant",
                "content": "I encountered an error with the tool execution."
            }
        }
        
        mock_http.post.side_effect = [
            MagicMock(json=lambda: error_tool_response, raise_for_status=MagicMock()),
            MagicMock(json=lambda: final_response, raise_for_status=MagicMock())
        ]
        
        # Force legacy engine for this test
        with patch('contextharbor.services.tooling._tool_engine', return_value='legacy'):
            result = await run_tool_calling_loop(
                http=mock_http,
                ollama_url="http://localhost:11434",
                model="llama3.1",
                messages=sample_messages,
                options=None,
                keep_alive=None,
                embed_model="nomic-embed-text",
                ingest_queue=mock_ingest_queue,
                kiwix_url=None,
                max_rounds=3
            )
        
        # Should complete despite tool error
        assert isinstance(result, ToolLoopResult)
        assert result.used_tools is True
        
        # Check that error was recorded in messages
        tool_messages = [msg for msg in result.messages if msg.get("role") == "tool"]
        assert len(tool_messages) > 0
        
        # Tool message should contain error payload
        tool_content = json.loads(tool_messages[0]["content"])
        assert tool_content["ok"] is False
        assert "error" in tool_content
        assert tool_content["tool"] == "doc_search"
    
    @pytest.mark.asyncio
    async def test_runtime_signature_caching(self):
        """Test that runtime signature properly identifies configuration changes."""
        
        # Import the signature function directly
        from contextharbor.services.tooling import _runtime_signature
        
        # Test signature generation
        http1 = MagicMock()
        http2 = MagicMock()
        ingest1 = MagicMock()
        
        sig1 = _runtime_signature(http1, ingest1, "model1", "url1")
        sig2 = _runtime_signature(http1, ingest1, "model2", "url1") 
        sig3 = _runtime_signature(http1, ingest1, "model1", "url2")
        sig4 = _runtime_signature(http2, ingest1, "model1", "url1")
        sig5 = _runtime_signature(http1, ingest1, "model1", "url1")
        
        assert sig1 != sig2  # Different embed model
        assert sig1 != sig3  # Different kiwix URL
        assert sig1 != sig4  # Different http client (different object id)
        assert sig1 == sig5  # Same configuration should be identical
    
    @pytest.mark.asyncio
    async def test_safety_limits_enforced(self):
        """Test that safety limits are enforced in registry mode."""
        
        from contextharbor.tools.runtime import ToolRegistry, ToolSpec, ToolRuntime
        from contextharbor.tools.models import ToolProgress
        from pydantic import BaseModel
        
        # Create test tool that violates limits
        class LargeArgs(BaseModel):
            data: str
        
        async def large_output_tool(args: LargeArgs):
            # Generate large output
            large_data = "x" * (5 * 1024 * 1024)  # 5MB
            return {"large_data": large_data}
        
        def infinite_stream_tool(args: LargeArgs):
            # Generate infinite stream
            i = 0
            while True:
                yield ToolProgress(step="processing", current=i, total=100)
                i += 1
        
        # Test large output limit
        registry = ToolRegistry()
        registry.register(ToolSpec(
            name="large_output_tool",
            description="Tool with large output",
            args_schema=LargeArgs,
            handler=large_output_tool
        ))
        
        runtime = ToolRuntime(registry, max_result_bytes=1024 * 1024)  # 1MB limit
        
        results = []
        async for chunk in runtime.call_async("large_output_tool", {"data": "test"}):
            results.append(chunk)
        
        assert len(results) == 1
        assert results[0].ok is False
        assert results[0].code == "output_too_large"
        
        # Test infinite stream limit
        registry.register(ToolSpec(
            name="infinite_stream_tool",
            description="Infinite streaming tool",
            args_schema=LargeArgs,
            handler=infinite_stream_tool
        ))
        
        results = []
        async for chunk in runtime.call_async("infinite_stream_tool", {"data": "test"}):
            results.append(chunk)
            if len(results) >= 150:  # Safety break for test
                break
        
        assert len(results) > 0
        # Should have stopped due to chunk limit
        error_chunk = results[-1]
        assert error_chunk.ok is False
        assert error_chunk.code == "max_chunks_exceeded"


if __name__ == "__main__":
    pytest.main([__file__])
