"""Deadline coverage for the optional model-rerank stage.

The rerank stage reads its HTTP response under ``rerank_timeout``: a server
that drips its body cannot keep a worker thread alive past the budget.  Batch
results are judged in completion order, so a fast failure falls back to RRF
without waiting for a slower sibling batch.
"""
import http.server
import threading
import time
import unittest
from unittest import mock

from multi_search_mcp.src.search.rerank import (
    RerankError,
    RerankPolicy,
    SystemOneReranker,
    apply_rerank,
)
from multi_search_mcp.src.support.concurrency import BoundedDaemonExecutor


def _hits(count):
    return [
        {
            "source_id": f"s{index}",
            "url": f"https://example.com/{index}",
            "title": f"title {index}",
            "content": "snippet",
        }
        for index in range(count)
    ]


class _DripServer:
    """Serve one System One endpoint whose response body drips byte by byte."""

    def __init__(self):
        self._stop = threading.Event()
        stop = self._stop

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                # Under the 8 MiB body cap, so only a deadline-aware read can
                # stop this response from running forever.
                self.send_header("Content-Length", "7000000")
                self.end_headers()
                try:
                    while not stop.wait(0.01):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_args):
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.base_url = f"http://127.0.0.1:{self._server.server_port}/v1"

    def close(self):
        self._stop.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


class RerankReadDeadlineTests(unittest.TestCase):
    def test_drip_response_ends_within_rerank_timeout_and_frees_worker(self):
        pool = BoundedDaemonExecutor(max_workers=2, thread_name_prefix="test-rerank-drip")
        self.addCleanup(pool.shutdown, wait=True, cancel_futures=True)
        server = _DripServer()
        # Close the drip before the pool joins: a worker still reading must
        # see the connection end even when the test fails.
        self.addCleanup(server.close)

        hits = _hits(4)
        policy = RerankPolicy(
            mode="rrf_model", base_url=server.base_url, model="m",
            batch_size=20, rerank_timeout=1.0,
        )
        reranker = SystemOneReranker(server.base_url, "m", api_key="k")
        started = time.monotonic()
        with mock.patch("multi_search_mcp.src.search.rerank._RERANK_POOL", pool):
            reordered, meta = apply_rerank(
                hits, "query", reranker, policy=policy,
                deadline=started + policy.rerank_timeout,
            )
        elapsed = time.monotonic() - started

        self.assertEqual(meta["fallback_reason"], "timeout")
        self.assertEqual(
            [hit["source_id"] for hit in reordered],
            [hit["source_id"] for hit in hits],
        )
        self.assertLessEqual(elapsed, policy.rerank_timeout + 0.3)
        # The drip must not leave the scoring thread blocked after the fallback.
        # ``_tasks.join()`` blocks until every submitted batch returned; wait on
        # an event so a stuck worker fails the test instead of hanging it.
        drained = threading.Event()

        def wait_for_workers():
            pool._tasks.join()
            drained.set()

        threading.Thread(target=wait_for_workers, daemon=True).start()
        self.assertTrue(
            drained.wait(timeout=2),
            "drip response kept the rerank worker stuck",
        )
        self.assertEqual(pool.detached_count, 0)


class RerankBatchFallbackTests(unittest.TestCase):
    def test_fast_batch_failure_falls_back_without_waiting_for_slow_batch(self):
        pool = BoundedDaemonExecutor(max_workers=2, thread_name_prefix="test-rerank-batches")
        self.addCleanup(pool.shutdown, wait=True, cancel_futures=True)
        release_first = threading.Event()

        class BatchReranker:
            def score(self, _query, candidates, *, deadline):
                ids = {str(candidate["source_id"]) for candidate in candidates}
                if "s0" in ids:
                    release_first.wait(timeout=10)
                    return {source_id: 0.5 for source_id in ids}
                raise RerankError("rate_limit")

        hits = _hits(4)
        policy = RerankPolicy(
            mode="rrf_model", base_url="http://127.0.0.1:1/v1", model="m",
            batch_size=2, rerank_timeout=1.0,
        )
        started = time.monotonic()
        try:
            with mock.patch("multi_search_mcp.src.search.rerank._RERANK_POOL", pool):
                reordered, meta = apply_rerank(
                    hits, "query", BatchReranker(), policy=policy,
                    deadline=started + policy.rerank_timeout,
                )
            elapsed = time.monotonic() - started
        finally:
            release_first.set()

        self.assertEqual(meta["fallback_reason"], "rate_limit")
        self.assertEqual(
            [hit["source_id"] for hit in reordered],
            [hit["source_id"] for hit in hits],
        )
        self.assertLess(elapsed, 0.8, "fallback waited for the slow first batch")


if __name__ == "__main__":
    unittest.main()
