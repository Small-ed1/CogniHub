# AGENTS.md - Router Phase 1 Development Guide

Essential information for agentic coding agents working in this repository.

## Build, Lint, and Test Commands

### Development Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Install in development mode (if editable package)
pip install -e .

# Run development server (FastAPI + Uvicorn)
uvicorn app:app --reload --host 0.0.0.0 --port 8000

# Run with custom config
OLLAMA_URL=http://localhost:11434 uvicorn app:app --reload
```

### Testing
```bash
# Run single test file
python -m pytest backup/tests/test_database.py -v

# Run all tests (from backup directory)
cd backup && python -m pytest tests/ -v

# Run tests with coverage
python -m pytest backup/tests/ --cov=agent --cov-report=html

# Run integration tests
python backup/test_integration.py

# Run component tests
python backup/test_components.py

# Manual endpoint testing
curl http://localhost:8000/health
curl http://localhost:8000/api/status
curl http://localhost:8000/api/models
```

### Linting and Code Quality
```bash
# Type checking (if mypy available)
mypy app.py --ignore-missing-imports
mypy *.py --ignore-missing-imports

# Basic syntax check
python -m py_compile app.py chatstore.py ragstore.py webstore.py researchstore.py

# Import validation
python -c "import app, chatstore, ragstore, webstore, researchstore; print('All imports successful')"
```

### Production Deployment
```bash
# Install systemd services for auto-start at boot
sudo cp systemd/cognihub.service /etc/systemd/system/
sudo cp systemd/kiwix.service /etc/systemd/system/
sudo cp kiwix-serve-sdc.sh /usr/local/bin/kiwix-serve-sdc.sh
sudo chmod +x /usr/local/bin/kiwix-serve-sdc.sh
sudo systemctl daemon-reload
sudo systemctl enable cognihub kiwix
sudo systemctl start cognihub kiwix

# Check service status
sudo systemctl status cognihub
sudo systemctl status kiwix

# Run TUI
python3 router_tui.py
```

## Service Endpoints

- **Showcase/Home Page**: http://localhost:8000
- **Full Dashboard**: http://localhost:8000/dashboard
- **Backend API**: http://localhost:8000
- **Ollama API**: http://localhost:11434 (must be running separately)
- **Kiwix API**: http://localhost:8080 (must be running separately)

## Database Management

### SQLite Database Files
- `chat.sqlite3` - Chat conversations and messages
- `rag.sqlite3` - Document storage and embeddings
- `web.sqlite3` - Web page cache and chunks
- `research.sqlite3` - Research runs and traces

### Database Operations
```bash
# Check database integrity
sqlite3 chat.sqlite3 "PRAGMA integrity_check;"

# Vacuum databases (reclaim space)
sqlite3 chat.sqlite3 "VACUUM;"
sqlite3 rag.sqlite3 "VACUUM;"

# Show database schema
sqlite3 chat.sqlite3 ".schema"
```

## Code Style Guidelines

### Python (Backend)

#### Imports
```python
from __future__ import annotations
import os, sqlite3, time
from typing import Optional, Any
from contextlib import asynccontextmanager, contextmanager
import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel, Field, ConfigDict
import ragstore, chatstore, webstore, researchstore
```

#### Type Hints
```python
async def get_chat(chat_id: str, limit: int = 2000) -> dict[str, Any]:
    return {"chat": {}, "messages": []}

