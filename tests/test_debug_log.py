import json
import os
import unittest
from contextlib import ExitStack
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.scrape import scrape
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.state import state_store
from multi_search_mcp.src.support import debug_log


SECRET = "sk-debug-secret-0123456789"


def _provider(source, rows_by_query):
    def search(query, config, context, key):
        return [dict(row) for row in rows_by_query.get(query, [])]

    return ProviderSpec(name=source, public_name=source, call=search)


def _row(source, name):
    return {
        "source": source,
        "title": f"Title {name}",
        "url": f"https://evidence.example/{name}",
        "description": f"Snippet for {name}",
        "content_kind": "excerpt",
    }


class DebugLogTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.addCleanup(debug_log.disable)
        temp = Path(self.stack.enter_context(TemporaryDirectory(prefix="debug-log-")))
        self.log_path = temp / "trace.jsonl"
        self.stack.enter_context(mock.patch.object(state_store, "DEFAULT_STATE_PATH", temp / "state.sqlite"))
        self.stack.enter_context(mock.patch("multi_search_mcp.src.state.runtime.load_config", return_value={}))
        self.stack.enter_context(mock.patch(
            "multi_search_mcp.src.state.runtime.load_keys", return_value={"brave": SECRET},
        ))
        self.stack.enter_context(mock.patch.dict(os.environ, {debug_log.ENV_VAR: ""}))
        self.stack.enter_context(mock.patch("socket.getaddrinfo", side_effect=AssertionError("unexpected DNS")))
        self.stack.enter_context(mock.patch("socket.socket.connect", side_effect=AssertionError("unexpected connection")))
        providers = {
            "brave": _provider("brave", {
                "primary": [_row("brave", "one")],
                "variant": [_row("brave", "two")],
            }),
            "exa": _provider("exa", {
                "primary": [{"source": "exa", "error": f"auth failed for {SECRET}"}],
                "variant": [],
            }),
        }
        self.stack.enter_context(mock.patch(
            "multi_search_mcp.src.search.registry.build_provider_registry", return_value=providers,
        ))
        self.stack.enter_context(mock.patch.object(scrape, "_jina_anonymous_cooling_down", return_value=False))
        self.stack.enter_context(mock.patch.object(
            scrape, "scrape_url_jina",
            side_effect=lambda url, *args, **kwargs: {"url": url, "error": "fixture target unavailable"},
        ))
        self.stack.enter_context(mock.patch.object(
            scrape, "scrape_url_firecrawl",
            side_effect=lambda url, key, **kwargs: {"url": url, "markdown": f"Body of {url}"},
        ))
        for name in ("scrape_url_exa", "scrape_url_tavily"):
            self.stack.enter_context(mock.patch.object(scrape, name, side_effect=AssertionError(name)))

    def _search(self, *extra):
        output, errors = StringIO(), StringIO()
        code = cli.main(
            ["search", "--source", "brave", "--source", "exa", "--expand", " variant ",
             "--expand", "primary", "--no-state", *extra, "--format", "json", "--", "primary"],
            stdout=output, stderr=errors,
        )
        self.assertEqual(code, 0, errors.getvalue())
        return json.loads(output.getvalue())

    def _events(self):
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]

    def test_search_trace_covers_parameters_plan_route_timings_results_and_fetch_chain(self):
        payload = self._search("--debug-log", str(self.log_path))
        events = self._events()
        kinds = [event["event"] for event in events]
        self.assertEqual(kinds[0], "cli_request")
        self.assertEqual(kinds[-1], "cli_exit")
        self.assertEqual(len({event["run_id"] for event in events}), 1)
        by_kind = {}
        for event in events:
            by_kind.setdefault(event["event"], []).append(event)

        request = by_kind["cli_request"][0]
        self.assertEqual(request["parameters"]["query"], "primary")
        self.assertEqual(request["parameters"]["expand"], [" variant ", "primary"])

        plan = by_kind["query_plan"][0]
        self.assertEqual(plan["expand_input"], [" variant ", "primary"])
        self.assertEqual(plan["executed_queries"], ["primary", "variant"])
        self.assertEqual(plan["duplicate_count"], 1)

        route = by_kind["route"][0]
        self.assertEqual(route["active_sources"], ["brave", "exa"])

        results = {(row["query"], row["source"]): row for row in by_kind["provider_result"]}
        self.assertEqual(results[("primary", "brave")]["rows"][0]["url"], "https://evidence.example/one")
        self.assertIsInstance(results[("primary", "brave")]["elapsed_ms"], int)
        self.assertEqual(results[("primary", "exa")]["status"], "error")
        self.assertEqual({row["query"] for row in by_kind["query_done"]}, {"primary", "variant"})
        self.assertEqual(len(by_kind["fusion"][0]["candidates"]), 2)

        chain = by_kind["scrape_chain"][0]
        self.assertEqual(chain["order"][:2], ["jina", "exa"])
        attempts = [(row["url"], row["backend"], row["status"]) for row in by_kind["scrape_attempt"]]
        self.assertIn(("https://evidence.example/one", "jina", "error"), attempts)
        self.assertIn(("https://evidence.example/one", "firecrawl", "ok"), attempts)
        fetched = {row["url"]: row for row in by_kind["fetch_source"]}
        self.assertEqual(fetched["https://evidence.example/one"]["backend"], "firecrawl")
        self.assertEqual(fetched["https://evidence.example/one"]["how"], "scrape")

        response = by_kind["search_response"][0]
        self.assertEqual(response["result_count"], len(payload["results"]))
        self.assertTrue(response["results"][0]["body_preview"].startswith("Body of https://"))

        text = self.log_path.read_text(encoding="utf-8")
        self.assertNotIn(SECRET, text)
        self.assertIn("<redacted>", text)

    def test_environment_variable_enables_the_trace_without_the_flag(self):
        with mock.patch.dict(os.environ, {debug_log.ENV_VAR: str(self.log_path)}):
            self._search()
        self.assertIn("search_response", [event["event"] for event in self._events()])

    def test_no_trace_is_written_unless_enabled(self):
        with mock.patch.object(debug_log, "default_path", return_value=self.log_path):
            payload = self._search()
        self.assertFalse(self.log_path.exists())
        self.assertNotIn("debug_log", json.dumps(payload))

    def test_unwritable_log_never_breaks_the_search(self):
        blocker = self.log_path.parent / "not-a-dir"
        blocker.write_text("file", encoding="utf-8")
        payload = self._search("--debug-log", str(blocker / "trace.jsonl"))
        self.assertEqual(payload["outcome"], "partial")


if __name__ == "__main__":
    unittest.main()
