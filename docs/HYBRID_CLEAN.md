# CogniHub Hybrid CPU/GPU Inference - Production Ready

## Overview

Clean, professional implementation of dual Ollama backends with intelligent intent-based routing.

## Architecture

```
┌─────────────────┐    ┌─────────────────┐
│   GPU Server   │    │   CPU Server   │
│ (127.0.0.1:11434) │    │ (127.0.0.1:11435) │
└─────────┬───────┘    └─────────┬───────┘
          │                     │
          └──────────┬───────────┘
                     │
          ┌────────────▼─────────────┐
          │   Hybrid Router         │
          │  (smart selection)      │
          └────────────┬─────────────┘
                     │
          ┌────────────▼─────────────┐
          │    CogniHub API       │
          └──────────────────────────┘
```

## Key Features

### Intent-Based Routing
- `intent="fast"`: GPU-first, CPU fallback (interactive chat)
- `intent="heavy"`: CPU-first, GPU fallback (intensive tasks)

### Smart Health Monitoring
- Real-time backend health checks before routing
- Automatic failover on primary failure
- VRAM error detection with CPU pinning

### Auto-Affinity Learning
- Remembers successful backend per model (fast intent only)
- Uses learned preference for subsequent calls
- Heavy intent remains CPU-first deterministic

### Parallel Processing
- Both backends can serve concurrent requests
- No blocking between GPU and CPU workloads
- Optimal resource utilization

## Installation

### 1. SystemD Services

Copy the service files and enable:

```bash
# GPU backend (Vulkan enabled)
systemctl --user enable --now ollama-gpu@$USER.service

# CPU backend (GPU disabled)
systemctl --user enable --now ollama-cpu@$USER.service
```

### 2. Environment Configuration

```bash
export OLLAMA_GPU_URL=http://127.0.0.1:11434
export OLLAMA_CPU_URL=http://127.0.0.1:11435
export OLLAMA_VULKAN=1
export GGML_VK_VISIBLE_DEVICES=0
```

### 3. Verify Installation

```bash
# Check backend health
python src/cognihub/services/hybrid_router_clean.py --check

# Expected output
{
  "gpu": {
    "status": "healthy",
    "url": "http://127.0.0.1:11434",
    "is_gpu": true
  },
  "cpu": {
    "status": "healthy", 
    "url": "http://127.0.0.1:11435",
    "is_gpu": false
  }
}
```

## Usage Examples

### Basic Usage

```python
from cognihub.services.hybrid_router_clean import smart_chat

# Fast intent (GPU-first) - default
response = await smart_chat(
    model="llama3.1:latest",
    messages=[{"role": "user", "content": "Hello!"}]
)

# Heavy intent (CPU-first)
response = await smart_chat(
    model="codellama:13b",
    messages=[{"role": "user", "content": "Process large document"}],
    intent="heavy"
)
```

### Advanced Usage

```python
from cognihub.services.hybrid_router_clean import get_router

# Get router instance for advanced operations
router = await get_router()

# Check health manually
health = await router.health_check()
print(health)

# List available models
models = await router.list_models()
print(models)

# Direct backend access
primary, fallback = await router._choose_backend("llama3.1:latest", "fast")
print(f"Primary: {primary.name}, Fallback: {fallback.name if fallback else 'None'}")
```

### Tool Calling Integration

```python
# With tool calling support
response = await smart_chat(
    model="llama3.1:latest",
    messages=[{"role": "user", "content": "Search for AI news"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search web",
            "parameters": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"]
            }
        }
    }],
    intent="fast"
)
```

### Parallel Processing

```python
import asyncio

# Concurrent requests to both backends
fast_task = smart_chat(
    model="llama3.1:latest",
    messages=fast_messages,
    intent="fast"
)

heavy_task = smart_chat(
    model="codellama:13b", 
    messages=heavy_messages,
    intent="heavy"
)

# Process both simultaneously
response1, response2 = await asyncio.gather(fast_task, heavy_task)
```

## Error Handling

