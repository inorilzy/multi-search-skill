"""Run the regression suite with disposable state and denied external network."""
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.test_isolation import NetworkIsolationError, isolated_test_environment


def main():
    with isolated_test_environment(source_root=ROOT) as isolation:
        suite = unittest.defaultTestLoader.discover(
            str(ROOT / "tests"), pattern="test_*.py", top_level_dir=str(ROOT),
        )
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        try:
            isolation.assert_clean()
        except NetworkIsolationError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        return int(not result.wasSuccessful())


if __name__ == "__main__":
    raise SystemExit(main())
