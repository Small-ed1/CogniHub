# CogniHub

CogniHub is a local-first chat + tools + RAG workspace built around Ollama.

This repo uses a workspace layout with multiple Python packages developed together.

## What's In Here

- `packages/cognihub`: FastAPI backend + web UI + tests
- `packages/ollama_cli`: `ollama-cli` library + CLI (shared clients/tools used by CogniHub)
- `scripts/`: helper scripts (env wizard, doctor, etc.)

## Quick Start

Prereqs:
- Python 3.14+
- Ollama running on `http://127.0.0.1:11434`

```bash
python -m venv .venv

# Activate the venv
# - Windows (PowerShell): .venv\\Scripts\\Activate.ps1
# - Windows (cmd.exe):   .venv\\Scripts\\activate.bat
# - macOS/Linux:         source .venv/bin/activate

python -m pip install -U pip
python -m pip install -e "packages/ollama_cli[dev]" -e "packages/cognihub[dev]"

python -m pytest
uvicorn cognihub.app:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## Web UI

The UI is served from `packages/cognihub/web/static/`.

Routes:
- `#/home`
- `#/chat`
- `#/library` (docs upload in sidebar; ZIM + EPUB tools in-page)
- `#/models`
- `#/settings`
- `#/chats` (dedicated chat management page)
- `#/help`

Most behavior is configurable under Settings; sources are synced between Settings and Library.

## Offline Sources

CogniHub can use offline sources (Kiwix ZIMs, EPUB libraries) for RAG.

Backend env vars (optional):

```bash
OLLAMA_URL=http://127.0.0.1:11434
KIWIX_URL=http://127.0.0.1:8081
KIWIX_ZIM_DIR=<path-to-your-zims>
EBOOKS_DIR=<path-to-your-ebooks>
EMBED_MODEL=nomic-embed-text
DEFAULT_CHAT_MODEL=llama3.1
```

UI-side overrides (stored in browser localStorage):
- Settings -> Sources

## Setup Wizard

To generate a local `.env` for your machine (without hardcoding paths in the repo):

```bash
python scripts/setup_env.py
```

## Setup Notes (Optional Components)

### Ollama

1) Install Ollama: `https://ollama.com`

2) Start Ollama (examples):

```bash
ollama serve
```

3) Pull at least one chat model and one embedding model:

```bash
ollama pull llama3.1
ollama pull nomic-embed-text
```

If you use different models, set them via `DEFAULT_CHAT_MODEL` and `EMBED_MODEL`.

### Kiwix (Offline ZIMs)

CogniHub can search and open pages from a local Kiwix server, and list `.zim` files from a directory.

Install Kiwix:
- Arch: `sudo pacman -S kiwix-tools`
- Debian/Ubuntu: `sudo apt-get install kiwix-tools`
- macOS (Homebrew): `brew install kiwix-tools`

Run `kiwix-serve` (example using a `library.xml`):

```bash
# Create a Kiwix library.xml that points to your .zim files
kiwix-serve --port 8081 --library /path/to/library.xml
```

Then set:

```bash
KIWIX_URL=http://127.0.0.1:8081
KIWIX_ZIM_DIR=/path/to/zims
```

ZIMs are not bundled; download them from a trusted source (e.g. Kiwix library).

### EPUB Ingestion

CogniHub can ingest EPUBs into RAG.

Set an ebooks directory:

```bash
EBOOKS_DIR=/path/to/ebooks
```

The UI will let you search and ingest from Settings -> Sources and the Library page.

### Web Search (Optional)

Some features can use web search providers.
If you run a local SearxNG instance, set:

```bash
SEARXNG_URL=http://localhost:8080/search
COGNIHUB_SEARCH_PROVIDER=searxng
```

## Doctor / Sanity Checks

```bash
python scripts/doctor.py
```

It checks your env vars, directories, and whether Ollama/Kiwix endpoints are reachable.

## Optional Symlinks (Convenience)

If you want stable default paths without hardcoding them in the project, you can create symlinks in your home directory:

```bash
python scripts/setup_links.py
```

This can create `~/zims -> /your/zims/path` and `~/Ebooks -> /your/ebooks/path` if you choose.

## Development

```bash
python -m pytest
python -m mypy packages/cognihub/src/cognihub --ignore-missing-imports
python -m mypy packages/ollama_cli/src/ollama_cli
```
