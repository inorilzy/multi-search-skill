import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src import service
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support import config


class ConfigurationDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.json"
        self.store = StateStore(Path(self.temp.name) / "state.sqlite")
        for patcher in (
            mock.patch.dict(os.environ, {config.CONFIG_ENV_VAR: str(self.path)}),
            mock.patch.object(service, "StateStore", return_value=self.store),
            mock.patch.object(service, "load_keys", return_value={}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_missing_env_path_is_an_error(self):
        with self.assertRaisesRegex(config.ConfigError, "config file not found"):
            config.load_config()

    def test_explicit_path_missing_or_malformed_is_an_error(self):
        with self.assertRaises(config.ConfigError):
            config.load_config(str(self.path))
        self.path.write_text("[broken", encoding="utf-8")
        with self.assertRaises(config.ConfigError):
            config.load_config()

    def test_missing_implicit_default_uses_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(config, "resolve_config_path", return_value=self.path):
            self.assertEqual(config.load_config(), {})

    def test_doctor_parses_and_validates_configuration(self):
        for text in ("{broken", '{"disabled_sources":["missing-provider"]}', '{"expand":false}',
                     '{"expand":["variant"],"query_fusion":{"mode":"weighted","primary_weight":1,"variant_budget":2}}'):
            with self.subTest(text=text):
                self.path.write_text(text, encoding="utf-8")
                data = service.doctor_data(include_keys=False)
                self.assertFalse(data["config_loaded"])
                self.assertEqual(data["config_status"], "error")
                self.assertTrue(data["config_error"])
                self.assertFalse(data["network_checked"])

    def test_doctor_reports_missing_explicit_config(self):
        data = service.doctor_data(include_keys=False)
        self.assertFalse(data["config_loaded"])
        self.assertIn("not found", data["config_error"])

    def test_doctor_network_reports_partial_failure(self):
        self.path.write_text("{}", encoding="utf-8")
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"{}"
        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", side_effect=[response, TimeoutError("probe timeout")]) as opener:
            data = service.doctor_data(include_keys=False, include_network=True)
        self.assertEqual(opener.call_count, 2)
        self.assertTrue(data["config_loaded"])
        self.assertTrue(data["network_checked"])
        self.assertFalse(data["network_ok"])
        self.assertEqual([row["status"] for row in data["network_checks"]], ["ok", "error"])
        self.assertIn("probe timeout", data["network_checks"][1]["error"])

    def test_doctor_network_success_and_no_network_default(self):
        self.path.write_text("{}", encoding="utf-8")
        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry") as opener:
            data = service.doctor_data(include_keys=False)
            opener.assert_not_called()
            self.assertFalse(data["network_checked"])
            self.assertIsNone(data["network_ok"])
            data = service.doctor_data(include_keys=False, include_network=True)
            self.assertTrue(data["network_ok"])
            self.assertEqual(opener.call_count, 2)

    def test_doctor_cli_returns_nonzero_for_bad_configuration(self):
        self.path.write_text("{broken", encoding="utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        code = cli.main(["doctor", "--no-keys"], stdout=stdout, stderr=stderr)
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(stdout.getvalue())["config_loaded"])

    def test_doctor_with_keys_still_renders_configuration_and_network(self):
        self.path.write_text("{broken", encoding="utf-8")
        for output_format in ("human", "markdown"):
            with self.subTest(output_format=output_format):
                stdout, stderr = io.StringIO(), io.StringIO()
                code = cli.main(["doctor", "--format", output_format], stdout=stdout, stderr=stderr)
                self.assertEqual(code, 1)
                self.assertIn("config_error", stdout.getvalue())
                self.assertIn("not valid JSON", stdout.getvalue())
                self.assertIn("network_checked", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
