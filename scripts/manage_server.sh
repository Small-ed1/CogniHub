#!/bin/bash
# ContextHarbor Server Management Script

PID_FILE="/tmp/router_server.pid"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$APP_DIR/logs"
LOG_FILE="$LOG_DIR/server.log"

mkdir -p "$LOG_DIR"

venv_python() {
    if [ -x "$APP_DIR/.venv/bin/python" ]; then
        echo "$APP_DIR/.venv/bin/python"
        return
    fi
    if [ -x "$APP_DIR/venv/bin/python" ]; then
        echo "$APP_DIR/venv/bin/python"
        return
    fi
    echo "python3"
}

start_server() {
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "Server is already running (PID: $(cat $PID_FILE))"
        return 1
    fi

    echo "Starting ContextHarbor server..."
    local py
    py="$(venv_python)"
    cd "$APP_DIR"
    nohup "$py" -m uvicorn contextharbor.app:app --host 0.0.0.0 --port 8003 > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 2

    if curl -s http://localhost:8003/health | grep -q '"ok":true'; then
        echo "Server started successfully on http://localhost:8003"
        echo "PID: $(cat $PID_FILE)"
    else
        echo "Server failed to start. Check logs: $LOG_FILE"
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_server() {
    if [ ! -f "$PID_FILE" ]; then
        echo "No PID file found. Server may not be running."
        return 1
    fi

    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping server (PID: $PID)..."
        kill "$PID"
        sleep 2

        if kill -0 "$PID" 2>/dev/null; then
            echo "Force killing server..."
            kill -9 "$PID"
        fi

        rm -f "$PID_FILE"
        echo "Server stopped"
    else
        echo "Server process not found"
        rm -f "$PID_FILE"
    fi
}

status_server() {
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        PID=$(cat "$PID_FILE")
        echo "Server is running (PID: $PID)"
        echo "🌐 URL: http://localhost:8003"

        # Test health
        if curl -s http://localhost:8003/health | grep -q '"ok":true'; then
            echo "🏥 Health: OK"
        else
            echo "🏥 Health: FAILED"
        fi
    else
        echo "Server is not running"
        [ -f "$PID_FILE" ] && rm -f "$PID_FILE"
    fi
}

case "$1" in
    start)
        start_server
        ;;
    stop)
        stop_server
        ;;
    restart)
        stop_server
        sleep 1
        start_server
        ;;
    status)
        status_server
        ;;
    logs)
        if [ -f "$LOG_FILE" ]; then
            tail -f "$LOG_FILE"
        else
            echo "No log file found"
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the server"
        echo "  stop    - Stop the server"
        echo "  restart - Restart the server"
        echo "  status  - Show server status"
        echo "  logs    - Show server logs"
        exit 1
        ;;
esac
