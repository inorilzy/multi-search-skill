"""Tests for the optional model-rerank stage behind ``ranking.mode``.

Every test uses a fake reranker; none of them touch the network.  The
rerank stage must be invisible when disabled and must fall back to the
complete RRF order on any adapter failure.
"""
import io
import json
import threading
import time
import unittest
import urllib.error
from unittest import mock

from multi_search_mcp.src.search.search_runner import ProviderSpec


def _rows(source, count):
    return [
        {
            "source": source,
            "title": f"{source}-{rank}",
            "url": f"https://example.com/{source}-{rank}",
            "description": f"{source} result {rank}",
            "content_kind": "excerpt",
        }
        for rank in range(1, count + 1)
    ]


def _providers(**rows_by_source):
    return {
        source: ProviderSpec(
            source, source,
            lambda _query, _config, _context, _key, rows=rows: rows,
        )
        for source, rows in rows_by_source.items()
    }


def _fused_hits(count=20):
    """Deterministic fused hits straight through the production RRF seam."""
    from multi_search_mcp.src.search.candidate import fuse_search_results

    return fuse_search_results(
        [("query", _rows("brave", count))], response_id="rerank-test", limit=count,
    )


class _FakeReranker:
    def __init__(self, scores=None, error=None, block=None, on_score=None):
        self.scores = dict(scores or {})
        self.error = error
        self.block = block  # threading.Event: wait inside score() until set
        self.on_score = on_score
        self.calls = []  # list of (batch_index -> [candidate dicts])

    def score(self, query, candidates, *, deadline):
        batch = [dict(candidate) for candidate in candidates]
        self.calls.append(batch)
        if self.on_score is not None:
            self.on_score(batch)
        if self.block is not None:
            self.block.wait(timeout=10)
        if self.error is not None:
            raise self.error
        return {
            str(candidate["source_id"]): candidate.get(
                "relevance_score",
                self.scores.get(candidate["source_id"], 0.5),
            )
            for candidate in batch
        }


class RerankPolicyTests(unittest.TestCase):
    def test_defaults_and_absent_ranking_config_mean_plain_rrf(self):
        from multi_search_mcp.src.search.rerank import RerankPolicy

        self.assertFalse(RerankPolicy.from_config({}).enabled)
        self.assertFalse(RerankPolicy.from_config({"other": {}}).enabled)
        self.assertFalse(RerankPolicy.from_config({"ranking": {}}).enabled)
        policy = RerankPolicy.from_config({"ranking": {"mode": "rrf_model"}})
        self.assertTrue(policy.enabled)

    def test_request_override_wins_and_is_validated(self):
        from multi_search_mcp.src.search.rerank import RerankPolicy
        from multi_search_mcp.src.support.config import ConfigError

        policy = RerankPolicy.from_config(
            {"ranking": {"mode": "rrf_model", "candidate_limit": 30}},
            {"candidate_limit": 12},
        )
        self.assertEqual(policy.candidate_limit, 12)
        self.assertEqual(policy.profile_id, "jev_default")
        policy = RerankPolicy.from_config({}, {"reranker_profile_id": "jev_default"})
        self.assertEqual(policy.profile_id, "jev_default")
        with self.assertRaises(ConfigError):
            RerankPolicy.from_config({}, {"mode": "bogus"})
        with self.assertRaises(ConfigError):
            RerankPolicy.from_config({}, {"unknown_knob": 1})
        with self.assertRaises(ConfigError):
            RerankPolicy.from_config({}, {"candidate_limit": 0})
        with self.assertRaises(ConfigError):
            RerankPolicy.from_config({}, {"batch_size": "lots"})
        with self.assertRaises(ConfigError):
            RerankPolicy.from_config({}, {"rerank_timeout": float("inf")})
        with self.assertRaises(ConfigError):
            RerankPolicy.from_config({"ranking": "yes"})


