#!/bin/bash
set -e

echo "ContextHarbor - Systemd Service Installation"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root (use sudo)"
    exit 1
fi

SERVICE_FILE="/etc/systemd/system/contextharbor.service"
SOURCE_SERVICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/systemd/contextharbor.service"

if [ ! -f "$SOURCE_SERVICE" ]; then
    echo "Error: contextharbor.service not found at: $SOURCE_SERVICE"
    exit 1
fi

echo "Installing systemd service..."
cp "$SOURCE_SERVICE" "$SERVICE_FILE"
chmod 644 "$SERVICE_FILE"

echo "Reloading systemd..."
systemctl daemon-reload

echo "Enabling contextharbor service..."
systemctl enable contextharbor

echo ""
echo "Installation complete!"
echo ""
echo "Commands to manage the service:"
echo "  sudo systemctl start contextharbor     # Start the service"
echo "  sudo systemctl stop contextharbor      # Stop the service"
echo "  sudo systemctl restart contextharbor   # Restart the service"
echo "  sudo systemctl status contextharbor    # Check status"
echo "  sudo journalctl -u contextharbor -f    # View logs"
echo ""
echo "Note: This unit expects a venv at %h/contextharbor/.venv and your repo checked out to %h/contextharbor"
echo "Note: Make sure Ollama is running (or install systemd/ollama-*.service separately)"
