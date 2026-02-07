# ContextHarbor Hybrid CPU/GPU Inference - Production Ready

## Overview

Clean, professional implementation of dual Ollama backends with intelligent intent-based routing.

## Key Components

### 1. Hybrid Router (`packages/contextharbor/src/contextharbor/services/hybrid_router.py`)
- **Intent-based routing**: `fast` (GPU-first) or `heavy` (CPU-first)
- **Smart health monitoring**: Real-time backend status checks
- **Auto-affinity learning**: Remembers successful backend per model (fast intent only)
- **VRAM error detection**: Auto-pins models to CPU on GPU OOM
- **Graceful fallback**: Primary fails → secondary backend
- **Parallel processing**: Both backends can serve concurrent requests
- **Professional logging**: Clean error handling and routing decisions

### 2. SystemD Services
- **GPU service**: Port 11434, Vulkan enabled
- **CPU service**: Port 11435, GPU disabled
- **Auto-restart**: Both backends restart on failure
- **User-scoped**: Per-user service management

## Routing Strategy

### Intent Types

#### `intent="fast"` (default)
- **Purpose**: Interactive chat, quick responses, tool calling
- **Routing**: GPU-first, CPU fallback
- **Use Cases**: User chat, code completion, simple tools
- **Affinity**: Learns which backend works best per model

#### `intent="heavy"`
- **Purpose**: Long-running, resource-intensive tasks
- **Routing**: CPU-first, GPU fallback
- **Use Cases**: Document processing, large embeddings, batch operations
- **Affinity**: No affinity (deterministic CPU-first)

## Smart Features

### Health Monitoring
- Backend health checked before each routing decision
- Real-time status updates
- Automatic detection of backend failures
- Error classification (VRAM vs network vs model)

### Error Recovery
- GPU OOM automatically pins model to CPU for future requests
- Network failures trigger fallback to healthy backend
- Model not found tries alternate backend
- All routing decisions logged for debugging

### Performance Optimization
- Parallel request handling
- Model affinity learning
- Smart backend selection based on intent
- Configurable model limits
- Memory-aware routing

## Usage Examples

### Basic Usage

```python
from contextharbor.services.hybrid_router import smart_chat

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
from contextharbor.services.hybrid_router import get_router

# Get router for advanced operations
router = await get_router()

# Health check
health = await router.health_check()
print(health)

# Model inventory
models = await router.list_models()
print(models)

# Direct backend access
primary, fallback = await router._choose_backend("llama3.1:latest", "fast")
print(f"Primary: {primary.name}")
```

### Tool Calling Support

```python
# Full tool calling with hybrid routing
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

## Configuration

### Environment Variables

```bash
# Backend URLs
export OLLAMA_GPU_URL=http://127.0.0.1:11434
export OLLAMA_CPU_URL=http://127.0.0.1:11435

# GPU Settings
export OLLAMA_VULKAN=1
export GGML_VK_VISIBLE_DEVICES=0

# CPU Settings  
export GGML_VK_VISIBLE_DEVICES=-1

# Performance
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_KEEP_ALIVE=30m
export OLLAMA_NUM_PARALLEL=2
```

### SystemD Commands

```bash
# Install and start services
systemctl --user daemon-reload
systemctl --user enable --now ollama-gpu@$USER.service
systemctl --user enable --now ollama-cpu@$USER.service

# Check status
systemctl --user status ollama-gpu@$USER.service
systemctl --user status ollama-cpu@$USER.service
```

## Hardware Compatibility

### Supported GPUs
- **NVIDIA**: CUDA support via `CUDA_VISIBLE_DEVICES`
- **AMD**: Vulkan support via `GGML_VK_VISIBLE_DEVICES`
- **Intel**: Vulkan support via `GGML_VK_VISIBLE_DEVICES`

### Model Size Recommendations (32GB RAM)
- **Fast lane (GPU)**: 1B-8B models
- **Heavy lane (CPU)**: 13B-20B models
- **Avoid**: 34B+ models (exceed 32GB even quantized)

## Error Handling

### Automatic Recovery
- **GPU OOM**: Model auto-pinned to CPU
- **Backend failure**: Automatic fallback
- **Network issues**: Retry with alternate backend
- **Model not found**: Try other backend

### Error Classification
Distinguishes between:
- **VRAM/OOM**: "out of memory", "vram", "insufficient memory"
- **Network**: "connection", "timeout", "network"  
- **Model**: "not found", "format", "corrupt"
- **Driver**: "cuda", "vulkan", "cublas", "hip"

## Monitoring

### Health Endpoints

```bash
# Check all backends
python packages/contextharbor/src/contextharbor/services/hybrid_router.py --check

# Expected output
{
  "gpu": {
    "status": "healthy",
    "version": "0.14.3",
    "url": "http://127.0.0.1:11434",
    "is_gpu": true
  },
  "cpu": {
    "status": "healthy", 
    "version": "0.14.3",
    "url": "http://127.0.0.1:11435",
    "is_gpu": false
  }
}
```

### Model Inventory

```bash
# List models per backend
python packages/contextharbor/src/contextharbor/services/hybrid_router.py --models
```

## Best Practices

### For 32GB RAM Systems
- Use `llama3.1:latest` (8B) for fast interactive chat
- Use `codellama:13b` (13B) for heavy processing tasks
- Avoid models larger than 20B even when quantized
- Limit concurrent models on CPU backend
- Use fast intent for interactive workloads
- Use heavy intent for batch processing

### Performance Tuning
- Enable model affinity learning
- Set appropriate keep-alive values
- Monitor backend health regularly
- Use intent-based routing for optimal performance

### Error Prevention
- Always check backend health before routing
- Use appropriate intent for workload type
- Monitor VRAM usage on GPU backend
- Set reasonable model size limits
- Enable proper GPU driver support

## Integration

### With ContextHarbor Features
The hybrid router integrates seamlessly with:
- **Native tool calling** (Ollama format)
- **RAG document retrieval**
- **Streaming responses**
- **Model validation**
- **Request/response logging**

### API Integration
```python
# In FastAPI endpoint
from contextharbor.services.hybrid_router import smart_chat

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

## Benefits

1. **Performance**: GPU acceleration when available
2. **Reliability**: Automatic CPU fallback
3. **Flexibility**: Intent-based routing
4. **Scalability**: Parallel processing
5. **Monitoring**: Real-time health checks
6. **Recovery**: Automatic error handling
7. **Optimization**: Model affinity learning

This production-ready hybrid system provides optimal resource utilization with intelligent routing, automatic failover, and comprehensive error handling.
