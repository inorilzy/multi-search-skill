"""`search --progress-events`: the stage stream the desktop's search diagram reads."""
import io
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.search.search_runner import ProviderSpec, SearchRunner, SearchRunnerConfig
from multi_search_mcp.src.support import debug_log


def _events(stream: io.StringIO) -> list[dict]:
    out = []
    for line in stream.getvalue().splitlines():
        assert line.startswith(debug_log.PROGRESS_PREFIX), line
        out.append(json.loads(line[len(debug_log.PROGRESS_PREFIX):]))
    return out


class ProgressStreamTests(unittest.TestCase):
    def setUp(self):
        debug_log.configure("0")
        self.stream = io.StringIO()
        debug_log.enable_progress(self.stream)
        self.addCleanup(debug_log.disable)

    def test_only_listed_kinds_and_fields_are_written(self):
        debug_log.event("fusion", candidates=[{"url": "https://a.example"}])
        debug_log.event(
            "scrape_attempt", url="https://a.example", backend="jina_key", status="ok",
            elapsed_ms=12, content_length=40, body_preview="private page text",
        )
        events = _events(self.stream)
        self.assertEqual([event["event"] for event in events], ["scrape_attempt"])
        self.assertNotIn("body_preview", events[0])
        self.assertEqual(events[0]["backend"], "jina_key")
        self.assertIn("t_ms", events[0])

    def test_known_credentials_and_long_errors_are_scrubbed(self):
        debug_log.add_secrets({"tavily": "tvly-fixture-secret-value"})
        debug_log.event(
            "scrape_attempt", url="https://a.example", backend="tavily", status="error",
            error="401 for key tvly-fixture-secret-value " + "x" * 500,
        )
        line = self.stream.getvalue()
        self.assertNotIn("tvly-fixture-secret-value", line)
        self.assertLess(len(_events(self.stream)[0]["error"]), 260)

    def test_rerank_events_name_the_model_and_scored_count(self):
        policy = SimpleNamespace(model="typesafe/jev-1.14", candidate_limit=50)
        hits = [{"url": "u1", "relevance_score": 0.9}, {"url": "u2", "relevance_score": None}]
        started = debug_log.log_rerank_start(hits, policy)
        debug_log.log_rerank(
            hits, {"mode_requested": "rrf_model", "mode_used": "rrf_model", "fallback_reason": None},
            started, policy=policy,
        )
        start, done = _events(self.stream)
        self.assertEqual(start, {"event": "rerank_start", "t_ms": start["t_ms"],
                                 "model": "typesafe/jev-1.14", "candidate_count": 2})
        self.assertEqual(done["scored_count"], 1)
        self.assertEqual(done["mode_used"], "rrf_model")
        self.assertNotIn("order", done, "the full per-hit list stays in the file log only")

    def test_rerank_moves_report_each_candidates_rank_before_and_after(self):
        policy = SimpleNamespace(model="typesafe/jev-1.14", candidate_limit=50)
        fused = [
            {"source_id": "a", "url": "https://a.example", "title": "A"},
            {"source_id": "b", "url": "https://b.example", "title": "B" * 500},
        ]
        started = debug_log.log_rerank_start(fused, policy)
        reranked = [dict(fused[1], relevance_score=0.9), dict(fused[0], relevance_score=0.4)]
        debug_log.log_rerank(reranked, {"mode_used": "rrf_model"}, started, policy=policy)
        debug_log.log_final_order(reranked[:1])
        events = _events(self.stream)
        moves = events[1]["moves"]
        self.assertEqual([(m["key"], m["rrf_rank"], m["rank"]) for m in moves], [("b", 2, 1), ("a", 1, 2)])
        self.assertEqual(moves[0]["relevance_score"], 0.9)
        self.assertLess(len(moves[0]["title"]), 200, "titles are clipped")
        self.assertEqual(events[2], {"event": "final_order", "t_ms": events[2]["t_ms"], "keys": ["b"]})

    def test_the_stream_is_capped(self):
        with mock.patch.object(debug_log, "PROGRESS_MAX_EVENTS", 3):
            for _ in range(10):
                debug_log.event("provider_start", query="q", source="brave")
        self.assertEqual(len(_events(self.stream)), 3)

    def test_a_broken_stream_never_breaks_the_caller(self):
        class Broken:
            def write(self, _text):
                raise OSError("closed")

            def flush(self):
                pass

        debug_log.enable_progress(Broken())
        debug_log.event("provider_start", query="q", source="brave")  # must not raise

    def test_each_searcher_reports_its_own_start_and_finish(self):
        def ok(query, cfg, ctx, key):
            return [{"source": "alpha", "title": "t", "url": "https://a.example"}]

        def broken(query, cfg, ctx, key):
            raise RuntimeError("down")

        providers = {
            "alpha": ProviderSpec(name="alpha", public_name="alpha", call=ok, key_required=False),
            "beta": ProviderSpec(name="beta", public_name="beta", call=broken, key_required=False),
        }
        config = SearchRunnerConfig(route="default", counts={}, timeout=5, serpapi_engine="google", keys={})
        SearchRunner(config, providers, route_resolver=lambda _r: ["alpha", "beta"]).run("q")
        events = _events(self.stream)
        done = {event["source"]: event for event in events if event["event"] == "provider_done"}
        self.assertEqual(done["alpha"]["status"], "ok")
        self.assertEqual(done["alpha"]["hit_count"], 1)
        self.assertEqual(done["beta"]["status"], "error")
        starts = {event["source"] for event in events if event["event"] == "provider_start"}
        self.assertEqual(starts, {"alpha", "beta"})
        kinds = [event["event"] for event in events]
        self.assertLess(kinds.index("provider_done"), kinds.index("provider_result"),
                        "completion is reported before the all-sources summary")


class ProgressFlagTests(unittest.TestCase):
    def tearDown(self):
        debug_log.disable()

    def test_flag_sends_stages_to_stderr_and_leaves_stdout_one_json_document(self):
        payload = {"outcome": "success", "results": [], "errors": [], "query": "q"}

        def handler(_args):
            debug_log.event("route", resolved_route="default", active_sources=["brave"])
            return payload

        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "_handle_search", handler):
            code = cli.main(["search", "--progress-events", "--", "q"], stdout=stdout, stderr=stderr)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["outcome"], "success")
        kinds = [event["event"] for event in _events(stderr)]
        self.assertIn("route", kinds)

    def test_without_the_flag_stderr_stays_quiet(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "_handle_search", lambda _a: {"outcome": "success", "results": []}):
            cli.main(["search", "--", "q"], stdout=stdout, stderr=stderr)
        self.assertNotIn(debug_log.PROGRESS_PREFIX, stderr.getvalue())

    def test_doctor_advertises_the_protocol(self):
        stdout = io.StringIO()
        cli.main(["doctor", "--no-keys", "--format", "json"], stdout=stdout, stderr=io.StringIO())
        self.assertEqual(
            json.loads(stdout.getvalue())["search_progress"],
            {"prefix": debug_log.PROGRESS_PREFIX, "schema_version": 1},
        )


if __name__ == "__main__":
    unittest.main()
