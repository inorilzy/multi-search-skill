"""disabled_sources written by the desktop settings file is honored by the real search service.

The config is loaded from a file in the same shape the desktop settings writer produces
(known keys plus an unknown field that must survive). Every searcher is faked on the registry;
no network call, no real key, no real user config or state is touched.
"""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.search import registry
from multi_search_mcp.src.search.search_runner import ALL_SOURCE_NAMES
from multi_search_mcp.src.service import run_search_web
from multi_search_mcp.src.support.config import load_config


DEFAULT_ROUTE_SOURCES = {"baidu", "brave", "exa", "firecrawl", "parallel", "serpapi", "tavily"}
SYNTHETIC_KEYS = {"baidu": "synthetic-baidu-0601", "brave": "synthetic-brave-0602"}


def _row(name):
    return {
        "source": name,
        "title": f"{name}-hit",
        "url": f"https://example.invalid/{name}",
        "snippet": "fixture",
        "content_kind": "snippet",
    }


class DisabledSourcesConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_file = Path(self.tmp.name) / "multi-search-config.json"
        self.calls: list[str] = []
        with ExitStack() as stack:
            for name in ALL_SOURCE_NAMES:
                stack.enter_context(mock.patch.object(registry, f"search_{name}", self._fake(name)))
            self.addCleanup(stack.pop_all().close)

    def _fake(self, name):
        def fake(*_args, **_kwargs):
            self.calls.append(name)
            if name == "brave":
                raise RuntimeError("fixture brave unavailable")
            return [_row(name)]

        return fake

    def write_desktop_config(self, data):
        self.config_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return load_config(str(self.config_file))

    def search(self, config, sources=None):
        request = {"query": "fixture", "use_state": False, "count": 1}
        if sources:
            request["sources"] = sources
        return run_search_web(request, keys=dict(SYNTHETIC_KEYS), config=config)

    def test_disabled_sources_are_not_called_and_partial_results_survive(self):
        disabled = sorted(DEFAULT_ROUTE_SOURCES - {"baidu", "brave"})
        config = self.write_desktop_config({
            "type": "default",
            "timeout": 30,
            "disabled_sources": disabled,
            "count": 3,
            "custom_note": "kept",
        })
        response = self.search(config)
        self.assertEqual(sorted(self.calls), ["baidu", "brave"])
        self.assertEqual(response["diagnostics"]["active_sources"], ["baidu", "brave"])
        self.assertEqual(response["diagnostics"]["disabled_sources"], disabled)
        self.assertEqual([row["source"] for row in response["provider_status"]], ["baidu", "brave"])
        self.assertIn("baidu-hit", [hit["title"] for hit in response["results"]])
        self.assertTrue(response["errors"], "brave failure must stay visible")
        self.assertEqual(json.loads(self.config_file.read_text(encoding="utf-8"))["custom_note"], "kept")

    def test_explicit_source_that_is_disabled_is_not_silently_reenabled(self):
        config = self.write_desktop_config({"type": "default", "disabled_sources": ["brave"]})
        with self.assertRaises(ValueError) as ctx:
            self.search(config, sources=["brave"])
        self.assertIn("all selected sources are disabled: brave", str(ctx.exception))
        self.assertEqual(self.calls, [])

    def test_explicit_disabled_source_is_dropped_while_enabled_one_runs(self):
        config = self.write_desktop_config({"type": "default", "disabled_sources": ["brave"]})
        response = self.search(config, sources=["baidu", "brave"])
        self.assertEqual(response["diagnostics"]["active_sources"], ["baidu"])
        self.assertEqual(self.calls, ["baidu"])

    def test_empty_selection_after_disabling_the_route_is_an_explicit_error(self):
        config = self.write_desktop_config({"type": "social", "disabled_sources": ["twitter"]})
        with self.assertRaises(ValueError) as ctx:
            self.search(config)
        self.assertIn("all selected sources are disabled: twitter", str(ctx.exception))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