### Automatic Recovery
- GPU OOM errors automatically pin model to CPU
- Network failures trigger fallback to healthy backend
- Model not found errors try alternate backend
- Backend health status refreshed before each routing decision

### Error Classification
The router distinguishes between:
- VRAM/OOM: "out of memory", "vram", "insufficient memory"
- Network: "connection", "timeout", "network"
- Model: "not found", "format", "corrupt"

### Logging
All routing decisions and errors are logged:
- Backend selection reasoning
- Health check results
- Fallback triggers
- Model affinity changes

## Configuration Options

### Model Size Guidelines (32GB RAM)
- Fast lane: 1B-8B models (GPU optimal)
- Heavy lane: 13B-20B models (CPU viable)
- Avoid: 34B+ models (exceed 32GB even quantized)

### Environment Variables
```bash
# Backend URLs
OLLAMA_GPU_URL=http://127.0.0.1:11434
OLLAMA_CPU_URL=http://127.0.0.1:11435

# GPU Settings
OLLAMA_VULKAN=1
GGML_VK_VISIBLE_DEVICES=0

# CPU Settings
GGML_VK_VISIBLE_DEVICES=-1

# Performance
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_KEEP_ALIVE=30m
OLLAMA_NUM_PARALLEL=2
```

## Hardware Compatibility

### Supported GPUs
- NVIDIA: CUDA support via CUDA_VISIBLE_DEVICES
- AMD: Vulkan support via GGML_VK_VISIBLE_DEVICES
- Intel: Vulkan support via GGML_VK_VISIBLE_DEVICES

### GPU Memory Allocation
- Router detects available VRAM automatically
- Models routed based on memory requirements
- OOM detection triggers CPU fallback

## Performance Optimization

### Memory Management
- Automatic model unloading on OOM
- Configurable model limits per backend
- Smart caching based on usage patterns

### Request Routing
- Intent-based selection for optimal performance
- Health-aware routing to avoid failed backends
- Model affinity learning for consistent performance

## Monitoring

### Health Endpoints
```bash
# Real-time health status
python src/cognihub/services/hybrid_router_clean.py --check

# Model inventory per backend
python src/cognihub/services/hybrid_router_clean.py --models
```

### Metrics Collection
- Backend response times
- Error rates per backend
- Model distribution statistics
- Resource utilization tracking

## Best Practices

### For 32GB RAM Systems
- Use 1B-8B models for fast interactive chat
- Use 13B-20B models for heavy processing tasks
- Avoid models larger than 20B even when quantized
- Limit concurrent models on CPU backend

### Error Prevention
- Always check backend health before routing
- Use appropriate intent for workload type
- Monitor VRAM usage on GPU backend
- Set reasonable model size limits

### Performance Tuning
- Use fast intent for interactive workloads
- Use heavy intent for batch processing
- Enable model affinity for consistent routing
- Configure appropriate keep-alive settings

## Integration

### With Existing CogniHub Features
The hybrid router integrates seamlessly with:
- Tool calling (native Ollama format)
- RAG document retrieval
- Streaming responses
- Model validation
- Request/response logging

### API Integration
```python
# In FastAPI endpoint
from cognihub.services.hybrid_router_clean import smart_chat

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    response = await smart_chat(
        model=request.model,
        messages=request.messages,
        tools=request.tools,
        intent=getattr(request, 'intent', 'fast')
    )
    return {"response": response}
```

## Troubleshooting

### Common Issues
- GPU backend not starting: Check Vulkan drivers
- CPU backend OOM: Reduce model size or limit concurrency
- Routing always to GPU: Check intent parameter
- Model not found: Verify model availability on target backend

### Debug Commands
```bash
# Test routing directly
python -c "
import asyncio
from cognihub.services.hybrid_router_clean import get_router

async def test():
    router = get_router()
    primary, fallback = await router._choose_backend('llama3.1:latest', 'fast')
    print(f'Primary: {primary.name}, Fallback: {fallback.name if fallback else None}')

asyncio.run(test())
"
```

This production-ready hybrid system provides optimal resource utilization with intelligent routing, automatic failover, and comprehensive error handling.