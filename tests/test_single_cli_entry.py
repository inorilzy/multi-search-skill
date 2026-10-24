"""Issue 24: the CLI is the single product entry; tools.py is a thin wrapper."""
from __future__ import annotations

import ast
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import multi_search_mcp.cli as cli
import multi_search_mcp.tools as tools
from multi_search_mcp.src.state.operations import (
    key_status,
    reset_key_state,
    reset_site_scraper_stats,
    set_site_scraper_preference,
    site_scraper_stats,
)
from multi_search_mcp.src.state.site_memory import SiteScraperMemory
from multi_search_mcp.src.state.state_store import StateStore


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "multi_search_mcp" / "cli.py"
TOOLS = ROOT / "multi_search_mcp" / "tools.py"


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


class CliSurfaceTests(unittest.TestCase):
    def test_sources_flags_include_shared_state_sections(self):
        with mock.patch(
            "multi_search_mcp.src.search.catalog.build_source_catalog",
            return_value={"schema_version": 1, "sources": []},
        ), mock.patch.object(cli, "key_status", return_value=[{"provider": "exa"}]) as status, \
           mock.patch.object(cli, "site_scraper_stats", return_value=[{"site": "example.com"}]) as stats:
            code, out, err = run_cli("sources", "--key-status", "--scraper-stats")

        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["key_status"], [{"provider": "exa"}])
        self.assertEqual(payload["site_scraper_stats"], [{"site": "example.com"}])
        status.assert_called_once_with()
        stats.assert_called_once_with()

    def test_sources_without_flags_does_not_touch_state(self):
        with mock.patch(
            "multi_search_mcp.src.search.catalog.build_source_catalog",
            return_value={"schema_version": 1, "sources": []},
        ), mock.patch(
            "multi_search_mcp.src.state.operations.StateStore",
            side_effect=AssertionError("sources must not open the state store by default"),
        ):
            code, out, err = run_cli("sources")

        self.assertEqual(code, 0, err)
        self.assertNotIn("key_status", json.loads(out))

    def test_no_state_is_available_on_search_fetch_and_read(self):
        captured = {}

        def fake_search(request):
            captured["search"] = request
            return {"query": request.query, "results": [], "provider_status": [], "diagnostics": {}}

        def fake_fetch(request):
            captured["fetch"] = request
            return {"source_id": request.source_id, "content": ""}

        def fake_read(request):
            captured["read"] = request
            return {"source_id": request.source_id, "content": ""}

        with mock.patch.object(cli, "run_search_web", side_effect=fake_search), \
             mock.patch.object(cli, "run_fetch_source", side_effect=fake_fetch), \
             mock.patch.object(cli, "run_read_source", side_effect=fake_read):
            self.assertEqual(run_cli("search", "q", "--no-state")[0], 0)
            self.assertEqual(run_cli("fetch", "src-1", "--no-state")[0], 0)
            self.assertEqual(run_cli("read", "src-1", "--no-state")[0], 0)

        self.assertFalse(captured["search"].use_state)
        self.assertFalse(captured["fetch"].use_state)
        self.assertFalse(captured["read"].use_state)

    def test_site_commands_read_and_write_the_same_core_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            with mock.patch(
                "multi_search_mcp.src.state.operations.StateStore", return_value=store,
            ):
                code, out, err = run_cli(
                    "site", "set-preference", "example.com", "jina", "--priority", "2",
                )
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out), {
                    "site": "example.com", "scraper": "jina",
                    "pinned": True, "priority": 2,
                })

                code, out, err = run_cli("site", "stats", "example.com")
                self.assertEqual(code, 0, err)
                rows = json.loads(out)["site_scraper_stats"]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["site"], "example.com")
                self.assertEqual(rows[0]["scraper"], "jina")
                self.assertEqual(rows[0]["manual_priority"], 2)
                self.assertEqual(rows[0]["manually_pinned"], 1)

                code, out, err = run_cli("site", "reset", "example.com")
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out), {"deleted": 1})

                code, out, err = run_cli("site", "stats", "example.com")
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out)["site_scraper_stats"], [])

    def test_site_stats_all_sites_and_reset_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            SiteScraperMemory(store).set_preference("a.example", "jina")
            SiteScraperMemory(store).set_preference("b.example", "exa")
            with mock.patch(
                "multi_search_mcp.src.state.operations.StateStore", return_value=store,
            ):
                code, out, err = run_cli("site", "stats")
                self.assertEqual(code, 0, err)
                self.assertEqual(len(json.loads(out)["site_scraper_stats"]), 2)

                code, out, err = run_cli("site", "reset")
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out), {"deleted": 2})

    def test_tools_wrappers_reuse_the_same_core_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            SiteScraperMemory(store).set_preference("example.com", "jina", priority=1)
            with mock.patch(
                "multi_search_mcp.src.state.operations.StateStore", return_value=store,
            ):
                self.assertEqual(tools.get_site_scraper_stats_tool("example.com")[
                    "site_scraper_stats"
                ][0]["manual_priority"], 1)
                self.assertEqual(tools.reset_site_scraper_stats_tool("example.com"), {"deleted": 1})

                self.assertEqual(tools.get_key_status_tool("missing"), {"key_status": []})
                self.assertEqual(tools.reset_key_state_tool("missing"), {"updated": 0})


