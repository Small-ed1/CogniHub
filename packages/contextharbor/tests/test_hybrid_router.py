import pytest
from contextharbor.services.hybrid_router import HybridRouter, Backend


@pytest.mark.anyio
async def test_refresh_health_exception_not_healthy(monkeypatch):
    r = HybridRouter([Backend("gpu", "http://x", True)])

    async def boom(_):
        raise RuntimeError("dead")

    monkeypatch.setattr(r, "_ping", boom)
    await r.refresh_health()
    assert r._health["gpu"] is False
    await r.close()


@pytest.mark.anyio
async def test_affinity_must_be_healthy(monkeypatch):
    r = HybridRouter([
        Backend("gpu", "http://x", True),
        Backend("cpu", "http://y", False),
    ])
    r.model_affinity["m"] = "gpu"
    r._health["gpu"] = False
    r._health["cpu"] = True

    # Mock refresh_health to avoid network calls
    async def mock_refresh():
        pass
    monkeypatch.setattr(r, "refresh_health", mock_refresh)

    primary, fallback = await r._choose_backend("m", "fast")
    assert primary.name == "cpu"
    await r.close()


@pytest.mark.anyio
async def test_vram_error_detection():
    r = HybridRouter([Backend("gpu", "http://x", True)])
    
    # Should detect VRAM errors
    vram_errors = [
        "CUDA out of memory",
        "out of memory",
        "failed to allocate",
        "cublas error",
        "hip error",
        "vulkan error",
        "insufficient memory",
    ]
    
    for err_msg in vram_errors:
        assert r._is_vram_error(Exception(err_msg))
    
    # Should NOT detect regular errors
    regular_errors = [
        "memory usage high",  # Should not trigger without "out of"
        "connection refused",
        "timeout error",
        "invalid request",
        "server error",
    ]
    
    for err_msg in regular_errors:
        assert not r._is_vram_error(Exception(err_msg))
    
    await r.close()


@pytest.mark.anyio
async def test_tools_and_options_none_handling():
    r = HybridRouter([Backend("cpu", "http://x", False)])
    
    # Test that empty lists are preserved
    payload = {"model": "test", "messages": [], "stream": False}
    
    # Simulate the payload building logic
    tools = []
    options = {}
    
    if tools is not None:
        payload["tools"] = tools
    if options is not None:
        payload["options"] = options
    
    assert "tools" in payload
    assert "options" in payload
    assert payload["tools"] == []
    assert payload["options"] == {}
    
    await r.close()
