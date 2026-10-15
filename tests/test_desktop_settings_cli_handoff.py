"""Independent CLI check of a config written by the desktop settings save path.

The desktop test (desktop/src-tauri/tests/settings.rs, handoff test) writes the real saved file
and copies it to the path named by MS_SETTINGS_HANDOFF. This module then runs the CLI's own
``main()`` with MULTI_SEARCH_CONFIG_DB pointing at that database, so the CLI itself must read the
desktop-written disabled_sources and default route. Every searcher is faked on the registry,
state and keys are isolated to temp paths, and no real key, network call, or user config is used.

Without MS_SETTINGS_HANDOFF the class is skipped; the gate sets it to the handoff copy.
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.search import registry
from multi_search_mcp.src.search.search_runner import ALL_SOURCE_NAMES
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support.credential_store import ConfigDatabase, default_store

HANDOFF = os.environ.get("MS_SETTINGS_HANDOFF")
SYNTHETIC_KEYS = {"baidu": "synthetic-baidu-0701", "brave": "synthetic-brave-0702"}


@unittest.skipUnless(HANDOFF, "MS_SETTINGS_HANDOFF names the desktop-written config copy")
class DesktopWrittenConfigReadByCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.config = root / "desktop-written.sqlite"
        self.config.write_bytes(Path(HANDOFF).read_bytes())
        self.calls: list[str] = []
        self.failing = set()
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ALL_SOURCE_NAMES:
            stack.enter_context(mock.patch.object(registry, f"search_{name}", self._fake(name)))
        env = {"MULTI_SEARCH_CONFIG_DB": str(self.config), "TWITTER_COOKIES_PATH": "synthetic-ignored-environment-path"}
        stack.enter_context(mock.patch.dict(os.environ, env))
        stack.enter_context(
            mock.patch("multi_search_mcp.src.service.StateStore",
                       lambda *a, **k: StateStore(root / "state.sqlite"))
        )
        # Real runtime loading must use the same DB as settings, not an injected
        # dict. These synthetic keys are written only into the disposable copy.
        store = default_store()
        for provider, value in SYNTHETIC_KEYS.items():
            store.set(provider, value)

    def _fake(self, name):
        def fake(*_args, **_kwargs):
            self.calls.append(name)
            if name in self.failing:
                raise RuntimeError(f"fixture {name} unavailable")
            return [{
                "source": name,
                "title": f"{name}-hit",
                "url": f"https://example.invalid/{name}",
                "snippet": "fixture",
                "content_kind": "snippet",
            }]

        return fake

    def run_cli(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(["search", "fixture", "--format", "json", "--no-scrape", *extra], stdout=out, stderr=err)
        payload = json.loads(out.getvalue()) if out.getvalue().strip().startswith("{") else None
        return code, payload, err.getvalue()

    def test_cli_reads_the_desktop_written_route_timeout_and_disabled_sources(self):
        desktop = ConfigDatabase(self.config).read_settings()
        self.assertEqual(desktop["disabled_sources"], ["brave"])
        self.assertEqual(desktop["type"], "default")
        self.assertEqual(desktop["timeout"], 25)
        code, payload, _err = self.run_cli()
        self.assertEqual(payload["diagnostics"]["disabled_sources"], ["brave"])
        self.assertNotIn("brave", payload["diagnostics"]["active_sources"])
        self.assertNotIn("brave", self.calls)
        self.assertIn("baidu", self.calls)

    def test_desktop_saved_twitter_path_reaches_search_twitter_through_real_key_loading(self):
        desktop = ConfigDatabase(self.config).read_settings()
        self.assertEqual(desktop["twitter_cookies_path"], "C:/synthetic/handoff-twitter-cookies.json")
        seen = []

        def fake_twitter(query, count=10, cookies="", timeout=None, *, publish_partial=None, deadline=None):
            seen.append(cookies)
            return []

        with mock.patch.object(registry, "search_twitter", fake_twitter):
            code, payload, err = self.run_cli("--source", "twitter")
        self.assertEqual(code, 0, err)
        self.assertEqual(seen, ["C:/synthetic/handoff-twitter-cookies.json"])

    def test_explicit_disabled_source_is_not_run_and_enabled_one_still_runs(self):
        code, payload, _err = self.run_cli("--source", "brave", "--source", "baidu")
        self.assertNotIn("brave", self.calls)
        self.assertIn("baidu", self.calls)
        self.assertEqual(payload["diagnostics"]["active_sources"], ["baidu"])

    def test_explicit_only_disabled_source_is_an_explicit_error_not_a_silent_rerun(self):
        code, payload, err = self.run_cli("--source", "brave")
        self.assertEqual(code, 1)
        self.assertIn("all selected sources are disabled: brave", err)
        self.assertEqual(self.calls, [])

    def test_partial_failure_keeps_the_successful_results(self):
        # hackernews needs no key, so it succeeds while baidu fails: the CLI must report partial.
        self.failing = {"baidu"}
        code, payload, _err = self.run_cli("--source", "baidu", "--source", "hackernews")
        self.assertEqual(payload["outcome"], "partial")
        titles = [hit["title"] for hit in payload["results"]]
        self.assertIn("hackernews-hit", titles)
        self.assertTrue(payload["errors"], "baidu failure must stay visible")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
