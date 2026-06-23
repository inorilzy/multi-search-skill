#!/usr/bin/env python3
"""Legacy shim for the canonical multi-search plugin MCP server."""
from __future__ import annotations

import runpy
from pathlib import Path


PLUGIN_SERVER = Path(__file__).resolve().parents[1] / "multi-search-plugin" / "mcp" / "server.py"


if __name__ == "__main__":
    runpy.run_path(str(PLUGIN_SERVER), run_name="__main__")
