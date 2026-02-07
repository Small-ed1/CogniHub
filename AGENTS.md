# AGENTS.md

This guide is for agentic coding assistants working in this repository.

Notes
- Prefer small, focused changes that match existing patterns.

Cursor/Copilot Rules
- No `.cursor/rules/`, `.cursorrules`, or `.github/copilot-instructions.md` found.

## Build / Run / Lint / Test

Recommended setup
```bash
python -m venv .venv

# Activate the venv
# - Windows (PowerShell): .venv\\Scripts\\Activate.ps1
# - Windows (cmd.exe):   .venv\\Scripts\\activate.bat
# - macOS/Linux:         source .venv/bin/activate

python -m pip install -U pip
python -m pip install -e "packages/ollama_cli[dev]" -e "packages/contextharbor[dev]"
```

Useful helper scripts
```bash
# generate a local .env (paths/endpoints) without committing secrets
python scripts/setup_env.py

# sanity check endpoints + directories
python scripts/doctor.py

# optional: create convenience symlinks like ~/zims and ~/Ebooks
python scripts/setup_links.py
```

Run server + UI
```bash
# FastAPI (dev)
uvicorn contextharbor.app:app --reload --host 0.0.0.0 --port 8000


# Terminal UI
contextharbor-tui


# CLI
contextharbor --help
```

Tests
```bash
# all tests
python -m pytest -q

# one file
python -m pytest packages/contextharbor/tests/test_context_builder.py -q

# single test
python -m pytest packages/contextharbor/tests/test_context_builder.py::test_build_context_caps_and_dedupe -q

# filter by substring
python -m pytest -k "context_builder or tool_runtime" -q
```

Type checking / sanity checks
```bash
# mypy (kept permissive; tighten only when scoped)
python -m mypy packages/contextharbor/src/contextharbor --ignore-missing-imports
python -m mypy packages/ollama_cli/src/ollama_cli --ignore-missing-imports
```

## Code Style Guidelines

Python version
- Target Python 3.14+.

Imports
- Use `from __future__ import annotations` at the top of modules with type hints.
- Group imports: stdlib, third-party, local; separate groups with a blank line.
- Prefer package-absolute imports within `contextharbor` (e.g., `from contextharbor.services.chat import stream_chat`).

Formatting
- 4-space indent, no tabs; keep functions small and readable.
- Prefer f-strings; avoid deeply nested expressions (use intermediate variables).
- No auto-formatter is enforced; keep lines ~100 chars when practical.
- Keep output ASCII by default; only emit unicode intentionally (e.g., user-facing text).

Typing
- Add type hints on public functions and any non-trivial internal helpers.
- Prefer builtin generics (`list[str]`, `dict[str, Any]`) and `| None` unions.
- For streaming endpoints, be explicit about `AsyncGenerator[str, None]` / async iterators.

Naming
- Modules/functions/vars: `snake_case`; classes: `PascalCase`; constants: `UPPER_SNAKE_CASE`.
- Prefix internal helpers with `_`.

Error handling
- Validate inputs early; raise `ValueError` for bad user input in pure functions/services.
- In FastAPI handlers, translate expected failures into `HTTPException` with correct status codes.
- Catch broad exceptions only at boundaries (API/tool execution), and return structured errors.

Pydantic models
- Use request/response `BaseModel` schemas for API boundaries.
- Set `model_config = ConfigDict(extra="ignore")` for tolerant request bodies; use `extra="forbid"` for strict tool contracts.
- Use `Field()` for constraints and defaults.

Async + networking
- Use explicit timeouts for outbound calls; avoid unbounded concurrency.
- Use `asyncio.Lock()` when sharing mutable process-wide state.

SQLite patterns
- Use context managers for connections/transactions; keep queries parameterized.
- Prefer `sqlite3.Row` row factory for dict-like reads.

Security + safety
- Treat URLs/hosts as untrusted: apply allow/block host lists to mitigate SSRF.
- Sanitize filenames on upload and enforce size caps (`MAX_UPLOAD_BYTES`).
- Keep tool outputs bounded (truncate + hash for logs).

Configuration
- Runtime config lives in `packages/contextharbor/src/contextharbor/config.py`.
- Common env vars: `OLLAMA_URL`, `DEFAULT_CHAT_MODEL`, `EMBED_MODEL`, `KIWIX_URL`, `KIWIX_ZIM_DIR`, `EBOOKS_DIR`.

Tool calling system (if touching tools)
- Contract types are in `packages/contextharbor/src/contextharbor/tools/contract.py` (`tool_request` / `final`).
- Tools must declare args schemas; executor enforces per-call timeout and output caps.
- Side-effecting tools must be gated via confirmation tokens.

Where to look
- API entrypoint: `packages/contextharbor/src/contextharbor/app.py`.
- Tool runtime: `packages/contextharbor/src/contextharbor/tools/registry.py`, `packages/contextharbor/src/contextharbor/tools/executor.py`.
- Stores (SQLite): `packages/contextharbor/src/contextharbor/stores/`.