class CoreOperationsTests(unittest.TestCase):
    def test_core_operation_functions_are_imported_by_both_entries(self):
        cli_tree = ast.parse(CLI.read_text(encoding="utf-8"))
        tools_tree = ast.parse(TOOLS.read_text(encoding="utf-8"))

        def imported_names(tree):
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    names.update(alias.name for alias in node.names)
            return names

        expected = {
            "key_status", "reset_key_state", "site_scraper_stats",
            "set_site_scraper_preference", "reset_site_scraper_stats",
        }
        self.assertLessEqual(expected, imported_names(cli_tree))
        self.assertLessEqual(expected, imported_names(tools_tree))
        for path in (CLI, TOOLS):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("SQLiteKeyManager", source)
            self.assertNotIn("SiteScraperMemory", source)
            self.assertNotIn("StateStore", source)

    def test_operations_module_is_the_only_state_command_implementation(self):
        source = (ROOT / "multi_search_mcp" / "src" / "state" / "operations.py").read_text(encoding="utf-8")
        self.assertIn("from ..support.backends import KNOWN_BACKENDS", source)
        self.assertIn("SQLiteKeyManager", source)
        self.assertIn("SiteScraperMemory", source)
        # Only this module and the search path (which summarizes status rows
        # for diagnostics) may call these storage methods.
        callers = []
        for path in (ROOT / "multi_search_mcp").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if ".status_rows(" in text or ".set_preference(" in text:
                callers.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(
            sorted(callers),
            ["multi_search_mcp/src/search/candidates.py", "multi_search_mcp/src/state/operations.py"],
        )


class ThinWrapperTests(unittest.TestCase):
    def test_tools_module_is_documented_as_a_thin_compatibility_wrapper(self):
        doc = ast.get_docstring(ast.parse(TOOLS.read_text(encoding="utf-8")))
        self.assertIsNotNone(doc)
        lowered = doc.lower()
        self.assertIn("cli", lowered)
        self.assertIn("thin", lowered)
        self.assertIn("compatibility", lowered)
        self.assertIn("no business rules", lowered)


class MigrationTokenLocationTests(unittest.TestCase):
    def test_cli_has_no_local_plan_token_implementation(self):
        source = CLI.read_text(encoding="utf-8")
        self.assertNotIn("def _plan_token", source)
        self.assertNotIn("hashlib", source)
        self.assertIn("legacy_migration.plan_token", source)


if __name__ == "__main__":
    unittest.main()