class ApplyRerankTests(unittest.TestCase):
    def test_scores_reorder_scored_hits_into_their_own_rrf_slots(self):
        from multi_search_mcp.src.search.rerank import (
            RerankPolicy, apply_rerank,
        )

        hits = _fused_hits(12)
        rrf_order = [hit["source_id"] for hit in hits]
        # Everything not named here scores 0.5.
        reranker = _FakeReranker({rrf_order[0]: 0.9, rrf_order[2]: 1.0})
        # The tail beyond candidate_limit (slots 10, 11) is never sent.
        policy = RerankPolicy(mode="rrf_model", candidate_limit=10, batch_size=20)

        reordered, meta = apply_rerank(
            hits, "query", reranker, policy=policy,
            deadline=time.monotonic() + 5,
        )

        self.assertEqual(meta["mode_used"], "rrf_model")
        self.assertIsNone(meta["fallback_reason"])
        # Scored slots 0-9 reorder by score (ties keep RRF order); the
        # unscored tail never moves.
        self.assertEqual(
            [hit["source_id"] for hit in reordered],
            [rrf_order[2], rrf_order[0], rrf_order[1]] + rrf_order[3:],
        )
        self.assertEqual(reordered[0]["relevance_score"], 1.0)
        self.assertEqual(reordered[1]["relevance_score"], 0.9)
        self.assertIsNone(reordered[10]["relevance_score"])
        self.assertIsNone(reordered[11]["relevance_score"])

    def test_model_only_sees_public_candidate_fields(self):
        from multi_search_mcp.src.search.rerank import (
            RerankPolicy, apply_rerank,
        )

        hits = _fused_hits(3)
        reranker = _FakeReranker({hit["source_id"]: 0.5 for hit in hits})
        apply_rerank(
            hits, "query", reranker,
            policy=RerankPolicy(mode="rrf_model"), deadline=time.monotonic() + 5,
        )
        self.assertEqual(len(reranker.calls), 1)
        for candidate in reranker.calls[0]:
            self.assertEqual(
                set(candidate),
                {"source_id", "url", "title", "content", "published_at"},
            )

    def test_batches_keep_one_scoring_standard_and_identity_per_id(self):
        from multi_search_mcp.src.search.rerank import (
            RerankPolicy, apply_rerank,
        )

        hits = _fused_hits(5)
        reranker = _FakeReranker({hit["source_id"]: 0.5 for hit in hits})
        apply_rerank(
            hits, "query", reranker,
            policy=RerankPolicy(mode="rrf_model", batch_size=2),
            deadline=time.monotonic() + 5,
        )
        self.assertEqual([len(batch) for batch in reranker.calls], [2, 2, 1])
        # Scores returned map to candidate ids, not positions.
        seen = {c["source_id"] for batch in reranker.calls for c in batch}
        self.assertEqual(seen, {hit["source_id"] for hit in hits})


