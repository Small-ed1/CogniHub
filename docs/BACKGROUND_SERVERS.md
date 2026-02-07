# Background Server Management

All servers can run in the background without active monitoring. Two options are available:

## Option 1: Manual Control (Recommended for Development)

Use the `scripts/servers.sh` script for full manual control:

```bash
# Start all servers
./scripts/servers.sh start

# Stop all servers
./scripts/servers.sh stop

# Restart all servers
./scripts/servers.sh restart

# Check status
./scripts/servers.sh status

# View logs
./scripts/servers.sh logs fastapi
./scripts/servers.sh logs ollama
```

**Features:**
- Simple bash script with no dependencies
- PID tracking and clean shutdown
- Log files (fastapi.log, ollama.log)
- Health checks on startup
- Easy status monitoring

## Option 2: Systemd Service (Production)

Install as systemd service for automatic startup:

```bash
 sudo ./scripts/install-service.sh

# Then manage with systemctl:
sudo systemctl start contextharbor
sudo systemctl stop contextharbor
sudo systemctl status contextharbor
sudo journalctl -u contextharbor -f
```

**Features:**
- Automatic startup on boot
- Automatic restart on failure
- Managed by system init
- Integrated with system logs

## Current Server Status

Both servers are currently running:

- **FastAPI**: http://localhost:8000 (PID tracked)
- **Ollama**: http://localhost:11434 (PID tracked)

## Log Files

- `logs/fastapi.log` - FastAPI server output
- `logs/ollama.log` - Ollama server output

View logs anytime:
```bash
tail -f logs/fastapi.log
tail -f logs/ollama.log
```

## Quick Start

1. Ensure dependencies are installed:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -U pip
   python -m pip install -e "packages/ollama_cli[dev]" -e "packages/contextharbor[dev]"
   ```

2. Pull embedding model for RAG:
   ```bash
   ollama pull nomic-embed-text
   ```

3. Start servers:
   ```bash
   ./scripts/servers.sh start
   ```

4. Access the app: http://localhost:8000

## Notes

- Both options run servers completely in background
- No need to monitor terminal or keep windows open
- Logs are captured and can be viewed anytime
- Processes are tracked and can be stopped cleanly
