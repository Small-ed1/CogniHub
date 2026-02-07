# Quick Reference - Background Servers

## Server Management Script

```bash
./scripts/servers.sh start    # Start all servers
./scripts/servers.sh stop     # Stop all servers
./scripts/servers.sh restart  # Restart all servers
./scripts/servers.sh status   # Check status
./scripts/servers.sh logs fastapi   # View FastAPI logs
./scripts/servers.sh logs ollama    # View Ollama logs
```

## Systemd Service (Optional)

```bash
sudo ./scripts/install-service.sh    # Install service
sudo systemctl start contextharbor
sudo systemctl stop contextharbor
sudo systemctl status contextharbor
sudo journalctl -u contextharbor -f
```

## Access

- App: http://localhost:8000
- Ollama API: http://localhost:11434

## Logs

- FastAPI: `tail -f logs/fastapi.log`
- Ollama: `tail -f logs/ollama.log`

Paths:
- `logs/fastapi.log`
- `logs/ollama.log`

## Current Status

Both servers running in background with PID tracking.
