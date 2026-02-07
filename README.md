# ContextHarbor

ContextHarbor is a local-first chat + tools + RAG workspace built around Ollama.

This repo uses a workspace layout with multiple Python packages developed together.

## What's In Here

- `packages/contextharbor`: FastAPI backend + web UI + tests
- `packages/contextharbor`: FastAPI backend + web UI + tests
- `packages/ollama_cli`: `ollama-cli` library + CLI (shared clients/tools used by ContextHarbor)
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
python -m pip install -e "packages/ollama_cli[dev]" -e "packages/contextharbor[dev]"

python -m pytest

# Start ContextHarbor (creates default config on first run)
contextharbor run
```

Open `http://127.0.0.1:8000`.

## Configuration (v1.0)

ContextHarbor uses TOML config files (single authoritative format):

- `core.toml` (models, ports, limits, paths)
- `tools.toml` (enable/disable tools + tool plugins)
- `search.toml` (web search provider + rate limits)

Default config directory:

- Windows: `%APPDATA%\\contextharbor`
- macOS/Linux: `~/.config/contextharbor`

Override with `CONTEXTHARBOR_CONFIG_DIR=/path/to/dir`.

See `docs/how-contextharbor-works.md` for an end-to-end overview.

## Web UI

The UI is served from `packages/contextharbor/web/static/`.

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

ContextHarbor can use offline sources (Kiwix ZIMs, EPUB libraries) for RAG.

Configure paths/endpoints in `core.toml` (and, for now, a few optional env vars are still honored in some modules; treat TOML as authoritative).

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

If you use different models, set them in `core.toml` under `[models]`.

### Kiwix (Offline ZIMs)

ContextHarbor can search and open pages from a local Kiwix server, and list `.zim` files from a directory.

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

ContextHarbor can ingest EPUBs into RAG.

Set an ebooks directory:

```bash
EBOOKS_DIR=/path/to/ebooks
```

The UI will let you search and ingest from Settings -> Sources and the Library page.

### Web Search (Optional)

Web search is controlled by `search.toml`:

- Set `[search].enabled = false` to disable entirely
- Provider is `[search].provider = "ddg"` (single supported provider for v1.0)

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
python -m mypy packages/contextharbor/src/contextharbor --ignore-missing-imports
python -m mypy packages/ollama_cli/src/ollama_cli
```