class ApplyRerankFallbackTests(unittest.TestCase):
    def _check(self, reranker, reason, hits=None, budget=5.0):
        from multi_search_mcp.src.search.rerank import (
            RerankPolicy, apply_rerank,
        )

        hits = hits if hits is not None else _fused_hits(6)
        original = [hit["source_id"] for hit in hits]
        reordered, meta = apply_rerank(
            hits, "query", reranker,
            policy=RerankPolicy(mode="rrf_model", batch_size=3),
            deadline=time.monotonic() + budget,
        )
        self.assertEqual([hit["source_id"] for hit in reordered], original)
        self.assertEqual(meta["mode_used"], "rrf")
        self.assertEqual(meta["mode_requested"], "rrf_model")
        self.assertEqual(meta["fallback_reason"], reason)
        self.assertTrue(all(hit["relevance_score"] is None for hit in reordered))

    def test_missing_id_fails_the_whole_stage(self):
        hits = _fused_hits(4)
        reranker = _FakeReranker()
        # Simulate an adapter that omits one candidate id.
        reranker.score = lambda q, c, *, deadline: {
            str(x["source_id"]): 0.5 for x in c[1:]
        }
        self._check(reranker, "invalid_response", hits)

    def test_unknown_id_fails_the_whole_stage(self):
        hits = _fused_hits(4)
        reranker = _FakeReranker({hit["source_id"]: 0.5 for hit in hits})
        base = reranker.score

        def add_bogus(q, c, *, deadline):
            return {**base(q, c, deadline=deadline), "src_bogus": 0.5}
        reranker.score = add_bogus
        self._check(reranker, "invalid_response", hits)

    def test_non_finite_and_out_of_range_scores_fail_the_whole_stage(self):
        hits = _fused_hits(4)
        for bad in (float("nan"), float("inf"), -0.1, 1.1, True, "0.9"):
            with self.subTest(bad=bad):
                scores = {hit["source_id"]: 0.5 for hit in hits}
                scores[hits[0]["source_id"]] = bad
                self._check(_FakeReranker(scores), "invalid_response", hits)

    def test_second_batch_failure_restores_full_rrf_order(self):
        from multi_search_mcp.src.search.rerank import RerankError

        hits = _fused_hits(4)
        order = [hit["source_id"] for hit in hits]
        good = {order[0]: 0.1, order[1]: 0.2}
        bad = {order[2]: 0.3, order[3]: 0.4}

        def flaky(q, candidates, *, deadline):
            ids = {str(c["source_id"]) for c in candidates}
            if ids <= set(good):
                return {i: good[i] for i in ids}
            raise RerankError("rate_limit")
        # batch 1 succeeds, batch 2 is rate-limited: nothing may be applied.
        reranker = _FakeReranker()
        reranker.score = flaky
        self._check(reranker, "rate_limit", hits)

    def test_timeout_returns_rrf_order(self):
        hits = _fused_hits(3)
        # The adapter outlives the stage deadline: abandon and fall back.
        release = threading.Event()
        reranker = _FakeReranker(
            {hit["source_id"]: 0.5 for hit in hits}, block=release,
        )
        try:
            self._check(reranker, "timeout", hits, budget=0.05)
        finally:
            release.set()
        # The deadline variant: stage deadline already elapsed before scoring.
        from multi_search_mcp.src.search.rerank import (
            RerankPolicy, apply_rerank,
        )
        reordered, meta = apply_rerank(
            hits, "query", _FakeReranker(),
            policy=RerankPolicy(mode="rrf_model"),
            deadline=time.monotonic() - 1,
        )
        self.assertEqual(meta["fallback_reason"], "timeout")
        self.assertEqual(
            [h["source_id"] for h in reordered],
            [h["source_id"] for h in hits],
        )

    def test_adapter_exception_maps_to_unavailable(self):
        self._check(_FakeReranker(error=RuntimeError("boom")), "unavailable")

    def test_no_reranker_is_unavailable_fallback(self):
        self._check(None, "unavailable")

    def test_unscored_hit_keeps_none_not_zero(self):
        from multi_search_mcp.src.search.rerank import (
            RerankPolicy, apply_rerank,
        )

        hits = _fused_hits(14)
        scored = hits[:10]
        reranker = _FakeReranker({hit["source_id"]: 0.0 for hit in scored})
        reordered, meta = apply_rerank(
            hits, "query", reranker,
            policy=RerankPolicy(mode="rrf_model", candidate_limit=10),
            deadline=time.monotonic() + 5,
        )
        self.assertEqual(meta["mode_used"], "rrf_model")
        self.assertEqual(reordered[0]["relevance_score"], 0.0)
        self.assertIsNotNone(reordered[0]["relevance_score"])
        for hit in reordered[10:]:
            self.assertIsNone(hit["relevance_score"])
            self.assertNotEqual(hit["relevance_score"], 0.0)