def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    return None
chat_id: str | None = None
```

#### Pydantic Models
```python
class ChatCreateReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: Optional[str] = "New Chat"
```

#### Error Handling
```python
@app.get("/api/chats/{chat_id}")
async def api_get_chat(chat_id: str):
    try:
        return chatstore.get_chat(chat_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
```

#### Async/Await Patterns
```python
# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup code
    ragstore.init_db()
    _http = httpx.AsyncClient(timeout=None)
    try:
        yield
    finally:
        # Cleanup code
        if _http:
            await _http.aclose()

# Retry pattern for network calls
async def _retry(coro_factory, tries: int = 3, base_delay: float = 0.4):
    last = None
    for i in range(tries):
        try:
            return await coro_factory()
        except Exception as e:
            last = e
            await asyncio.sleep(base_delay * (2 ** i))
    raise last
```

#### Naming Conventions
- **Classes**: PascalCase (`ChatCreateReq`, `Database`)
- **Functions/Methods**: snake_case (`get_chat`, `list_chats`, `init_db`)
- **Constants**: UPPER_SNAKE_CASE (`OLLAMA_URL`, `DEFAULT_EMBED_MODEL`)
- **Files**: snake_case (`user_manager.py`, `database.py`)
- **Variables**: snake_case (`user_data`, `result_list`)
- **Private methods**: prefix with `_` (`_validate_input`)

#### Database Operations
```python
@contextmanager
def _db():
    con = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    try:
        yield con
        con.commit()
    finally:
        con.close()
```

### JavaScript (Web UI)

#### Imports
```javascript
const el = (id) => document.getElementById(id);
async function api(path, opts) {
    const res = await fetch(path, opts);
    const text = await res.text();
    let j = {};
    try { j = JSON.parse(text); } catch {}
    if (!res.ok) throw new Error(j.error || j.detail || `HTTP ${res.status}`);
    return j;
}
```

#### Naming Conventions
- **Components**: PascalCase (`ChatInterface`, `UserProfile`)
- **Functions**: camelCase (`handleSubmit`, `loadMessages`)
- **Constants**: UPPER_SNAKE_CASE (`MAX_MESSAGE_LENGTH`)
- **CSS Classes**: kebab-case (`chat-container`, `message-item`)
- **Variables**: camelCase (`userData`, `isLoading`)

### Python (TUI)

Follow backend Python conventions. Use textual for TUI components.

## File Organization

```
/
├── app.py                 # Main FastAPI application
├── chatstore.py           # Chat database operations
├── ragstore.py            # RAG document storage
├── webstore.py            # Web page scraping
├── researchstore.py       # Deep research runs
├── router_tui.py          # Terminal User Interface
├── config.py              # Configuration management
├── requirements.txt        # Python dependencies
├── static/
│   ├── index.html         # Main web UI
│   ├── app.js            # Frontend JavaScript
│   └── styles.css        # Frontend styles
├── systemd/              # Systemd service files
├── scripts/              # Utility scripts
├── docs/                 # Documentation files
├── data/                 # SQLite databases directory
└── *.sqlite3             # SQLite databases (legacy location)
```

## Environment Variables

```bash
OLLAMA_URL="http://127.0.0.1:11434"
EMBED_MODEL="embeddinggemma"
DEFAULT_CHAT_MODEL="llama3.1"
API_BASE="http://127.0.0.1:8000"
RAG_DB="rag.sqlite3"
CHAT_DB="chat.sqlite3"
MAX_UPLOAD_BYTES=10485760"
KIWIX_URL="http://127.0.0.1:8080"  # Kiwix server URL

# Web scraping SSRF protection
WEB_ALLOWED_HOSTS=""        # Comma-separated whitelist (empty = any public domain)
WEB_BLOCKED_HOSTS=""        # Comma-separated blacklist
WEB_UA="Mozilla/5.0..."  # Custom User-Agent for requests

# Research model configuration
DECIDER_MODEL=""            # Model for deciding which chat model to use
RESEARCH_PLANNER_MODEL=""   # Model for planning research queries
RESEARCH_VERIFIER_MODEL=""  # Model for verifying research claims
RESEARCH_SYNTH_MODEL=""     # Model for synthesizing research results
```

## Development Workflow

### Before Committing Changes
```bash
# Run type checking
mypy app.py --ignore-missing-imports

# Run syntax checks
python -m py_compile app.py chatstore.py ragstore.py webstore.py researchstore.py

# Test imports
python -c "import app, chatstore, ragstore, webstore, researchstore; print('All imports successful')"
```

### Common Development Tasks
```bash
# Add a new database migration
# Edit the init_db() function in the relevant store module
# Add migration logic with version checks

# Add new API endpoint
# Add route to app.py following existing patterns
# Add Pydantic models for requests/responses
# Implement business logic in appropriate store module

# Update frontend
# Edit static/index.html for structure
# Edit static/app.js for functionality
# Edit static/styles.css for styling
```

## Security Considerations

- **API Key Protection**: Use `API_KEY` environment variable for endpoint protection
- **File Upload Limits**: Respect `MAX_UPLOAD_BYTES` configuration
- **Web Scraping**: Configure `WEB_ALLOWED_HOSTS` and `WEB_BLOCKED_HOSTS` for SSRF protection
- **Database Safety**: Always use parameterized queries, never string interpolation
- **Input Validation**: Validate all user inputs through Pydantic models

## Notes

- **No automated tests**: All testing is manual via curl or web UI
- **No linting/formatting config**: Code style is maintained manually
- **SQLite WAL mode**: Always use WAL journal mode for concurrency
- **Type hints**: Use `dict[str, Any]` and `list[str]` style (Python 3.9+)
- **Async context managers**: Use `@asynccontextmanager` for lifespan in FastAPI apps
- **Error responses**: Return JSON with `{"error": "message"}` or `{"detail": "message"}`
