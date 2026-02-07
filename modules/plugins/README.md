# Plugins

ContextHarbor tool plugins that can be enabled without editing core files.

Expected shape:

- A Python module/package that exports `register_tools(registry, **deps)`.
- Add the module path to `tools.toml` under `[tools].plugin_modules`.

## Example

This repo includes an example plugin package at:

- `modules/plugins/example_plugin`

Install it (editable):

```bash
pip install -e modules/plugins/example_plugin
```

Enable it in your ContextHarbor config (`tools.toml`):

```toml
[tools]
enabled = ["web_search", "doc_search", "local_file_read", "example_time"]
plugin_modules = ["contextharbor_example_plugin"]
```

Then restart ContextHarbor.
