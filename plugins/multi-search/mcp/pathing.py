"""Path helpers for the multi-search MCP server."""
from __future__ import annotations

import sys
from pathlib import Path


MCP_ROOT = Path(__file__).resolve().parent


def add_plugin_to_path() -> None:
    root = str(MCP_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
