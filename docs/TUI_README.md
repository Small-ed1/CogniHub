# ContextHarbor - Terminal User Interface (TUI)

A full-featured terminal interface for ContextHarbor with the same functionality as the web UI.

## Features

### Chat Interface
- Send/receive messages in real-time
- Auto-scroll to new messages
- Rich message formatting with markdown support
- Display message roles (user/assistant/system) with color coding
- Timestamp and model display

### Slash Commands
All slash commands from the web GUI are supported:

```
/find <query>       Search messages in current chat
/search <query>       Search messages across all chats
/pin                  Toggle pin status on current chat
/archive               Toggle archive status on current chat
/summary              Generate a summary of current chat
/jump <msg_id>        Jump to a specific message in the chat
/help                 Show available commands and key bindings
```

### Chat Management
- List all chats with status indicators (pinned/archived)
- Create new chats
- Select and switch between chats
- Archive/unarchive chats
- Delete chats

### Key Bindings
```
Ctrl+Q       Quit the application
Ctrl+N       Create new chat
Ctrl+S       Toggle sidebar visibility
F5            Refresh chat list
Ctrl+T        Switch to next tab (Chats/Help)
```

## Usage

### Start the TUI

Install the workspace packages (recommended):

```bash
python -m venv .venv

# Activate the venv
# - Windows (PowerShell): .venv\\Scripts\\Activate.ps1
# - Windows (cmd.exe):   .venv\\Scripts\\activate.bat
# - macOS/Linux:         source .venv/bin/activate

python -m pip install -U pip
python -m pip install -e "packages/ollama_cli[dev]" -e "packages/contextharbor[dev]"

contextharbor-tui
```

### Requirements

The TUI connects to your running API server. Make sure the backend is running:

```bash
sudo systemctl start contextharbor
```

Or start manually:
```bash
uvicorn contextharbor.app:app --reload --host 0.0.0.0 --port 8000
```

### Configuration

The TUI reads these environment variables:

- `API_BASE` - API endpoint (default: `http://127.0.0.1:8000`)
- `OLLAMA_URL` - Ollama endpoint (default: `http://127.0.0.1:11434`)

## Screens

1. **Main Chat Screen**
   - Message history with auto-scroll
   - Input field with slash command support
   - Status bar with model info

2. **Sidebar - Chats Tab**
   - List all chats
   - Shows pinned/archived status
   - Select chat to load

3. **Sidebar - Help Tab**
   - Shows all available slash commands
   - Shows key bindings
   - Shows usage examples

## Tips

- Type `/help` in the chat input to see all available commands
- Use arrow keys to navigate message history
- Messages are automatically saved to the database
- The TUI works in any terminal with mouse support
