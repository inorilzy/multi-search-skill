"""Regression tests for multi-search."""
import os

# Search traces follow the user's `debug_log` setting. A test module run on its
# own (outside scripts/run_tests.py) still sees the real home directory, so the
# suite never writes into ~/.multi-search/logs unless a test opts in itself.
os.environ.setdefault("MULTI_SEARCH_DEBUG_LOG", "0")