class JevRerankerTests(unittest.TestCase):
    def test_missing_api_key_fails_closed_as_auth(self):
        from multi_search_mcp.src.search.rerank import JevReranker, RerankError

        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop(JevReranker.KEY_ENV, None)
            with self.assertRaises(RerankError) as ctx:
                JevReranker().score("q", [{"source_id": "s1"}], deadline=time.monotonic() + 5)
        self.assertEqual(ctx.exception.reason, "auth")

    def test_http_error_classification(self):
        from multi_search_mcp.src.search.rerank import JevReranker, RerankError

        def opener_for(code):
            def opener(_req, **_kw):
                body = io.BytesIO(b"")
                try:
                    raise urllib.error.HTTPError("u", code, "m", {}, body)
                finally:
                    body.close()
            return opener

        for code, reason in ((401, "auth"), (403, "auth"), (429, "rate_limit"), (500, "unavailable")):
            with self.subTest(code=code):
                reranker = JevReranker(api_key="k", opener=opener_for(code))
                with self.assertRaises(RerankError) as ctx:
                    reranker.score("q", [{"source_id": "s1"}], deadline=time.monotonic() + 5)
                self.assertEqual(ctx.exception.reason, reason)

    def test_grades_normalize_and_payload_names_single_candidates(self):
        from multi_search_mcp.src.search.rerank import JevReranker

        captured = {}

        def opener(req, **_kw):
            captured["payload"] = json.loads(req.data.decode())
            return io.BytesIO(json.dumps({
                "scores": [{"id": "a", "grade": 4}, {"id": "b", "grade": 1}],
            }).encode())

        reranker = JevReranker(api_key="k", opener=opener)
        scores = reranker.score(
            "q", [{"source_id": "a"}, {"source_id": "b"}],
            deadline=time.monotonic() + 5,
        )
        self.assertEqual(scores, {"a": 1.0, "b": 0.25})
        self.assertEqual(captured["payload"]["model"], "jev-1.14.0")
        instructions = [q["instructions"] for q in captured["payload"]["questions"]]
        self.assertIn("仅评价候选 a", instructions[0])
        self.assertIn("仅评价候选 b", instructions[1])

    def test_defensive_response_parsing(self):
        from multi_search_mcp.src.search.rerank import JevReranker, RerankError

        def reranker_for(body):
            return JevReranker(
                api_key="k",
                opener=lambda _req, **_kw: io.BytesIO(json.dumps(body).encode()),
            )

        candidates = [{"source_id": "a"}, {"source_id": "b"}]
        for body in (
            {},
            {"scores": [{"id": "a", "grade": 1}]},                # missing id
            {"scores": [{"id": "a", "grade": 1}, {"id": "z", "grade": 1}]},  # unknown id
            {"scores": [{"id": "a", "grade": 5}, {"id": "b", "grade": 1}]},  # out of range
            {"scores": [{"id": "a", "grade": float("nan")}, {"id": "b", "grade": 1}]},
        ):
            with self.subTest(body=body):
                with self.assertRaises(RerankError) as ctx:
                    reranker_for(body).score("q", candidates, deadline=time.monotonic() + 5)
                self.assertEqual(ctx.exception.reason, "invalid_response")


class CandidatesIntegrationTests(unittest.TestCase):
    def _run(self, *, ranking=None, reranker=None, count=30):
        from multi_search_mcp.src.service import (
            SearchWebRequest, run_search_candidates,
        )

        request = SearchWebRequest(
            query="q", sources=["brave", "tavily"], count=count,
            use_state=False, ranking=ranking,
        )
        return run_search_candidates(
            request,
            providers=_providers(
                brave=_rows("brave", count), tavily=_rows("tavily", count),
            ),
            keys={}, config={}, reranker=reranker,
        )

    def test_default_mode_never_calls_the_reranker(self):
        reranker = _FakeReranker({})
        response = self._run(reranker=reranker)
        self.assertEqual(reranker.calls, [])
        self.assertEqual(response["mode_requested"], "rrf")
        self.assertEqual(response["mode_used"], "rrf")
        self.assertIsNone(response["fallback_reason"])
        self.assertEqual(len(response["results"]), 15)

    def test_rerank_reorders_and_reports_scores(self):
        baseline = self._run()
        self.assertEqual(
            baseline["results"][0]["canonical_url"],
            "https://example.com/brave-1",
        )
        third_url = baseline["results"][2]["canonical_url"]
        reranker = _FakeReranker(on_score=lambda batch: [
            candidate.update(
                relevance_score=1.0
                if candidate["url"] == third_url else 0.5
            )
            for candidate in batch
        ])
        response = self._run(
            ranking={"mode": "rrf_model"}, reranker=reranker,
        )
        self.assertEqual(response["mode_used"], "rrf_model")
        self.assertEqual(len(response["results"]), 15)
        self.assertEqual(response["results"][0]["canonical_url"], third_url)
        self.assertEqual(response["results"][0]["relevance_score"], 1.0)
        for hit in response["results"]:
            self.assertIn("relevance_score", hit)
        # RRF order elsewhere preserved after the promoted hit's own slot swap.
        self.assertEqual(
            response["results"][1]["canonical_url"],
            "https://example.com/brave-1",
        )

    def test_rerank_failure_keeps_rrf_order_in_response(self):
        from multi_search_mcp.src.search.rerank import RerankError

        baseline = self._run()
        response = self._run(
            ranking={"mode": "rrf_model"},
            reranker=_FakeReranker(error=RerankError("auth")),
        )
        self.assertEqual(response["mode_used"], "rrf")
        self.assertEqual(response["fallback_reason"], "auth")
        # source_id is response-scoped, so compare stable URL identity.
        self.assertEqual(
            [hit["canonical_url"] for hit in response["results"]],
            [hit["canonical_url"] for hit in baseline["results"]],
        )

    def test_rerank_happens_before_fetch_stage(self):
        from multi_search_mcp.src.service import SearchWebRequest, run_search_web

        baseline = self._run()
        winner_url = baseline["results"][2]["canonical_url"]
        reranker = _FakeReranker(on_score=lambda batch: [
            candidate.update(
                relevance_score=1.0
                if candidate["url"] == winner_url else 0.5
            )
            for candidate in batch
        ])
        fetched = []

        def capture(hits, **kw):
            fetched.extend(h["source_id"] for h in hits)
            return {"results": [{} for _h in hits]}

        with mock.patch(
            "multi_search_mcp.src.search_web.run_ranked_fetch_stage",
            side_effect=capture,
        ):
            response = run_search_web(
                SearchWebRequest(
                    query="q", sources=["brave", "tavily"], count=30,
                    use_state=False, ranking={"mode": "rrf_model"},
                ),
                providers=_providers(
                    brave=_rows("brave", 30), tavily=_rows("tavily", 30),
                ),
                keys={}, config={}, reranker=reranker,
            )
        # The fetch stage received the reranked order, not the RRF order.
        self.assertEqual(response["results"][0]["canonical_url"], winner_url)
        self.assertEqual(response["mode_used"], "rrf_model")
        self.assertTrue(fetched)
        fetched_urls = {
            hit["source_id"]: hit["canonical_url"]
            for hit in response["results"]
        }
        self.assertEqual(fetched_urls[fetched[0]], winner_url)


