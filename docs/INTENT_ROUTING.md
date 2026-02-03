# Intent-Based Hybrid Routing

CogniHub's hybrid router now supports **intent-based routing** for optimal resource utilization.

## Intent Types

### `intent="fast"` (default)
- **Purpose**: Interactive chat, quick responses
- **Routing**: GPU-first, CPU fallback
- **Use Cases**: User chat, simple tool calling, code completion

### `intent="heavy"` 
- **Purpose**: Long-running, resource-intensive tasks
- **Routing**: CPU-first, even if GPU available
- **Use Cases**: Document processing, large embeddings, batch operations

## Usage Examples

```python
from cognihub.services.hybrid_router import smart_chat

# Fast interactive chat (GPU-first)
response = await smart_chat(
    model="llama3.1:latest",
    messages=[{"role": "user", "content": "Hello!"}],
    intent="fast"  # or omit (default)
)

# Heavy processing task (CPU-first)  
response = await smart_chat(
    model="llama3.1:latest", 
    messages=[{"role": "user", "content": "Process this 10GB document"}],
    intent="heavy"
)
```

## Routing Logic

1. **Check affinity**: Previously successful backend for this model gets priority
2. **Health refresh**: Verify backend availability before routing
3. **Intent-based selection**:
   - `fast` → GPU if healthy, otherwise CPU
   - `heavy` → CPU if healthy, otherwise GPU
4. **Error classification**: GPU OOM/VRAM errors pin model to CPU
5. **Fallback handling**: Primary fails → try secondary backend

## Smart Features

### ✅ Auto-Affinity Learning
Router learns which backend works best per model:
```python
# After a successful call
router.model_affinity["llama3.1:latest"] = "gpu"  # Model prefers GPU

# Future calls automatically use GPU
response = await smart_chat(model="llama3.1:latest", ...)
```

### ✅ VRAM Error Detection  
GPU failures due to memory issues are detected and model is pinned to CPU:
```python
# Detects errors like: "out of memory", "CUDA error", "insufficient VRAM"
if router._is_vram_error(error):
    router.model_affinity[model] = "cpu"  # Pin to CPU
```

### ✅ Health Monitoring
Backends are health-checked before each routing decision:
```python
await router.refresh_health()  # Check all backend health
router._health  # Dict of backend status
```

## Parallel Processing

Both backends can handle simultaneous requests:
```python
import asyncio

# Concurrent fast chat (GPU) + heavy task (CPU)
fast_task = smart_chat(model="llama3.1:latest", messages=fast_msgs, intent="fast")
heavy_task = smart_chat(model="llama3.1:latest", messages=heavy_msgs, intent="heavy")

response1, response2 = await asyncio.gather(fast_task, heavy_task)
```

## Configuration

### Environment Variables
```bash
export OLLAMA_GPU_URL=http://127.0.0.1:11434    # GPU backend
export OLLAMA_CPU_URL=http://127.0.0.1:11435    # CPU backend
```

### Backend Management
```bash
# Check health
python src/cognihub/services/hybrid_router.py --check

# List models per backend  
python src/cognihub/services/hybrid_router.py --models
```

## Best Practices

### For 32GB RAM Systems
- **Fast intent**: 7B-8B models → GPU
- **Heavy intent**: 13B-20B models → CPU  
- **Avoid**: 34B+ models (require >32GB even when quantized)

### Error Recovery
- **GPU OOM** → Model auto-pins to CPU
- **Backend down** → Automatic failover
- **Model not found** → Try other backend

This intent system gives you **fine-grained control** over resource usage while maintaining **automatic fallback capabilities**! 🎯