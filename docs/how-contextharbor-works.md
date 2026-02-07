# How ContextHarbor Works (v1.0)

ContextHarbor is a local-first assistant built around:

- A FastAPI server (`contextharbor run`) that exposes a small set of HTTP endpoints
- One LLM backend (Ollama) for chat + optional tool calling
- A small, stable tool contract (discoverable + config-driven)

## Startup

1) Run `contextharbor run`
2) On first run it creates 3 TOML config files in your config directory:
   - `core.toml`
   - `tools.toml`
   - `search.toml`
3) It performs deterministic preflight checks (notably: Ollama reachability). If a check fails, it exits with a human-readable fix.

## Configuration Layout

- `core.toml`
  - `[core]` server host/port/reload
  - `[models]` Ollama URL + default chat/embed models
  - `[paths]` data directory for sqlite DBs
  - `[limits]` bounds for uploads and research loops

- `tools.toml`
  - `[tools].enabled` list of enabled tool names
  - `[tools].plugin_modules` optional python modules that register additional tools
  - per-tool config blocks (example: `[tools.local_file_read]` roots + size limits)

- `search.toml`
  - `[search].enabled` hard on/off switch
  - `[search].provider` (v1.0: `ddg`)
  - `[search].min_interval_seconds` provider rate limiting
  - `[search].user_agent` user agent string

## Chat Flow

Endpoint: `POST /api/chat`

- Validates model exists in Ollama (explicit error if missing)
- Optionally builds RAG context (documents/web/offline sources) based on request `rag` settings
- Uses a bounded tool loop (max cycles) when tools are available
- Streams results as NDJSON

Tools are never run “invisibly”:

- The server emits tool-related events (`tool_calls`, `tool_results`) in the NDJSON stream.

## Tool System

Tools are:

- Discoverable via `GET /api/tools/schemas`
- Enabled/disabled via `tools.toml`
- Executed via a stable envelope with:
  - `ok` boolean
  - `data` on success
  - `error` object on failure (with `code` + `message`)
  - `meta` for timing

Built-in tools (v1.0):

- `web_search` (network)
- `doc_search` (local RAG)
- `local_file_read` (root-scoped, size-bounded)
- `shell_exec` (dangerous; disabled by default; requires confirmation token)

## Web Search

Web search is “minimal but honest”:

- Exactly one provider is selected via config
- Failures are propagated explicitly (no pretending results exist)
- Requests are rate-limited
- A user agent is always set

## Research Mode

Endpoint: `POST /api/research/run`

- Explicitly invoked (never automatic)
- Bounded by `core.toml` limits
- Returns:
  - `answer`
  - `sources` used
  - `steps` taken (high-level)

Research synthesis is tool-free so the returned steps/sources are the full picture.

## Extending Tools Without Editing Core

1) Create a python module that exports `register_tools(registry, **deps)`
2) Add the module path to `tools.toml` under `[tools].plugin_modules`
3) Restart ContextHarbor

Your module receives dependency injection (http client, ingest queue, embed model, kiwix url) and can register new tools in the registry.
