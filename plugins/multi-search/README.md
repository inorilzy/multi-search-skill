# Multi Search Plugin

This directory is the Codex plugin package for multi-search.

This package is the canonical runtime. The parent repository still contains a
legacy CLI/debug implementation under `scripts/`, but plugin tools should use
only the bundled `mcp/src/` implementation.

It contains:

- `.codex-plugin/plugin.json` for plugin metadata.
- `.mcp.json` for MCP server registration.
- `skills/multi-search/SKILL.md` as the thin natural-language trigger layer.
- `mcp/server.py` as the MCP stdio entrypoint.
- `mcp/tools.py` for tool wrappers.
- `mcp/pathing.py` to load this plugin's bundled Python package.
- `mcp/src/` as the self-contained search, scrape, state, key, and
  service implementation used by the MCP tools.

The plugin is self-contained: the MCP tools call the bundled
`src.service` layer, which owns orchestration and delegates to the
local SearchRunner, scrape pipeline, key state, and site scraper memory modules.
It does not import the parent repository's `scripts/` package, and there is no
CLI entrypoint — all access is through MCP.

Configuration boundaries:

- Secrets: environment variables or `~/.search-keys.json`.
- Non-secret defaults: `multi-search-config.json` in this plugin directory.
- Runtime state: `~/.multi-search/state.sqlite`.
- Plugin/MCP manifests: startup metadata only, never API keys.

MCP explicit arguments override `multi-search-config.json`; omitted arguments
fall back to config, then built-in defaults.

Run from this directory:

```powershell
python mcp/server.py
```

The MCP tools are:

- `multi_search`
- `scrape_url`
- `list_sources`
- `doctor`
- `get_key_status`
- `reset_key_state`
- `get_site_scraper_stats`
- `set_site_scraper_preference`
- `reset_site_scraper_stats`
