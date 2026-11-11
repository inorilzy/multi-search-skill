"""Plugin declarations exported through the shared source catalog (ticket 02).

`multi-search sources --format json` and `desktop/source-catalog.json` must
carry the login methods and balance capability of every built-in plugin, and
each source must name the plugin that owns it.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.plugins import builtin_plugins
from multi_search_mcp.src.search import catalog as catalog_module
from scripts.export_source_catalog import JSON_PATH


def _run_cli(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(args), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _expected_auth_methods(plugin) -> list[dict[str, str]]:
    return [
        {
            "type": method.type,
            "label": method.label,
            "credential": method.credential,
            "purpose": method.purpose,
        }
        for method in plugin.auth_methods
    ]


class PluginCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog_module.build_source_catalog()
        self.entries = {entry["id"]: entry for entry in self.catalog["plugins"]}

    def test_plugins_array_follows_plugin_registration_order(self):
        self.assertEqual(
            [entry["id"] for entry in self.catalog["plugins"]],
            [plugin.id for plugin in builtin_plugins()],
        )

    def test_plugin_entries_match_their_declarations(self):
        self.assertEqual(len(self.entries), len(self.catalog["plugins"]), "plugin ids are unique")
        for plugin in builtin_plugins():
            with self.subTest(plugin=plugin.id):
                entry = self.entries[plugin.id]
                self.assertEqual(set(entry), {
                    "id", "label", "key_provider", "search_sources", "scrape_channels",
                    "auth_methods", "balance_supported", "balance_note",
                })
                self.assertEqual(entry["label"], plugin.label)
                self.assertEqual(entry["key_provider"], plugin.key_provider)
                self.assertEqual(entry["search_sources"], list(plugin.search_sources))
                self.assertEqual(entry["scrape_channels"], list(plugin.scrape_channels))
                self.assertEqual(entry["auth_methods"], _expected_auth_methods(plugin))
                self.assertIs(entry["balance_supported"], plugin.balance is not None)
                self.assertEqual(entry["balance_note"], plugin.balance_note)

    def test_balance_supported_reflects_the_balance_callable(self):
        self.assertFalse(self.entries["baidu"]["balance_supported"])
        self.assertTrue(self.entries["baidu"]["balance_note"].strip())
        for entry in self.catalog["plugins"]:
            self.assertIsInstance(entry["balance_supported"], bool, entry["id"])

    def test_every_source_entry_names_its_owning_plugin(self):
        plugins = {plugin.id: plugin for plugin in builtin_plugins()}
        self.assertEqual(len(self.catalog["sources"]), len({source["name"] for source in self.catalog["sources"]}))
        for source in self.catalog["sources"]:
            with self.subTest(source=source["name"]):
                self.assertIn("plugin", source)
                self.assertIn(source["plugin"], plugins)
                plugin = plugins[source["plugin"]]
                self.assertTrue(
                    source["name"] in plugin.search_sources or source["name"] in plugin.scrape_channels,
                    f"{source['name']} is owned by {source['plugin']}",
                )
        ownership = {source["name"]: source["plugin"] for source in self.catalog["sources"]}
        self.assertEqual(ownership["github_repos"], "github")
        self.assertEqual(ownership["github_code"], "github")
        self.assertEqual(ownership["stackoverflow"], "stackexchange")
        self.assertEqual(ownership["jina"], "jina")

    def test_configured_catalog_keeps_plugin_metadata(self):
        configured = catalog_module.build_configured_source_catalog({})
        self.assertEqual(configured["plugins"], self.catalog["plugins"])
        self.assertEqual(
            [source["plugin"] for source in configured["sources"]],
            [source["plugin"] for source in self.catalog["sources"]],
        )


class CatalogCliPluginTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config_path = Path(temp.name) / "settings.json"
        self.config_path.write_text("{}", encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {"MULTI_SEARCH_CONFIG": str(self.config_path)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_sources_json_exposes_plugins_and_source_ownership(self):
        code, out, err = _run_cli("sources", "--format", "json")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["plugins"], catalog_module.build_source_catalog()["plugins"])
        self.assertTrue(payload["plugins"], "the JSON output includes the plugin catalog")
        for source in payload["sources"]:
            self.assertIn("plugin", source, source["name"])


class GeneratedPluginArtifactTests(unittest.TestCase):
    def test_desktop_artifact_contains_the_generated_plugin_catalog(self):
        artifact = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        builtin = catalog_module.build_source_catalog()
        self.assertEqual(artifact["plugins"], builtin["plugins"])
        self.assertEqual(
            [source["plugin"] for source in artifact["sources"]],
            [source["plugin"] for source in builtin["sources"]],
        )


if __name__ == "__main__":
    unittest.main()
