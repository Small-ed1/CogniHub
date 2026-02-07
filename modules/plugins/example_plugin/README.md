# Example ContextHarbor Tool Plugin

This is a minimal tool plugin demonstrating ContextHarbor's tool extension API.

## Install

From the repo root:

```bash
pip install -e modules/plugins/example_plugin
```

## Enable

Edit your `tools.toml` (usually under `%APPDATA%\\contextharbor` on Windows):

```toml
[tools]
enabled = ["web_search", "doc_search", "local_file_read", "example_time"]
plugin_modules = ["contextharbor_example_plugin"]
```

Restart ContextHarbor.

## Tools

- `example_time`: returns the server's current time.
