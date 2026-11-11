import http.client
import json
import os
import threading
import time
import unittest
from contextlib import ExitStack
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src import log_viewer
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
        self.runs_dir = temp / "runs"
        # Traces must never reach the real home directory.
        self.stack.enter_context(mock.patch.object(debug_log, "runs_dir", return_value=self.runs_dir))
        self.stack.enter_context(mock.patch.object(state_store, "DEFAULT_STATE_PATH", temp / "state.sqlite"))
        # The desktop's page-05 switch, as stored in the shared settings.
        self.config = {"debug_log": True}
        self.stack.enter_context(mock.patch(
            "multi_search_mcp.src.state.runtime.load_config", side_effect=lambda *_a, **_k: dict(self.config),
        ))
        self.stack.enter_context(mock.patch(
            "multi_search_mcp.src.state.runtime.load_keys", return_value={"brave": SECRET},
        ))
        self.stack.enter_context(mock.patch.dict(os.environ, {debug_log.ENV_VAR: ""}))
        self.network_guard = ExitStack()
        self.addCleanup(self.network_guard.close)
        self.network_guard.enter_context(mock.patch("socket.getaddrinfo", side_effect=AssertionError("unexpected DNS")))
        self.network_guard.enter_context(mock.patch("socket.socket.connect", side_effect=AssertionError("unexpected connection")))
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
        self.assertEqual(chain["order"][:3], ["jina_key", "jina_anon", "exa"])
        attempts = [(row["url"], row["backend"], row["status"]) for row in by_kind["scrape_attempt"]]
        self.assertIn(("https://evidence.example/one", "jina_anon", "error"), attempts)
        self.assertIn(("https://evidence.example/one", "firecrawl_anon", "ok"), attempts)
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

    def test_no_trace_unless_the_setting_or_environment_asks(self):
        self.config = {}
        self._search()
        self.assertFalse(self.runs_dir.exists())
        self.config = {"debug_log": False}
        self._search()
        self.assertFalse(self.runs_dir.exists())
        with mock.patch.dict(os.environ, {debug_log.ENV_VAR: "1"}):
            self._search()
        self.assertEqual(len(list(self.runs_dir.glob("*.jsonl"))), 1)

    def test_trace_state_ends_with_the_cli_invocation(self):
        self._search()
        self.assertFalse(debug_log.enabled())
        debug_log.event("late", note="written after main returned")
        text = "".join(path.read_text(encoding="utf-8") for path in self.runs_dir.glob("*.jsonl"))
        self.assertNotIn("written after main returned", text)

    def test_url_credentials_are_redacted(self):
        # The request is rejected (no model), but its parameters are logged first.
        cli.main(["search", "--debug-log", str(self.log_path), "--rerank",
                  "--rerank-base-url", "http://user:hunter2@rank.example/v1", "--", "primary"],
                 stdout=StringIO(), stderr=StringIO())
        text = self.log_path.read_text(encoding="utf-8")
        self.assertNotIn("hunter2", text)
        self.assertIn("http://<redacted>@rank.example/v1", text)

    def test_setting_on_writes_one_private_file_per_run(self):
        payload = self._search()
        self._search()
        files = sorted(self.runs_dir.glob("*.jsonl"))
        self.assertEqual(len(files), 2)
        self.assertNotIn("debug_log", json.dumps(payload))
        if os.name == "posix":
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.runs_dir.stat().st_mode & 0o777, 0o700)
        run_ids = {json.loads(line)["run_id"] for line in files[0].read_text(encoding="utf-8").splitlines()}
        self.assertEqual(len(run_ids), 1)

    def test_zero_overrides_the_setting(self):
        with mock.patch.dict(os.environ, {debug_log.ENV_VAR: "0"}):
            self._search()
        self.assertFalse(self.runs_dir.exists())

    def test_retention_keeps_newest_runs_and_drops_old_ones(self):
        self.runs_dir.mkdir()
        now = time.time()
        for index in range(5):
            path = self.runs_dir / f"run-{index}.jsonl"
            path.write_text("{}\n", encoding="utf-8")
            os.utime(path, (now - index, now - index))
        stale = self.runs_dir / "stale.jsonl"
        stale.write_text("{}\n", encoding="utf-8")
        os.utime(stale, (now - 30 * 86_400,) * 2)
        keep = self.runs_dir / "notes.txt"
        keep.write_text("not a run", encoding="utf-8")
        debug_log.prune(self.runs_dir, keep=4, max_age_days=7)
        self.assertEqual(sorted(path.name for path in self.runs_dir.iterdir()),
                         ["notes.txt", "run-0.jsonl", "run-1.jsonl", "run-2.jsonl"])

    def test_viewer_detail_answers_route_queries_providers_ranking_and_pages(self):
        self._search()
        runs = log_viewer.load_runs([self.runs_dir])
        self.assertEqual(len(runs), 1)
        run_id, events = next(iter(runs.items()))
        summary = log_viewer.list_runs(runs)[0]
        self.assertEqual((summary["query"], summary["route"], summary["outcome"]), ("primary", "default", "partial"))
        detail = log_viewer.build_detail(run_id, events)
        self.assertEqual(detail["route"]["active_sources"], ["brave", "exa"])
        self.assertEqual(detail["query_plan"]["executed_queries"], ["primary", "variant"])
        self.assertEqual({(row["query"], row["source"]) for row in detail["providers"]},
                         {("primary", "brave"), ("primary", "exa"), ("variant", "brave"), ("variant", "exa")})
        self.assertTrue(all(row["attempts"] for row in detail["providers"]))
        self.assertEqual([row["final_rank"] for row in detail["ranking"]["rows"]], [1, 2])
        self.assertEqual(detail["ranking"]["rows"][0]["provider_ranks"][0]["provider"], "brave")
        page = detail["fetches"][0]
        self.assertEqual(page["url"], detail["ranking"]["rows"][0]["url"])
        self.assertEqual([(a["backend"], a["status"]) for a in page["attempts"]],
                         [("jina_key", "skipped"), ("jina_anon", "error"), ("exa", "skipped"),
                          ("tavily", "skipped"), ("firecrawl_key", "skipped"), ("firecrawl_anon", "ok")])
        self.assertEqual(page["result"]["backend"], "firecrawl")

    def test_abandoned_fetch_is_reported_as_a_timeout(self):
        events = [
            {"run_id": "run_000000000000", "event": "scrape_chain", "url": "https://a.example/", "t_ms": 10,
             "order": ["jina", "exa"]},
            {"run_id": "run_000000000000", "event": "scrape_key_attempt", "url": "https://a.example/",
             "backend": "jina", "key_id": "anonymous", "elapsed_ms": 400, "error": "HTTP 403", "t_ms": 420},
            {"run_id": "run_000000000000", "event": "fetch_stage_done", "t_ms": 1010,
             "failures": [{"url": "https://a.example/", "error": "fetch timeout after 1s"}]},
        ]
        page = log_viewer.build_detail("run_000000000000", events)["fetches"][0]
        self.assertEqual(page["attempts"], [{"backend": "jina", "status": "timeout", "elapsed_ms": 400,
                                             "error": "HTTP 403"}])
        self.assertEqual((page["result"]["event"], page["result"]["elapsed_ms"], page["result"]["error"]),
                         ("fetch_timeout", 1000, "fetch timeout after 1s"))

    def test_viewer_server_is_loopback_only_and_serves_runs(self):
        self._search()
        self.network_guard.close()  # The viewer is reached over loopback HTTP.
        server = log_viewer.make_server([self.runs_dir], port=0)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.assertEqual(server.server_address[0], "127.0.0.1")
        port = server.server_address[1]

        def get(path, host=f"127.0.0.1:{port}"):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("GET", path, headers={"Host": host})
            response = connection.getresponse()
            body = response.read()
            connection.close()
            return response, body

        response, body = get("/")
        self.assertEqual(response.status, 200)
        self.assertIn("script-src 'self'", response.getheader("Content-Security-Policy"))
        self.assertIn(b"/app.js", body)
        runs = json.loads(get("/api/runs")[1])["runs"]
        self.assertEqual(len(runs), 1)
        detail = json.loads(get("/api/runs/" + runs[0]["run_id"])[1])
        self.assertEqual(detail["summary"]["query"], "primary")
        self.assertEqual(get("/api/runs/../../etc/passwd")[0].status, 404)
        self.assertEqual(get("/api/runs", host="attacker.example")[0].status, 403)

    def test_unwritable_log_never_breaks_the_search(self):
        blocker = self.log_path.parent / "not-a-dir"
        blocker.write_text("file", encoding="utf-8")
        payload = self._search("--debug-log", str(blocker / "trace.jsonl"))
        self.assertEqual(payload["outcome"], "partial")


if __name__ == "__main__":
    unittest.main()
