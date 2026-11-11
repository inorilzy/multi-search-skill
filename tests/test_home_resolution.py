"""Config and state paths resolve at call time and honour the shared state override."""
import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.state import state_store
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support import config


ROOT = Path(__file__).resolve().parents[1]
SCRAPE_MEMORY_RS = ROOT / "desktop" / "src-tauri" / "src" / "scrape_memory.rs"


class HomeResolutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="home-resolution-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def _home(self, name):
        home = self.root / name
        (home / ".multi-search").mkdir(parents=True)
        return home

    def _environment(self, home, **overrides):
        values = {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "MULTI_SEARCH_CONFIG": "",
            "MULTI_SEARCH_CONFIG_DB": "",
            "MULTI_SEARCH_STATE_DB": "",
        }
        values.update(overrides)
        return mock.patch.dict(os.environ, values)

    def test_config_path_follows_home_changed_in_the_same_process(self):
        first, second = self._home("first"), self._home("second")
        for home in (first, second):
            (home / ".multi-search" / "multi-search-config.json").write_text("{}", encoding="utf-8")

        with self._environment(first):
            self.assertEqual(
                config.resolve_config_path(),
                first / ".multi-search" / "multi-search-config.json",
            )
            self.assertEqual(
                config.USER_CONFIG_PATH,
                first / ".multi-search" / "multi-search-config.json",
            )
        with self._environment(second):
            self.assertEqual(
                config.resolve_config_path(),
                second / ".multi-search" / "multi-search-config.json",
            )
            self.assertEqual(
                config.USER_CONFIG_PATH,
                second / ".multi-search" / "multi-search-config.json",
            )

    def test_config_database_path_follows_home_changed_in_the_same_process(self):
        first, second = self._home("first"), self._home("second")

        with self._environment(first):
            self.assertEqual(config.config_db_path(), first / ".multi-search" / "config.sqlite")
        with self._environment(second):
            self.assertEqual(config.config_db_path(), second / ".multi-search" / "config.sqlite")

    def test_state_database_path_follows_home_changed_in_the_same_process(self):
        first, second = self._home("first"), self._home("second")

        with self._environment(first):
            self.assertEqual(StateStore().path, first / ".multi-search" / "state.sqlite")
            self.assertEqual(
                state_store.DEFAULT_STATE_PATH,
                first / ".multi-search" / "state.sqlite",
            )
        with self._environment(second):
            self.assertEqual(StateStore().path, second / ".multi-search" / "state.sqlite")
            self.assertEqual(
                state_store.DEFAULT_STATE_PATH,
                second / ".multi-search" / "state.sqlite",
            )

    def test_state_store_reads_multi_search_state_db_override(self):
        home = self._home("home")
        custom = self.root / "custom" / "state.sqlite"

        with self._environment(home, MULTI_SEARCH_STATE_DB=str(custom)):
            store = StateStore()

        self.assertEqual(store.path, custom)
        self.assertTrue(custom.exists())

    def test_state_database_override_is_a_literal_path_like_the_desktop(self):
        home = self._home("home")

        with self._environment(home, MULTI_SEARCH_STATE_DB="~/custom/state.sqlite"):
            self.assertEqual(state_store.default_state_path(), Path("~/custom/state.sqlite"))

    def test_desktop_and_cli_read_the_same_state_database_override(self):
        source = SCRAPE_MEMORY_RS.read_text(encoding="utf-8")
        match = re.search(r'const STATE_DB_ENV: &str = "([^"]+)";', source)

        self.assertIsNotNone(match, "desktop state override constant is missing")
        self.assertEqual(match.group(1), state_store.STATE_DB_ENV)

    def test_new_state_database_does_not_create_provider_runs(self):
        store = StateStore(self.root / "new" / "state.sqlite")

        with store.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }

        self.assertNotIn("provider_runs", tables)
        self.assertIn("key_state", tables)

    def test_existing_state_database_with_provider_runs_still_opens(self):
        path = self.root / "legacy" / "state.sqlite"
        path.parent.mkdir(parents=True)
        with sqlite3.connect(path) as conn:
            conn.execute(
                """
                CREATE TABLE provider_runs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  provider TEXT NOT NULL,
                  operation TEXT NOT NULL,
                  success INTEGER NOT NULL,
                  raw_hits INTEGER,
                  error_type TEXT,
                  error_message TEXT,
                  elapsed_ms INTEGER,
                  created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO provider_runs(provider, operation, success, created_at) "
                "VALUES('brave', 'search', 1, 't0')"
            )
            conn.execute("PRAGMA user_version=2")

        store = StateStore(path)

        with store.connect() as conn:
            rows = [tuple(row) for row in conn.execute("SELECT provider, operation FROM provider_runs")]
            key_state_exists = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='key_state'"
            ).fetchone()[0]
        self.assertEqual(rows, [("brave", "search")])
        self.assertEqual(key_state_exists, 1)


if __name__ == "__main__":
    unittest.main()
