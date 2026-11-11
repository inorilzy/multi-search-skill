"""Ticket 08: ``doctor`` names a user JSON config that config.sqlite shadows."""
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src import diagnostics
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support import config
from tests.desktop_schema import create_config_db


class ConfigShadowDoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.json_path = self.home / ".multi-search" / "multi-search-config.json"
        self.db_path = self.home / ".multi-search" / "config.sqlite"
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        self.store = StateStore(self.home / "state.sqlite")
        for patcher in (
            mock.patch.dict(
                os.environ,
                {
                    "MULTI_SEARCH_CONFIG": "",
                    "MULTI_SEARCH_CONFIG_DB": str(self.db_path),
                    "HOME": str(self.home),
                    "USERPROFILE": str(self.home),
                },
            ),
            mock.patch.object(config, "USER_CONFIG_PATH", self.json_path),
            mock.patch("multi_search_mcp.src.diagnostics.StateStore", return_value=self.store),
            mock.patch("multi_search_mcp.src.state.runtime.load_keys", return_value={}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_user_json(self, data=None):
        self.json_path.write_text(json.dumps(data if data is not None else {}), encoding="utf-8")

    def create_settings_db(self, settings=None):
        create_config_db(self.db_path)
        if settings is None:
            return
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "INSERT INTO settings(id,data) VALUES(1,?)",
                (json.dumps(settings),),
            )
            connection.commit()

    def test_doctor_reports_shadow_warning_when_user_json_and_config_sqlite_both_exist(self):
        self.write_user_json({"counts": {"brave": 3}})
        self.create_settings_db({"type": "default"})

        data = diagnostics.doctor_data(include_keys=False)

        self.assertEqual(data["config_path_source"], "sqlite")
        self.assertTrue(data["config_shadowed"])
        self.assertEqual(len(data["config_warnings"]), 1)
        warning = data["config_warnings"][0]
        self.assertIn("遮蔽", warning)
        self.assertIn(str(self.json_path), warning)
        self.assertEqual(data["config_status"], "ok")
        self.assertNotIn("config_error", data)

    def test_doctor_does_not_warn_when_only_the_user_json_exists(self):
        self.write_user_json({})

        data = diagnostics.doctor_data(include_keys=False)

        self.assertEqual(data["config_path_source"], "user")
        self.assertFalse(data["config_shadowed"])
        self.assertEqual(data["config_warnings"], [])

    def test_doctor_does_not_warn_when_only_config_sqlite_exists(self):
        self.create_settings_db({"type": "default"})

        data = diagnostics.doctor_data(include_keys=False)

        self.assertEqual(data["config_path_source"], "sqlite")
        self.assertFalse(data["config_shadowed"])
        self.assertEqual(data["config_warnings"], [])

    def test_doctor_does_not_warn_for_a_database_without_a_settings_record(self):
        self.write_user_json({})
        self.create_settings_db()

        data = diagnostics.doctor_data(include_keys=False)

        self.assertEqual(data["config_path_source"], "user")
        self.assertFalse(data["config_shadowed"])
        self.assertEqual(data["config_warnings"], [])

    def test_doctor_does_not_warn_when_multi_search_config_selects_the_json(self):
        self.write_user_json({})
        self.create_settings_db({"type": "default"})
        os.environ["MULTI_SEARCH_CONFIG"] = str(self.json_path)

        data = diagnostics.doctor_data(include_keys=False)

        self.assertEqual(data["config_path_source"], "env")
        self.assertFalse(data["config_shadowed"])
        self.assertEqual(data["config_warnings"], [])

    def test_doctor_cli_prints_the_shadow_warning_without_failing(self):
        self.write_user_json({"counts": {"brave": 3}})
        self.create_settings_db({"type": "default"})
        stdout, stderr = io.StringIO(), io.StringIO()

        code = cli.main(["doctor", "--no-keys"], stdout=stdout, stderr=stderr)

        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["config_shadowed"])
        self.assertIn("遮蔽", payload["config_warnings"][0])


if __name__ == "__main__":
    unittest.main()
