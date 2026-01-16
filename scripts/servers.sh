#!/bin/bash
set -e

APP_DIR="/home/small_ed/router_phase1"
FASTAPI_PID_FILE="$APP_DIR/fastapi.pid"
OLLAMA_PID_FILE="$APP_DIR/ollama.pid"
FASTAPI_LOG="$APP_DIR/fastapi.log"
OLLAMA_LOG="$APP_DIR/ollama.log"

cd "$APP_DIR"

kill_pidfile() {
    local pidfile="$1"
    local name="$2"
    if [ -f "$pidfile" ]; then
        local pid
        pid="$(cat "$pidfile" 2>/dev/null || true)"
        if [ -n "$pid" ] && ps -p "$pid" >/dev/null 2>&1; then
            echo "Stopping $name (PID: $pid)"
            kill "$pid" || true
            sleep 1
            ps -p "$pid" >/dev/null 2>&1 && kill -9 "$pid" || true
        fi
        rm -f "$pidfile"
    fi
}

kill_existing() {
    kill_pidfile "$FASTAPI_PID_FILE" "FastAPI"
    kill_pidfile "$OLLAMA_PID_FILE" "Ollama"
}

start_ollama() {
    echo "Starting Ollama..."
    nohup ollama serve > "$OLLAMA_LOG" 2>&1 &
    OLLAMA_PID=$!
    echo "$OLLAMA_PID" > "$OLLAMA_PID_FILE"
    echo "Ollama started (PID: $OLLAMA_PID), logging to $OLLAMA_LOG"
}

start_fastapi() {
    echo "Starting FastAPI..."
    source venv/bin/activate
    nohup uvicorn app:app --host 0.0.0.0 --port 8000 > "$FASTAPI_LOG" 2>&1 &
    FASTAPI_PID=$!
    echo "$FASTAPI_PID" > "$FASTAPI_PID_FILE"
    echo "FastAPI started (PID: $FASTAPI_PID), logging to $FASTAPI_LOG"
}

wait_for_ollama() {
    echo "Waiting for Ollama to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:11434/api/version > /dev/null 2>&1; then
            echo "Ollama is ready!"
            return 0
        fi
        sleep 1
    done
    echo "Ollama failed to start in time. Check $OLLAMA_LOG"
    return 1
}

wait_for_fastapi() {
    echo "Waiting for FastAPI to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            echo "FastAPI is ready!"
            return 0
        fi
        sleep 1
    done
    echo "FastAPI failed to start in time. Check $FASTAPI_LOG"
    return 1
}

case "$1" in
    start)
        echo "Starting all servers..."
        kill_existing
        start_ollama
        wait_for_ollama
        start_fastapi
        wait_for_fastapi
        echo ""
        echo "All servers started successfully!"
        echo "FastAPI: http://localhost:8000"
        echo "Ollama: http://localhost:11434"
        echo ""
        echo "View logs:"
        echo "  FastAPI: tail -f $FASTAPI_LOG"
        echo "  Ollama:  tail -f $OLLAMA_LOG"
        ;;
    stop)
        echo "Stopping all servers..."
        kill_existing
        echo "All servers stopped."
        ;;
    restart)
        $0 stop
        sleep 2
        $0 start
        ;;
    status)
        echo "Server status:"
        if [ -f "$FASTAPI_PID_FILE" ]; then
            PID=$(cat "$FASTAPI_PID_FILE")
            if ps -p "$PID" > /dev/null 2>&1; then
                echo "FastAPI: RUNNING (PID: $PID)"
            else
                echo "FastAPI: NOT RUNNING (stale PID file)"
            fi
        else
            echo "FastAPI: NOT RUNNING"
        fi

        if [ -f "$OLLAMA_PID_FILE" ]; then
            PID=$(cat "$OLLAMA_PID_FILE")
            if ps -p "$PID" > /dev/null 2>&1; then
                echo "Ollama: RUNNING (PID: $PID)"
            else
                echo "Ollama: NOT RUNNING (stale PID file)"
            fi
        else
            echo "Ollama: NOT RUNNING"
        fi
        ;;
    logs)
        case "$2" in
            fastapi|api)
                tail -f "$FASTAPI_LOG"
                ;;
            ollama)
                tail -f "$OLLAMA_LOG"
                ;;
            *)
                echo "Usage: $0 logs {fastapi|ollama}"
                exit 1
                ;;
        esac
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  start    - Start all servers in background"
        echo "  stop     - Stop all servers"
        echo "  restart  - Restart all servers"
        echo "  status   - Show server status"
        echo "  logs     - View logs (fastapi|ollama)"
        exit 1
        ;;
esac
