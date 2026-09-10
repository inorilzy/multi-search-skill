"""Run the regression suite with disposable runtime state."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    with tempfile.TemporaryDirectory(prefix="multi-search-tests-") as temp:
        with patch("multi_search_mcp.src.state.state_store.DEFAULT_STATE_PATH", Path(temp) / "state.sqlite"):
            suite = unittest.defaultTestLoader.discover(str(root), pattern="test_*.py")
            result = unittest.TextTestRunner(verbosity=1).run(suite)
            return not result.wasSuccessful()


if __name__ == "__main__":
    raise SystemExit(main())