class FusionInvariantTests(unittest.TestCase):
    def test_rrf_constant_is_still_40_and_snapshots_replay(self):
        from multi_search_mcp.src.search.candidate import RRF_RANK_CONSTANT
        from multi_search_mcp.src.search.snapshots import (
            capture_snapshot, replay_snapshot,
        )

        self.assertEqual(RRF_RANK_CONSTANT, 40)
        providers = _providers(brave=_rows("brave", 5))
        snapshot = capture_snapshot(
            {"query": "question", "sources": ["brave"], "use_state": False},
            expand=[], providers=providers, keys={}, config={},
        )
        self.assertEqual(snapshot["fusion"]["rank_constant"], 40)
        results = replay_snapshot(snapshot)["results"]
        self.assertEqual(len(results), 5)
        self.assertEqual(results[0]["canonical_url"], "https://example.com/brave-1")


class _FakeJevOpener:
    """Stands in for the HTTP transport of the real ``JevReranker``.

    It answers every question with grade 4 for the first id it sees and
    grade 1 for the rest, and records each request so tests can prove the
    adapter really sent one.
    """

    def __init__(self):
        self.requests = []

    def __call__(self, request, **_kwargs):
        payload = json.loads(request.data.decode("utf-8"))
        self.requests.append({
            "url": request.full_url,
            "auth": request.get_header("Authorization"),
            "payload": payload,
        })
        ids = [question["id"] for question in payload["questions"]]
        grades = [
            {"id": source_id, "grade": 4 if index == len(ids) - 1 else 1}
            for index, source_id in enumerate(ids)
        ]
        return io.BytesIO(json.dumps({"scores": grades}).encode("utf-8"))


