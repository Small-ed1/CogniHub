# AGENTS.md

This guide is for agentic coding assistants working in this repository.

Notes
- The repo is mid-migration; the actively-developed setup is under `monorepo/`.
- Prefer small, focused changes that match existing patterns.

Cursor/Copilot Rules
- No `.cursor/rules/`, `.cursorrules`, or `.github/copilot-instructions.md` found.

## Build / Run / Lint / Test

Recommended setup (monorepo)
```bash
cd monorepo
python -m venv .venv
source .venv/bin/activate

python -m pip install -U pip
python -m pip install -e packages/ollama_cli
python -m pip install -e packages/cognihub
```

Useful helper scripts (monorepo)
```bash
cd monorepo

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
cd monorepo
uvicorn cognihub.app:app --reload --host 127.0.0.1 --port 8000

# Terminal UI
cd monorepo
cognihub-tui

# CLI
cd monorepo
cognihub --help
```

Tests (monorepo)
```bash
cd monorepo

# all tests
python -m pytest -q

# one file
python -m pytest packages/cognihub/tests/test_context_builder.py -q

# single test
python -m pytest packages/cognihub/tests/test_context_builder.py::test_build_context_caps_and_dedupe -q

# filter by substring
python -m pytest -k "context_builder or tool_runtime" -q
```

Tests (legacy root layout)
```bash
# all tests
PYTHONPATH=src python -m pytest -q

# single test
PYTHONPATH=src python -m pytest tests/test_tool_runtime.py::test_tool_executor_timeout -q
```

Type checking / sanity checks
```bash
cd monorepo

# mypy (kept permissive; tighten only when scoped)
python -m mypy packages/cognihub/src/cognihub --ignore-missing-imports
python -m mypy packages/ollama_cli/src/ollama_cli --ignore-missing-imports

# quick syntax check (legacy root layout)
python -m py_compile src/cognihub/app.py src/cognihub/stores/*.py src/cognihub/services/*.py
```

Legacy (repo root) notes
- Root `src/cognihub/` still runs; prefer monorepo for new work.
- If you run from root without installing, use `PYTHONPATH=src`.

## Code Style Guidelines

Python version
- Target Python 3.14+ in `monorepo/` (the actively-developed packaging).

Imports
- Use `from __future__ import annotations` at the top of modules with type hints.
- Group imports: stdlib, third-party, local; separate groups with a blank line.
- Prefer package-absolute imports within `cognihub` (e.g., `from cognihub.services.chat import stream_chat`).

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
- Runtime config lives in `src/cognihub/config.py` (monorepo mirrors this).
- Common env vars: `OLLAMA_URL`, `DEFAULT_CHAT_MODEL`, `EMBED_MODEL`, `KIWIX_URL`, `KIWIX_ZIM_DIR`, `EBOOKS_DIR`.

Tool calling system (if touching tools)
- Contract types are in `src/cognihub/tools/contract.py` (`tool_request` / `final`).
- Tools must declare args schemas; executor enforces per-call timeout and output caps.
- Side-effecting tools must be gated via confirmation tokens.

Where to look
- API entrypoint: `src/cognihub/app.py` (and monorepo equivalent).
- Tool runtime: `src/cognihub/tools/registry.py`, `src/cognihub/tools/executor.py`.
- Stores (SQLite): `src/cognihub/stores/`.
