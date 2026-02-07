# ContextHarbor Hybrid CPU/GPU Inference

## Overview

ContextHarbor now supports **dual inference backends** for optimal resource utilization:

- **GPU Backend** (port 11434): Fast inference for smaller models
- **CPU Backend** (port 11435): Large model support + fallback

## Architecture

```
┌─────────────────┐    ┌─────────────────┐
│   GPU Server   │    │   CPU Server   │
│ (127.0.0.1:11434) │    │ (127.0.0.1:11435) │
└─────────┬───────┘    └─────────┬───────┘
          │                      │
          └──────────┬───────────┘
                     │
          ┌────────────▼─────────────┐
          │   Hybrid Router         │
          │  (smart selection)      │
          └────────────┬─────────────┘
                     │
          ┌────────────▼─────────────┐
          │  ContextHarbor API    │
          └──────────────────────────┘
```

## Features

### ✅ Smart Model Routing
- **Small models** (< 8GB): GPU first
- **Large models** (> 8GB): CPU first  
- **GPU failures**: Auto-fallback to CPU
- **VRAM detection**: Automatic capacity calculation

### ✅ Parallel Processing
- Concurrent requests to different backends
- No blocking between GPU and CPU workloads
- Optimal resource utilization

### ✅ Robust Fallback
- GPU driver issues → CPU automatically
- Model too large for VRAM → CPU
- Backend crash → healthy backend takeover

## Setup

### 1. Install Dependencies

```bash
# NVIDIA GPU support
sudo pacman -S nvidia-utils nvidia-settings

# AMD/Intel Vulkan support  
sudo pacman -S vulkan-tools vulkan-icd-loader

# Ollama (if not installed)
sudo pacman -S ollama
```

### 2. Run Setup Script

```bash
# Automatic setup and service startup
./scripts/setup_hybrid_ollama.sh
```

### 3. Manual Setup (Optional)

```bash
# GPU service
systemctl --user enable --now ollama-gpu@$USER.service

# CPU service  
systemctl --user enable --now ollama-cpu@$USER.service

# Check status
systemctl --user status ollama-gpu@$USER
systemctl --user status ollama-cpu@$USER
```

## Usage

### Environment Variables
```bash
export OLLAMA_GPU_URL=http://127.0.0.1:11434
export OLLAMA_CPU_URL=http://127.0.0.1:11435
```

### API Usage

```python
from contextharbor.services.hybrid_router import smart_chat

# Automatic backend selection
response = await smart_chat(
    model="llama3.1:8b",  # Goes to GPU
    messages=[{"role": "user", "content": "Hello!"}]
)

# Large model → CPU
response = await smart_chat(
    model="llama3.1:70b",  # Goes to CPU
    messages=[{"role": "user", "content": "Complex task"}]
)

# Tool calling with hybrid routing
response = await smart_chat(
    model="llama3.1:8b",
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
    }]
)
```

## Model Size Estimates

| Model | Estimated GB | Recommended Backend |
|--------|-------------|-------------------|
| llama3.2:1b | 1GB | GPU |
| llama3.2:3b | 2GB | GPU |
| llama3.1:8b | 6GB | GPU |
| llama3.2:11b | 8GB | GPU |
| llama3.1:70b | 42GB | CPU |
| qwen2.5:32b | 20GB | CPU |
| mixtral:8x22b | 65GB | CPU |

## Monitoring

### Check Backend Health
```bash
# Check all backends
python packages/contextharbor/src/contextharbor/services/hybrid_router.py --check

# Expected output
{
  "gpu": {
    "status": "healthy",
    "version": "0.14.3", 
    "url": "http://127.0.0.1:11434",
    "max_memory_gb": 12,
    "is_gpu": true
  },
  "cpu": {
    "status": "healthy",
    "version": "0.14.3",
    "url": "http://127.0.0.1:11435", 
    "max_memory_gb": 16,
    "is_gpu": false
  }
}
```

### List Available Models
```bash
# Models per backend
python packages/contextharbor/src/contextharbor/services/hybrid_router.py --models

# Output
{
  "gpu": ["llama3.1:8b", "llama3.2:3b"],
  "cpu": ["llama3.1:70b", "qwen2.5:32b"]
}
```

## Configuration

### GPU Control
```bash
# Disable GPU (force CPU)
export GGML_VK_VISIBLE_DEVICES=-1

# Pin specific GPU (NVIDIA)
export CUDA_VISIBLE_DEVICES=0

# Pin specific GPU (Vulkan)
export GGML_VK_VISIBLE_DEVICES=0
```

### Memory Limits
```bash
# Limit concurrent models
export OLLAMA_MAX_LOADED_MODELS=2

# Set keep-alive (reduces loading time)
export OLLAMA_KEEP_ALIVE=30m
```

## Troubleshooting

### GPU Backend Not Starting
```bash
# Check GPU detection
nvidia-smi  # NVIDIA
vulkaninfo --summary  # AMD/Intel

# Force CPU mode
systemctl --user stop ollama-gpu@$USER
```

### Model Too Large for GPU
```bash
# Router will automatically fall back to CPU
# Check logs for routing decisions

# Override routing manually
export OLLAMA_GPU_URL=""  # Force CPU only
```

### Performance Tuning
```bash
# CPU threads
export OLLAMA_NUM_PARALLEL=4

# GPU memory optimization
export OLLAMA_GPU_OVERHEAD=0

# Context size
export OLLAMA_CONTEXT_LENGTH=4096
```

## Integration with ContextHarbor

The hybrid router integrates seamlessly with existing ContextHarbor features:

- ✅ **Tool calling**: Native Ollama tools with smart routing
- ✅ **RAG**: Document retrieval with optimal backend
- ✅ **Streaming**: Real-time responses from best backend
- ✅ **Research**: Complex tasks with automatic model selection

### Web Interface Integration
```python
# In app.py - replace direct ollama calls
from contextharbor.services.hybrid_router import smart_chat

# Chat endpoint automatically uses hybrid routing
response = await smart_chat(model, messages, tools=tools)
```

## Benefits

1. **Performance**: GPU for speed when possible
2. **Capacity**: CPU for large models
3. **Reliability**: Automatic fallback on failures
4. **Scalability**: Parallel concurrent requests
5. **Flexibility**: Manual override options
6. **Monitoring**: Health checks and metrics

## Advanced Usage

### Custom Routing Rules
```python
# Override model size estimates
router.model_sizes.update({
    "my_custom_model": 15,  # Force CPU for 15GB model
})
```

### Backend Priority
```python
# Custom backend selection logic
primary, fallback = router._select_backend("model_name")
print(f"Primary: {primary.name}, Fallback: {fallback}")
```

This hybrid system gives you the **best of both worlds**: GPU speed when available, CPU capacity when needed, all with automatic intelligent routing.
