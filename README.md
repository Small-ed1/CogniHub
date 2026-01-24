# CogniHub

A local-first AI assistant with chat, RAG, and deep research capabilities. Built with FastAPI, SQLite, and integrated with Ollama for local model execution.

## Features

- **Web Interface**: Modern chat UI with sidebar navigation, settings panel, and real-time updates
- **Chat Management**: Create, rename, archive, pin, and search through conversations
- **RAG System**: Document upload and retrieval-augmented generation for enhanced responses
- **Deep Research**: Multi-round research with web scraping, claim verification, and synthesis
- **Model Integration**: Auto-model selection, Ollama integration, and multiple model support
- **Terminal UI**: Textual-based TUI for console usage
- **Kiwix Integration**: Offline Wikipedia access through Kiwix server
- **Settings Management**: Per-chat settings for model, temperature, context, and more

## Tool Agent

For advanced interactions with Ollama using tool-calling, run the included agent:

```bash
./scripts/run_agent.sh
```

This provides a CLI interface with web search, document search, and safe terminal execution tools.
It expects the FastAPI server to be running and uses `API_BASE` (default `http://localhost:8000`).

## Quick Start

### Prerequisites

- Python 3.8+
- [Ollama](https://ollama.ai/) installed and running
- Required models: `llama3.1` and `embeddinggemma`

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/Small-ed1/CogniHub
   cd CogniHub
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Pull required Ollama models**
   ```bash
   ollama pull llama3.1
   ollama pull embeddinggemma
   ```

### Running

#### Option 1: Web Interface (Recommended)

```bash
# Start the server
uvicorn src.cognihub.app:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 in your browser.

#### Option 2: Terminal UI

```bash
python src/cognihub/tui/cognihub_tui.py
```

#### Option 3: Production Deployment

```bash
# Install systemd services
sudo cp systemd/cognihub.service /etc/systemd/system/
sudo cp systemd/kiwix.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cognihub kiwix
sudo systemctl start cognihub kiwix
```

## Architecture

### Backend (FastAPI)

- **Main Application**: `src/cognihub/app.py` - FastAPI server with all endpoints
- **Database Modules**:
  - `src/cognihub/stores/chatstore.py` - Chat and message management
  - `src/cognihub/stores/ragstore.py` - Document storage and embeddings
  - `src/cognihub/stores/webstore.py` - Web page caching and chunking
  - `src/cognihub/stores/researchstore.py` - Research run tracking and claims
- **Configuration**: `src/cognihub/config.py` - Environment variable handling

### Frontend

- **Web UI**: `static/index.html`, `static/app.js`, `static/styles.css`
- **Terminal UI**: `cognihub_tui.py` (Textual framework)

### Data Storage

- **SQLite Databases**:
  - `chat.sqlite3` - Conversations and messages
  - `rag.sqlite3` - Document embeddings and chunks
  - `web.sqlite3` - Web page cache
  - `research.sqlite3` - Research runs and results

## API Endpoints

### Chat Management
- `GET /api/chats` - List chats
- `POST /api/chats` - Create new chat
- `GET /api/chats/{id}` - Get chat details
- `PATCH /api/chats/{id}` - Update chat settings
- `DELETE /api/chats/{id}` - Delete chat

### Messages
- `POST /api/chats/{id}/append` - Add messages
- `POST /api/chats/{id}/clear` - Clear chat history
- `GET /api/chats/{id}/search` - Search messages

### RAG System
- `POST /api/docs/upload` - Upload documents
- `GET /api/docs` - List documents
- `DELETE /api/docs/{id}` - Delete document

### Research
- `POST /api/research` - Start research task
- `GET /api/research/{run_id}` - Get research status
- `GET /api/research/{run_id}/sources` - Get research sources

### Models & Status
- `GET /api/models` - List available Ollama models
- `GET /api/status` - Check Ollama status
- `GET /health` - Health check endpoint

## Configuration

### Environment Variables

```bash
# Ollama Configuration
OLLAMA_URL=http://127.0.0.1:11434
EMBED_MODEL=embeddinggemma
DEFAULT_CHAT_MODEL=llama3.1

# Database Paths
CHAT_DB=chat.sqlite3
RAG_DB=rag.sqlite3
WEB_DB=web.sqlite3

# Upload & Security
MAX_UPLOAD_BYTES=10485760
API_KEY=your-secret-key  # Optional API key protection

# Research Models (Optional)
RESEARCH_PLANNER_MODEL=llama3.1
RESEARCH_VERIFIER_MODEL=llama3.1
RESEARCH_SYNTH_MODEL=llama3.1
```

### Web Scraping Protection

```bash
# SSRF Protection
WEB_ALLOWED_HOSTS=example.com,trusted.org
WEB_BLOCKED_HOSTS=malicious.com
WEB_UA=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36
```

## Development

### Testing

```bash
# Run pytest suite
python -m pytest tests/ -v
```

### Code Quality

```bash
# Type checking
mypy src/cognihub/ --ignore-missing-imports

# Syntax validation
python -m py_compile src/cognihub/app.py src/cognihub/stores/*.py src/cognihub/services/*.py

# Import testing
python -c "import sys; sys.path.insert(0, 'src'); import cognihub.app, cognihub.stores.chatstore, cognihub.stores.ragstore; print('All imports successful')"
```

### Database Operations

```bash
# Check database integrity
sqlite3 chat.sqlite3 "PRAGMA integrity_check;"

# Vacuum databases
sqlite3 chat.sqlite3 "VACUUM;"
sqlite3 rag.sqlite3 "VACUUM;"
```

## Deployment Options



### Manual Linux Deployment

1. **Install services**
   ```bash
   sudo cp systemd/cognihub.service /etc/systemd/system/
   sudo cp systemd/kiwix.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable cognihub kiwix
   ```

2. **Start services**
   ```bash
   sudo systemctl start cognihub kiwix
   ```

### Windows Deployment

See `README_Windows.md` for Windows-specific setup instructions.

## Troubleshooting

### Common Issues

1. **Ollama Connection Failed**
   - Ensure Ollama is running: `ollama serve`
   - Check OLLAMA_URL environment variable
   - Verify models are pulled: `ollama list`

2. **Port Already in Use**
   - Change FastAPI port: `uvicorn app:app --port 8001`
   - Or set environment: `API_BASE=http://localhost:8001`

3. **Database Errors**
   - Check file permissions on SQLite files
   - Run integrity check: `sqlite3 chat.sqlite3 "PRAGMA integrity_check;"`

4. **High Memory Usage**
   - Adjust cache settings in config.py
   - Monitor with `htop` or system tools

### Logs

- FastAPI logs: `logs/fastapi.log`
- Ollama logs: `logs/ollama.log`
- Application logs: `server.log`

## Contributing

1. Follow the code style guidelines in `AGENTS.md`
2. Run tests before committing
3. Update documentation for new features
4. Use type hints and proper error handling

## License

This project is open source. See individual files for license information.