class CoreAdapterConstructionTests(unittest.TestCase):
    """F1: core builds the adapter itself from the merged policy."""

    def _run(self, *, ranking=None, config=None, factory=None):
        from multi_search_mcp.src.search import rerank
        from multi_search_mcp.src.service import (
            SearchWebRequest, run_search_candidates,
        )

        registry = (
            {rerank.DEFAULT_RERANKER_PROFILE: factory}
            if factory is not None else dict(rerank.RERANKER_PROFILES)
        )
        with mock.patch.dict(rerank.RERANKER_PROFILES, registry, clear=True):
            return run_search_candidates(
                SearchWebRequest(
                    query="q", sources=["brave"], count=12,
                    use_state=False, ranking=ranking,
                ),
                providers=_providers(brave=_rows("brave", 12)),
                keys={}, config=config or {},
            )

    def test_rrf_model_without_injection_calls_the_real_adapter(self):
        from multi_search_mcp.src.search.rerank import JevReranker

        opener = _FakeJevOpener()
        with mock.patch.dict("os.environ", {JevReranker.KEY_ENV: "test-key"}):
            response = self._run(
                ranking={"mode": "rrf_model"},
                factory=lambda: JevReranker(opener=opener),
            )
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(opener.requests[0]["auth"], "Bearer test-key")
        self.assertTrue(opener.requests[0]["url"].endswith("/v1/systemone"))
        self.assertEqual(response["mode_requested"], "rrf_model")
        self.assertEqual(response["mode_used"], "rrf_model")
        self.assertIsNone(response["fallback_reason"])
        # The last RRF candidate got grade 4 -> promoted to slot 0.
        self.assertEqual(
            response["results"][0]["canonical_url"], "https://example.com/brave-12",
        )
        self.assertEqual(response["results"][0]["relevance_score"], 1.0)
        self.assertEqual(response["results"][1]["relevance_score"], 0.25)

    def test_rrf_model_without_key_falls_back_auth(self):
        from multi_search_mcp.src.search.rerank import JevReranker

        opener = _FakeJevOpener()
        with mock.patch.dict("os.environ", {JevReranker.KEY_ENV: ""}):
            response = self._run(
                ranking={"mode": "rrf_model"},
                factory=lambda: JevReranker(opener=opener),
            )
        self.assertEqual(opener.requests, [])
        self.assertEqual(response["mode_used"], "rrf")
        # "auth" proves the adapter ran; "unavailable" would mean no adapter.
        self.assertEqual(response["fallback_reason"], "auth")
        self.assertTrue(all(h["relevance_score"] is None for h in response["results"]))

    def test_config_file_only_switch_still_reranks(self):
        # The desktop toggle writes only the config file; the request carries
        # no override. Core must still build and call the adapter.
        from multi_search_mcp.src.search.rerank import JevReranker

        opener = _FakeJevOpener()
        with mock.patch.dict("os.environ", {JevReranker.KEY_ENV: "test-key"}):
            response = self._run(
                ranking=None,
                config={"ranking": {
                    "mode": "rrf_model", "reranker_profile_id": "jev_default",
                    "candidate_limit": 50, "batch_size": 20, "rerank_timeout": 5,
                }},
                factory=lambda: JevReranker(opener=opener),
            )
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(response["mode_used"], "rrf_model")

    def test_default_rrf_never_builds_reads_key_or_networks(self):
        from multi_search_mcp.src.search.rerank import JevReranker

        factory = mock.Mock(side_effect=AssertionError("must not construct"))
        # The key is only ever read inside JevReranker.score; trap it too.
        with mock.patch.object(
            JevReranker, "score", side_effect=AssertionError("key read"),
        ) as score, mock.patch(
            "socket.socket.connect", side_effect=AssertionError("network"),
        ) as connect:
            for ranking, config in (
                (None, {}),
                ({"mode": "rrf"}, {}),
                (None, {"ranking": {"mode": "rrf"}}),
            ):
                with self.subTest(ranking=ranking, config=config):
                    response = self._run(
                        ranking=ranking, config=config, factory=factory,
                    )
                    self.assertEqual(response["mode_used"], "rrf")
                    self.assertIsNone(response["fallback_reason"])
        factory.assert_not_called()
        score.assert_not_called()
        connect.assert_not_called()

    def test_injected_reranker_takes_precedence_over_registry(self):
        from multi_search_mcp.src.search import rerank
        from multi_search_mcp.src.service import (
            SearchWebRequest, run_search_candidates,
        )

        factory = mock.Mock(side_effect=AssertionError("must not construct"))
        fake = _FakeReranker()
        with mock.patch.dict(
            rerank.RERANKER_PROFILES,
            {rerank.DEFAULT_RERANKER_PROFILE: factory}, clear=True,
        ):
            response = run_search_candidates(
                SearchWebRequest(
                    query="q", sources=["brave"], count=12, use_state=False,
                    ranking={"mode": "rrf_model"},
                ),
                providers=_providers(brave=_rows("brave", 12)),
                keys={}, config={}, reranker=fake,
            )
        factory.assert_not_called()
        self.assertTrue(fake.calls)
        self.assertEqual(response["mode_used"], "rrf_model")

    def test_build_reranker_uses_the_registry(self):
        from multi_search_mcp.src.search.rerank import (
            JevReranker, RERANKER_PROFILES, build_reranker,
        )
        from multi_search_mcp.src.support.config import ConfigError

        self.assertEqual(set(RERANKER_PROFILES), {"jev_default"})
        self.assertIsInstance(build_reranker("jev_default"), JevReranker)
        for bad in ("jev", "bogus", ""):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                build_reranker(bad)


