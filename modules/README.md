# Modules

This directory contains optional, non-core components.

Guidelines:

- Core ContextHarbor lives under `packages/`.
- Anything in here must be safe to ignore for v1.0.
- Prefer keeping optional components as self-contained Python packages.

Layout:

- `modules/agents/`: standalone agent runners / prototypes
- `modules/plugins/`: ContextHarbor tool plugins (loadable via `tools.toml`)
