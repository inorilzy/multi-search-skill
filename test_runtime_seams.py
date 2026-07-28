import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.service import list_sources
from multi_search_mcp.src.state.keys import load_keys


class RuntimeSeamTests(unittest.TestCase):
    def test_load_keys_accepts_injected_file_and_environ_with_env_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            keys_path = Path(tmp) / "custom-keys.json"
            keys_path.write_text(
                json.dumps({"brave": "file-brave", "exa": "file-exa"}),
                encoding="utf-8",
            )

            keys = load_keys(
                keys_file=keys_path,
                environ={"BRAVE_API_KEY": "env-brave", "EXA_API_KEY": "env-exa"},
            )

        self.assertEqual(keys["brave"], "env-brave")
        self.assertEqual(keys["exa"], "env-exa")

    def test_list_sources_skips_state_store_when_status_flags_are_disabled(self):
        with mock.patch("multi_search_mcp.src.service.StateStore", side_effect=AssertionError("StateStore should not be constructed")):
            data = list_sources(include_key_status=False, include_scraper_stats=False)

        self.assertIn("default", data["routes"])
        self.assertIn("brave", data["sources"])
        self.assertNotIn("key_status", data)
        self.assertNotIn("site_scraper_stats", data)

    def test_list_sources_constructs_state_store_when_status_requested(self):
        fake_store = object()
        fake_manager = mock.Mock()
        fake_manager.status_rows.return_value = [{"provider": "exa"}]

        with mock.patch("multi_search_mcp.src.service.StateStore", return_value=fake_store) as store_cls, \
             mock.patch("multi_search_mcp.src.service.SQLiteKeyManager", return_value=fake_manager):
            data = list_sources(include_key_status=True, include_scraper_stats=False)

        store_cls.assert_called_once_with()
        fake_manager.status_rows.assert_called_once_with()
        self.assertEqual(data["key_status"], [{"provider": "exa"}])


if __name__ == "__main__":
    unittest.main()
