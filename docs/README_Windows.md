# CogniHub - Windows Setup

This guide explains how to run CogniHub on Windows.

## Prerequisites

- Python 3.8+ installed
- Ollama installed (download from https://ollama.ai/)
- Git (optional, for cloning)

## Installation

1. Clone or download the repository
2. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Install Ollama and pull required models:
   ```
   ollama pull llama3.1
   ollama pull embeddinggemma
   ```

## Running the Application

### Option 1: Using PowerShell Scripts (Recommended)

1. Start servers:
   ```
   .\scripts\servers.ps1 start
   ```

2. Run TUI:
   ```
   .\scripts\run_tui.ps1
   ```

3. Stop servers:
   ```
   .\scripts\servers.ps1 stop
   ```

### Option 2: Using Batch Scripts

1. Start servers:
   ```
   scripts\servers.bat start
   ```

2. Run TUI:
   ```
   scripts\run_tui.bat
   ```

3. Stop servers:
   ```
   scripts\servers.bat stop
   ```

### Option 2: Manual Start

1. Start Ollama:
   ```
   ollama serve
   ```

2. Start FastAPI (in another terminal):
   ```
   uvicorn app:app --host 0.0.0.0 --port 8000
   ```

3. Open web UI at http://localhost:8000

4. Or run TUI:
    ```
    python src/cognihub/tui/cognihub_tui.py
    ```

## PowerShell Script Commands

- `.\scripts\servers.ps1 start` - Start Ollama and FastAPI
- `.\scripts\servers.ps1 stop` - Stop servers
- `.\scripts\servers.ps1 restart` - Restart servers
- `.\scripts\servers.ps1 status` - Show server status
- `.\scripts\servers.ps1 logs fastapi` - View FastAPI logs
- `.\scripts\servers.ps1 logs ollama` - View Ollama logs

## Batch Script Commands (Alternative)

- `scripts\servers.bat start` - Start Ollama and FastAPI
- `scripts\servers.bat stop` - Stop servers
- `scripts\servers.bat restart` - Restart servers
- `scripts\servers.bat status` - Show server status
- `scripts\servers.bat logs fastapi` - View FastAPI logs
- `scripts\servers.bat logs ollama` - View Ollama logs

## Directory Structure

- `src/` - Python source code
- `src/cognihub/static/` - Static web files
- `~/.cognihub/data/` - SQLite databases (created automatically)
- `docs/` - Documentation
- `scripts/` - Batch scripts

## Troubleshooting

- If ports are in use, change them in the scripts or environment variables
- Logs are in `logs/` directory
- Databases are in `data/` directory

## Environment Variables

You can set these to customize behavior:
- `OLLAMA_URL` - Ollama API URL (default: http://127.0.0.1:11434)
- `CHAT_DB` - Chat database path (default: data/chat.sqlite3)
- `RAG_DB` - RAG database path (default: data/rag.sqlite3)
- etc.