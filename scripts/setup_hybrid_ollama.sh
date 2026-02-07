#!/bin/bash
# Hybrid Ollama Setup Script
# Sets up GPU and CPU instances with smart configuration

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_HOME="$HOME"

echo "🚀 Setting up Hybrid Ollama Infrastructure..."

# Create systemd user directory
mkdir -p "$USER_HOME/.config/systemd/user"

# Install service files
cp "$SCRIPT_DIR/../systemd/ollama-gpu@.service" "$USER_HOME/.config/systemd/user/"
cp "$SCRIPT_DIR/../systemd/ollama-cpu@.service" "$USER_HOME/.config/systemd/user/"

# Reload systemd
systemctl --user daemon-reload

# Detect GPU and setup appropriate services
echo "🔍 Detecting hardware..."

# Check for NVIDIA GPU
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    echo "✅ NVIDIA GPU detected"
    GPU_SERVICE="ollama-gpu@$USER.service"
else
    echo "⚠️  No NVIDIA GPU detected"
    GPU_SERVICE=""
fi

# Check for AMD/Intel Vulkan support
if command -v vulkaninfo >/dev/null 2>&1 && vulkaninfo --summary >/dev/null 2>&1; then
    echo "✅ Vulkan GPU support detected (AMD/Intel)"
    if [ -z "$GPU_SERVICE" ]; then
        GPU_SERVICE="ollama-gpu@$USER.service"
    fi
else
    echo "⚠️  No Vulkan GPU support detected"
fi

# Calculate memory allocation
TOTAL_RAM=$(free -g | awk '/^Mem:/{print $2}')
CPU_MAX=$((TOTAL_RAM / 2))  # Use half of system RAM for CPU backend

echo "💾 System RAM: ${TOTAL_RAM}GB (CPU backend max: ${CPU_MAX}GB)"

# Start services
if [ -n "$GPU_SERVICE" ]; then
    echo "🎮 Starting GPU backend..."
    systemctl --user enable --now "$GPU_SERVICE"
    
    # Wait for GPU backend to start
    echo "⏳ Waiting for GPU backend..."
    sleep 5
    
    # Test GPU backend
    if curl -s http://127.0.0.1:11434/api/tags >/dev/null; then
        echo "✅ GPU backend started successfully"
    else
        echo "❌ GPU backend failed to start"
    fi
fi

echo "🖥️  Starting CPU backend..."
systemctl --user enable --now "ollama-cpu@$USER.service"

# Wait for CPU backend to start
echo "⏳ Waiting for CPU backend..."
sleep 5

# Test CPU backend
if curl -s http://127.0.0.1:11435/api/tags >/dev/null; then
    echo "✅ CPU backend started successfully"
else
    echo "❌ CPU backend failed to start"
fi

echo ""
echo "🎯 Setup Summary:"
echo "   GPU Backend:  http://127.0.0.1:11434 ${GPU_SERVICE:+(✅ Running)} ${GPU_SERVICE:-❌ Unavailable}"
echo "   CPU Backend:  http://127.0.0.1:11435 (✅ Running)"
echo "   Max CPU Model Size: ${CPU_MAX}GB"
echo ""
echo "🔧 Usage in ContextHarbor:"
echo "   export OLLAMA_GPU_URL=http://127.0.0.1:11434"
echo "   export OLLAMA_CPU_URL=http://127.0.0.1:11435"
echo ""
echo "📊 Check status:"
echo "   python3 $SCRIPT_DIR/../packages/contextharbor/src/contextharbor/services/hybrid_router.py --check"
