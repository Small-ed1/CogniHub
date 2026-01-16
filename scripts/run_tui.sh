#!/bin/bash
cd "$(dirname "$(readlink -f "$0")")"

# Check if API is running
if ! curl -sf http://127.0.0.1:8000/health 2>/dev/null; then
    echo "Warning: API server may not be running."
    echo "Start with: sudo systemctl start router_phase1"
    echo "Or run manually: python3 app.py"
    echo ""
fi

# Activate venv and run TUI
if [ -d "venv" ]; then
    source venv/bin/activate
    python3 router_tui.py
else
    echo "Virtual environment not found. Run: python3 router_tui.py"
fi
