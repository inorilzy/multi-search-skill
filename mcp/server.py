#!/usr/bin/env python3
"""Compatibility wrapper for local `python mcp/server.py` launches."""
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from multi_search_mcp.server import main


if __name__ == "__main__":
    main()
