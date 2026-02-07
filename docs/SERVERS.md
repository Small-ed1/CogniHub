# Server Management

All servers can be started in the background without monitoring using the `scripts/servers.sh` script.

## Usage

```bash
# Start all servers (FastAPI + Ollama)
./scripts/servers.sh start

# Stop all servers
./scripts/servers.sh stop

# Restart all servers
./scripts/servers.sh restart

# Check server status
./scripts/servers.sh status

# View logs
./scripts/servers.sh logs fastapi    # View FastAPI logs
./scripts/servers.sh logs ollama     # View Ollama logs
```

## Servers

- **FastAPI**: http://localhost:8000
- **Ollama**: http://localhost:11434

## Logs

Logs are written to:
- `logs/fastapi.log` - FastAPI server logs
- `logs/ollama.log` - Ollama server logs

## Process Management

The script manages PIDs automatically:
- `fastapi.pid` - FastAPI process ID
- `ollama.pid` - Ollama process ID

## Setup

1. Create a venv and install the workspace packages:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -U pip
   python -m pip install -e "packages/ollama_cli[dev]" -e "packages/contextharbor[dev]"
   ```

2. Pull an embedding model for RAG:
   ```bash
   ollama pull nomic-embed-text
   ```

3. Start servers:
   ```bash
   ./scripts/servers.sh start
   ```

## Notes

- Both servers run as background processes with nohup
- Logs are captured and can be viewed with `tail -f`
- Status can be checked anytime with `./servers.sh status`
- Servers are automatically stopped/restarted by the script