class ProfileIdentityTests(unittest.TestCase):
    """F2: one authoritative profile id, shared with the desktop editor."""

    def test_core_accepts_jev_default_and_rejects_others(self):
        from multi_search_mcp.src.search.rerank import RerankPolicy
        from multi_search_mcp.src.support.config import ConfigError

        self.assertEqual(RerankPolicy().profile_id, "jev_default")
        policy = RerankPolicy.from_config(
            {"ranking": {"mode": "rrf_model", "reranker_profile_id": "jev_default"}},
        )
        self.assertEqual(policy.profile_id, "jev_default")
        for bad in ("jev", "JEV_DEFAULT", "bogus", "", None, 7):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                RerankPolicy.from_config({}, {"reranker_profile_id": bad})

    def test_cli_unknown_profile_exits_2(self):
        import multi_search_mcp.cli as cli

        for bad in ("jev", "bogus"):
            with self.subTest(bad=bad), \
                 mock.patch.object(cli, "run_search_web") as run:
                stdout, stderr = io.StringIO(), io.StringIO()
                code = cli.main(
                    ["search", "q", "--rerank", "--rerank-profile", bad],
                    stdout=stdout, stderr=stderr,
                )
                self.assertEqual(code, 2)
                self.assertIn("unknown rerank profile", stderr.getvalue())
                run.assert_not_called()

    def test_cli_has_no_private_profile_list(self):
        import multi_search_mcp.cli as cli
        import multi_search_mcp.tools as tools

        self.assertFalse(hasattr(cli, "KNOWN_RERANK_PROFILES"))
        self.assertFalse(hasattr(cli, "_reranker_for"))
        self.assertFalse(hasattr(tools, "_reranker_for"))


# Mirrors desktop/src-tauri/src/settings.rs RANKING_*_MIN/MAX. If either side
# changes, this set and the desktop constants must move together.
DESKTOP_RANKING_BOUNDS = {
    "candidate_limit": (10, 200),
    "batch_size": (1, 50),
    "rerank_timeout": (1, 60),
}


class NumericBoundsTests(unittest.TestCase):
    """F3: core enforces exactly the desktop editor's ranges."""

    CASES = {
        "candidate_limit": {9: False, 10: True, 200: True, 201: False},
        "batch_size": {0: False, 1: True, 50: True, 51: False},
        "rerank_timeout": {0: False, 1: True, 60: True, 61: False},
    }

    def test_boundary_values(self):
        from multi_search_mcp.src.search.rerank import RerankPolicy
        from multi_search_mcp.src.support.config import ConfigError

        for key, cases in self.CASES.items():
            for value, accepted in cases.items():
                with self.subTest(key=key, value=value):
                    config = {"ranking": {"mode": "rrf_model", key: value}}
                    if accepted:
                        policy = RerankPolicy.from_config(config)
                        self.assertEqual(getattr(policy, key), value)
                    else:
                        with self.assertRaises(ConfigError):
                            RerankPolicy.from_config(config)

    def test_core_ranges_match_desktop_ranges(self):
        from multi_search_mcp.src.search import rerank

        self.assertEqual(
            {
                "candidate_limit": rerank.CANDIDATE_LIMIT_RANGE,
                "batch_size": rerank.BATCH_SIZE_RANGE,
                "rerank_timeout": rerank.RERANK_TIMEOUT_RANGE,
            },
            DESKTOP_RANKING_BOUNDS,
        )

    def test_every_core_accepted_value_is_desktop_valid(self):
        from multi_search_mcp.src.search.rerank import RerankPolicy
        from multi_search_mcp.src.support.config import ConfigError

        defaults = RerankPolicy()
        for key, (low, high) in DESKTOP_RANKING_BOUNDS.items():
            self.assertTrue(low <= getattr(defaults, key) <= high, key)
            for value in range(low - 5, high + 6):
                try:
                    RerankPolicy.from_config({}, {key: value})
                except ConfigError:
                    self.assertFalse(low <= value <= high, (key, value))
                else:
                    self.assertTrue(low <= value <= high, (key, value))


if __name__ == "__main__":
    unittest.main()
