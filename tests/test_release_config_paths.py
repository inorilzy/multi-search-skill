"""Release-mode config resolution: no compiled-in or site-packages dev fallback."""
import importlib.util
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


REPO_ROOT = Path(__file__).resolve().parents[1]


def _missing_home_config(root: Path) -> Path:
    return root / "home" / ".multi-search" / "multi-search-config.json"


class SourceCheckoutDetectionTests(unittest.TestCase):
    def test_the_repository_is_detected_as_a_source_checkout(self):
        self.assertTrue(config.IS_SOURCE_CHECKOUT)
        self.assertEqual(config.dev_config_path(), REPO_ROOT / "multi-search-config.json")

    def test_a_site_packages_layout_is_not_a_source_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            site_packages = Path(temp) / "site-packages"
            # What a wheel installs: the package, but no project manifest next to it.
            (site_packages / "multi_search_mcp" / "src" / "support").mkdir(parents=True)
            (site_packages / "multi_search_mcp" / "cli.py").write_text("", encoding="utf-8")
            self.assertFalse(config._is_source_checkout(site_packages))

    def test_an_installed_module_never_resolves_next_to_site_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            site_packages = Path(temp) / "site-packages"
            module_path = site_packages / "multi_search_mcp" / "src" / "support" / "config.py"
            module_path.parent.mkdir(parents=True)
            module_path.write_text(Path(config.__file__).read_text(encoding="utf-8"), encoding="utf-8")
            # A local attacker can place a config file here; an installed CLI must ignore it.
            (site_packages / "multi-search-config.json").write_text('{"type": "dev"}', encoding="utf-8")

            spec = importlib.util.spec_from_file_location("multi_search_installed_config", module_path)
            installed = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(installed)

            home_config = _missing_home_config(Path(temp))
            with mock.patch.object(installed, "USER_CONFIG_PATH", home_config), \
                 mock.patch.dict(os.environ, {installed.CONFIG_ENV_VAR: ""}):
                self.assertIsNone(installed.DEV_CONFIG_PATH, "an installed package must not even name a dev path")
                self.assertIsNone(installed.dev_config_path())
                path, source = installed.resolve_config_path_source()
                self.assertEqual((path, source), (home_config, "defaults"))
                self.assertNotIn("site-packages", str(path))
                self.assertEqual(installed.load_config(), {}, "the site-packages config must never be read")


class SourceTreeFallbackTests(unittest.TestCase):
    def test_source_checkout_reads_the_dev_file_only_when_the_user_file_is_absent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dev = root / "multi-search-config.json"
            dev.write_text('{"type": "dev"}', encoding="utf-8")
            user = _missing_home_config(root)
            with mock.patch.object(config, "IS_SOURCE_CHECKOUT", True), \
                 mock.patch.object(config, "DEV_CONFIG_PATH", dev), \
                 mock.patch.object(config, "USER_CONFIG_PATH", user), \
                 mock.patch.dict(os.environ, {config.CONFIG_ENV_VAR: ""}):
                self.assertEqual(config.resolve_config_path_source(), (dev, "dev_fallback"))
                self.assertEqual(config.load_config(), {"type": "dev"})

                user.parent.mkdir(parents=True)
                user.write_text("{}", encoding="utf-8")
                self.assertEqual(config.resolve_config_path_source(), (user, "user"))

    def test_installed_layout_ignores_a_dev_file_even_when_it_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dev = root / "multi-search-config.json"
            dev.write_text('{"type": "dev"}', encoding="utf-8")
            user = _missing_home_config(root)
            with mock.patch.object(config, "IS_SOURCE_CHECKOUT", False), \
                 mock.patch.object(config, "DEV_CONFIG_PATH", dev), \
                 mock.patch.object(config, "USER_CONFIG_PATH", user), \
                 mock.patch.dict(os.environ, {config.CONFIG_ENV_VAR: ""}):
                self.assertIsNone(config.dev_config_path())
                self.assertEqual(config.resolve_config_path_source(), (user, "defaults"))
                self.assertEqual(config.load_config(), {})

    def test_environment_variable_still_wins_in_every_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            explicit = Path(temp) / "explicit.json"
            explicit.write_text("{}", encoding="utf-8")
            with mock.patch.object(config, "IS_SOURCE_CHECKOUT", False), \
                 mock.patch.dict(os.environ, {config.CONFIG_ENV_VAR: str(explicit)}):
                self.assertEqual(config.resolve_config_path_source(), (explicit, "env"))


class DoctorConfigPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for patcher in (
            mock.patch("multi_search_mcp.src.diagnostics.StateStore", return_value=StateStore(self.root / "state.sqlite")),
            mock.patch("multi_search_mcp.src.state.runtime.load_keys", return_value={}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_doctor_json_reports_the_path_and_source_the_cli_uses(self):
        explicit = self.root / "explicit.json"
        explicit.write_text("{}", encoding="utf-8")
        with mock.patch.dict(os.environ, {config.CONFIG_ENV_VAR: str(explicit)}):
            data = service.doctor_data(include_keys=False)
            self.assertEqual(data["config_path"], str(explicit))
            self.assertEqual(data["config_path_source"], "env")

            stdout, stderr = io.StringIO(), io.StringIO()
            code = cli.main(["doctor", "--no-keys", "--format", "json"], stdout=stdout, stderr=stderr)
            payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["config_path"], str(explicit))
        self.assertEqual(payload["config_path_source"], "env")

    def test_doctor_reports_the_user_path_never_site_packages_in_an_installed_layout(self):
        user = _missing_home_config(self.root)
        with mock.patch.object(config, "IS_SOURCE_CHECKOUT", False), \
             mock.patch.object(config, "DEV_CONFIG_PATH", self.root / "site-packages" / "multi-search-config.json"), \
             mock.patch.object(config, "USER_CONFIG_PATH", user), \
             mock.patch.dict(os.environ, {config.CONFIG_ENV_VAR: ""}):
            data = service.doctor_data(include_keys=False)
        self.assertEqual(data["config_path"], str(user))
        self.assertEqual(data["config_path_source"], "defaults")
        self.assertNotIn("site-packages", data["config_path"])


if __name__ == "__main__":
    unittest.main()
