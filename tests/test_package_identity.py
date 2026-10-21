import subprocess
import sys
import unittest


class PackageIdentityTests(unittest.TestCase):
    def test_public_entrypoints_do_not_load_retired_scrape_planner(self):
        script = """
import sys
import multi_search_mcp.cli
import multi_search_mcp.src.service

assert "multi_search_mcp.src.scrape.scrape_planner" not in sys.modules
"""
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_cli_loads_core_only_through_canonical_package(self):
        script = """
import sys
import multi_search_mcp.cli as cli
from multi_search_mcp.src import service

assert cli is not service
assert not any(name == "src" or name.startswith("src.") for name in sys.modules)
"""
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
