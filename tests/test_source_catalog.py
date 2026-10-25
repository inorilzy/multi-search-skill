"""Contract tests for the shared source catalog (issue 09, review H-04/L-01).

The Python core owns the catalog; the CLI exposes it; the desktop consumes
generated artifacts. These tests pin all three edges so a source rename cannot
leave a stale copy behind in Rust or JavaScript.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from multi_search_mcp import cli
from multi_search_mcp.src.search import catalog as catalog_module
from multi_search_mcp.src.search.capabilities import PROVIDER_CAPABILITIES
from multi_search_mcp.src.search.search_runner import (
    ALL_SOURCE_NAMES,
    ROUTE_ALIASES,
    ROUTE_PROFILES,
    ROUTE_SOURCE_ORDER,
    SOURCE_ALIASES,
)
from multi_search_mcp.src.state.keys import (
    CREDENTIAL_STORE_PROVIDERS,
    KEY_ENV_NAMES,
    KEY_ENV_PAIRS,
    load_keys,
)
from scripts.export_source_catalog import JS_PATH, JSON_PATH, artifacts, check, render_js


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


class _FakeStore:
    def __init__(self, values: dict[str, str] | None = None):
        self.values = values or {}

    def get(self, provider: str):
        return self.values.get(provider)


def _run_cli(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(args), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


class CatalogCliTests(unittest.TestCase):
    def test_sources_json_is_the_shared_catalog(self):
        code, out, err = _run_cli("sources", "--format", "json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), catalog_module.build_source_catalog())

    def test_sources_defaults_to_json_and_supports_other_formats(self):
        code, out, err = _run_cli("sources")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["schema_version"], catalog_module.SCHEMA_VERSION)
        for output_format in ("human", "markdown"):
            with self.subTest(output_format=output_format):
                code, out, err = _run_cli("sources", "--format", output_format)
                self.assertEqual(code, 0, err)
                self.assertTrue(out.strip())


class CatalogCoreParityTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog_module.build_source_catalog()
        self.sources = {entry["name"]: entry for entry in self.catalog["sources"]}

    def test_every_provider_has_one_catalog_entry(self):
        self.assertEqual(list(self.sources), list(catalog_module.SOURCE_DISPLAY_ORDER))
        self.assertEqual(set(self.sources), set(PROVIDER_CAPABILITIES))
        self.assertEqual(
            {name for name, entry in self.sources.items() if entry["searchable"]},
            ALL_SOURCE_NAMES,
        )

    def test_aliases_match_search_runner(self):
        self.assertEqual(self.catalog["source_aliases"], dict(sorted(SOURCE_ALIASES.items())))
        for name, entry in self.sources.items():
            expected = sorted(alias for alias, target in SOURCE_ALIASES.items() if target == name)
            self.assertEqual(entry["aliases"], expected, name)

    def test_routes_match_route_profiles_and_keep_documented_order(self):
        routes = {entry["name"]: entry for entry in self.catalog["routes"]}
        self.assertEqual(set(routes), set(ROUTE_SOURCE_ORDER))
        for name, sources in ROUTE_SOURCE_ORDER.items():
            self.assertEqual(routes[name]["sources"], list(sources))
            self.assertEqual(set(sources), ROUTE_PROFILES[name])
        for name, entry in routes.items():
            expected_aliases = sorted(alias for alias, target in ROUTE_ALIASES.items() if target == name)
            self.assertEqual(entry["aliases"], expected_aliases)
        # Each source advertises exactly the routes that contain it.
        for name, entry in self.sources.items():
            self.assertEqual(
                entry["routes"],
                [route for route in ROUTE_SOURCE_ORDER if name in ROUTE_PROFILES[route]],
            )

    def test_env_names_match_key_env_pairs(self):
        self.assertEqual(self.catalog["key_resolution"]["order"], list(catalog_module.KEY_RESOLUTION_ORDER))
        self.assertEqual(self.catalog["key_resolution"]["env_alias_priority"], "last_non_empty_wins")
        self.assertEqual(self.catalog["env"]["alias_priority"], "last_non_empty_wins")

        expected: dict[str, list[str]] = {}
        for env_name, provider in KEY_ENV_PAIRS:
            expected.setdefault(provider, []).append(env_name)
        self.assertEqual(self.catalog["env"]["providers"], expected)
        flattened = [name for names in self.catalog["env"]["providers"].values() for name in names]
        self.assertEqual(flattened, list(KEY_ENV_NAMES))

        for name, entry in self.sources.items():
            provider = entry["key_provider"]
            expected_env = expected.get(provider) or expected.get(f"{name}_cookies") or []
            self.assertEqual(entry["env"], expected_env, name)

    def test_credential_store_metadata_matches_keys_module(self):
        self.assertEqual(
            self.catalog["credential_store_providers"], list(CREDENTIAL_STORE_PROVIDERS)
        )
        keyed = {name for name, entry in self.sources.items() if entry["keyed"]}
        self.assertEqual(
            keyed,
            {
                "baidu", "brave", "parallel", "tavily", "exa", "firecrawl", "serpapi", "github_repos", "jina",
            },
        )
        self.assertEqual(self.sources["github_repos"]["key_provider"], "github")
        self.assertEqual(self.sources["twitter"]["env"], ["TWITTER_COOKIES_PATH"])
        self.assertTrue(self.sources["twitter"]["cookie"])
        self.assertFalse(self.sources["jina"]["searchable"])

    def test_presentation_metadata_covers_every_source_and_route(self):
        for name, entry in self.sources.items():
            with self.subTest(source=name):
                self.assertTrue(entry["label"].strip())
                self.assertTrue(entry["description"].strip())
                self.assertTrue(entry["mark"].strip())
                self.assertEqual(entry["public_name"], PROVIDER_CAPABILITIES[name].public_name)
                self.assertEqual(entry["max_count"], PROVIDER_CAPABILITIES[name].search.max_count)
        for route in self.catalog["routes"]:
            self.assertTrue(route["label"].strip())


class EnvPrecedenceTests(unittest.TestCase):
    def test_catalog_env_order_is_the_order_load_keys_applies(self):
        catalog = catalog_module.build_source_catalog()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        keys_file = Path(temp.name) / "missing-keys.json"
        environ = {
            env_name: f"value-{env_name}"
            for env_name, _provider in KEY_ENV_PAIRS
        }
        keys = load_keys(keys_file, environ=environ, credential_store=None)
        for provider, env_names in catalog["env"]["providers"].items():
            expected = environ[env_names[-1]]
            if provider == "twitter_cookies":
                self.assertEqual(keys["twitter"], expected)
                self.assertEqual(keys["twitter_cookies"], expected)
            else:
                self.assertEqual(keys[provider], expected, provider)

    def test_key_resolution_order_is_env_store_file(self):
        catalog = catalog_module.build_source_catalog()
        self.assertEqual(catalog["key_resolution"]["order"], ["env", "credential_store", "keys_file"])
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        keys_file = Path(temp.name) / "keys.json"
        keys_file.write_text(json.dumps({"brave": "file-key"}), encoding="utf-8")
        store = _FakeStore({"brave": "store-key"})

        from_store = load_keys(keys_file, environ={}, credential_store=store)
        self.assertEqual(from_store["brave"], "store-key")

        from_env = load_keys(
            keys_file,
            environ={"BRAVE_SEARCH_API_KEY": "env-old", "BRAVE_API_KEY": "env-new"},
            credential_store=store,
        )
        self.assertEqual(from_env["brave"], "env-new", "last non-empty env alias wins over env+store")

        from_file = load_keys(keys_file, environ={}, credential_store=_FakeStore())
        self.assertEqual(from_file["brave"], "file-key")


class GeneratedArtifactTests(unittest.TestCase):
    def test_desktop_artifacts_are_current(self):
        rendered = artifacts()
        self.assertEqual(rendered[JSON_PATH], JSON_PATH.read_text(encoding="utf-8"))
        self.assertEqual(rendered[JS_PATH], JS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(check(rendered), [])
        catalog = catalog_module.build_source_catalog()
        self.assertEqual(render_js(catalog), rendered[JS_PATH])
        self.assertIn("export const SOURCE_CATALOG", rendered[JS_PATH])
        # The JSON artifact is what Rust includes at compile time.
        self.assertEqual(json.loads(rendered[JSON_PATH]), catalog)

    def test_export_script_check_mode_passes(self):
        from scripts import export_source_catalog

        self.assertEqual(export_source_catalog.main(["--check"]), 0)


class ReadmeContractTests(unittest.TestCase):
    def _env_block(self) -> list[list[str]]:
        text = README.read_text(encoding="utf-8")
        marker = "环境变量会覆盖同名配置"
        section = text.split(marker, 1)[1]
        block = section.split("```text", 1)[1].split("```", 1)[0]
        return [line.split(" / ") for line in block.strip().splitlines()]

    def test_readme_env_block_matches_catalog_order_and_names(self):
        catalog = catalog_module.build_source_catalog()
        expected = list(catalog["env"]["providers"].values())
        self.assertEqual(self._env_block(), expected)

    def test_readme_documents_last_non_empty_alias_wins(self):
        text = README.read_text(encoding="utf-8")
        self.assertIn("最后一个非空值生效", text)
        self.assertIn("BRAVE_SEARCH_API_KEY", text)
        self.assertIn("`BRAVE_API_KEY`", text)
        self.assertIn("`credential_store`", text)
        self.assertIn("`keys_file`", text)
        self.assertIn("TWITTER_COOKIES_PATH", text)


if __name__ == "__main__":
    unittest.main()
