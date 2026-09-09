import threading
import time
import unittest
from unittest import mock

from multi_search_mcp.src.scrape import stage
from multi_search_mcp.src.support.concurrency import BoundedDaemonExecutor


def _hits(count):
    return [
        {"source_id": f"source-{index}", "url": f"https://example.com/{index}", "source": "brave"}
        for index in range(count)
    ]


class RankedFetchStageTests(unittest.TestCase):
    def setUp(self):
        self.pool = BoundedDaemonExecutor(max_workers=4, thread_name_prefix="test-ranked-fetch")
        self.patch = mock.patch.object(stage, "_SCRAPE_POOL", self.pool)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.pool.shutdown, wait=True, cancel_futures=True)

    def test_keeps_ranking_when_fetches_complete_out_of_order(self):
        second_finished = threading.Event()
        completed = []
        hits = _hits(2)

        def fetch(hit, remaining):
            self.assertGreater(remaining, 0)
            if hit is hits[0]:
                self.assertTrue(second_finished.wait(timeout=1))
            completed.append(hit["source_id"])
            if hit is hits[1]:
                second_finished.set()
            return {"source_id": hit["source_id"], "content": "body"}

        result = stage.run_ranked_fetch_stage(hits, fetch=fetch, timeout=2, concurrency=2)
        self.assertEqual(completed, ["source-1", "source-0"])
        self.assertEqual([row["source_id"] for row in result["results"]], ["source-0", "source-1"])
        self.assertEqual(result["errors"], [])

    def test_fetches_all_same_source_hits_without_quota_or_rank_window(self):
        hits = _hits(18)
        called = []

        def fetch(hit, remaining):
            called.append(hit["source_id"])
            return {"source_id": hit["source_id"], "content": "body"}

        result = stage.run_ranked_fetch_stage(hits, fetch=fetch, timeout=2, concurrency=1)
        self.assertEqual(called, [hit["source_id"] for hit in hits])
        self.assertEqual(len(result["results"]), 18)
        self.assertEqual(result["errors"], [])

    def test_errors_keep_hit_identity_and_successful_neighbors(self):
        hits = _hits(4)

        def fetch(hit, remaining):
            if hit is hits[1]:
                raise RuntimeError("backend failed token=private-value")
            if hit is hits[2]:
                return {"error": "access denied", "status": 403}
            if hit is hits[3]:
                return None
            return {"source_id": hit["source_id"], "content": "body"}

        result = stage.run_ranked_fetch_stage(hits, fetch=fetch, timeout=2)
        self.assertEqual(result["results"][0]["content"], "body")
        self.assertEqual(result["errors"], result["results"][1:])
        for hit, row in zip(hits[1:], result["errors"]):
            self.assertEqual(row["source_id"], hit["source_id"])
            self.assertEqual(row["url"], hit["url"])
            self.assertTrue(row["error"])
        self.assertNotIn("private-value", result["errors"][0]["error"])
        self.assertEqual(result["errors"][1]["status"], 403)

    def test_limits_request_concurrency(self):
        active = 0
        maximum = 0
        lock = threading.Lock()
        first_pair = threading.Barrier(2)
        hits = _hits(8)

        def fetch(hit, remaining):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                if hit in hits[:2]:
                    first_pair.wait(timeout=1)
                time.sleep(0.01)
                return {"source_id": hit["source_id"], "content": "body"}
            finally:
                with lock:
                    active -= 1

        result = stage.run_ranked_fetch_stage(hits, fetch=fetch, timeout=2, concurrency=2)
        self.assertEqual(maximum, 2)
        self.assertEqual(result["errors"], [])

    def test_passes_remaining_batch_time_to_each_fetch(self):
        remaining_times = []

        def fetch(hit, remaining):
            remaining_times.append(remaining)
            time.sleep(0.02)
            return {"content": "body"}

        result = stage.run_ranked_fetch_stage(_hits(2), fetch=fetch, timeout=1, concurrency=1)
        self.assertEqual(result["errors"], [])
        self.assertGreater(remaining_times[0], remaining_times[1])
        self.assertGreater(remaining_times[1], 0)
        self.assertLessEqual(remaining_times[0], 1)

    def test_timeout_returns_without_waiting_and_preserves_finished_hits(self):
        release = threading.Event()
        hits = _hits(4)
        called = []

        def fetch(hit, remaining):
            called.append(hit["source_id"])
            if hit is hits[1]:
                release.wait(timeout=2)
            return {"source_id": hit["source_id"], "content": "body"}

        try:
            start = time.monotonic()
            result = stage.run_ranked_fetch_stage(hits, fetch=fetch, timeout=0.08, concurrency=1)
            self.assertLess(time.monotonic() - start, 0.5)
            self.assertEqual(result["results"][0]["content"], "body")
            self.assertEqual(called, ["source-0", "source-1"])
            self.assertEqual(len(result["errors"]), 3)
            self.assertTrue(all("timeout" in row["error"] for row in result["errors"]))
        finally:
            release.set()

    def test_expired_batch_does_not_invoke_fetch(self):
        fetch = mock.Mock()
        result = stage.run_ranked_fetch_stage(_hits(2), fetch=fetch, timeout=0)
        fetch.assert_not_called()
        self.assertEqual(len(result["errors"]), 2)

    def test_global_pool_wait_cannot_start_fetch_after_deadline(self):
        release = threading.Event()
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix="test-ranked-fetch-saturated")
        fetch = mock.Mock(return_value={"content": "body"})
        try:
            pool.submit_before(time.monotonic() + 1, release.wait, 2)
            with mock.patch.object(stage, "_SCRAPE_POOL", pool):
                result = stage.run_ranked_fetch_stage(_hits(2), fetch=fetch, timeout=0.04)
            release.set()
            pool.shutdown(wait=True, cancel_futures=True)
            fetch.assert_not_called()
            self.assertEqual(len(result["errors"]), 2)
        finally:
            release.set()
            pool.shutdown(wait=True, cancel_futures=True)

    def test_worker_rechecks_deadline_before_invoking_callback(self):
        release = threading.Event()
        fetch = mock.Mock(return_value={"content": "body"})
        submit = self.pool.submit_before

        def delay_worker(deadline, callback, hit):
            def delayed():
                release.wait(timeout=2)
                return callback(hit)

            return submit(deadline, delayed)

        try:
            with mock.patch.object(self.pool, "submit_before", side_effect=delay_worker):
                result = stage.run_ranked_fetch_stage(_hits(1), fetch=fetch, timeout=0.04)
            self.assertEqual(len(result["errors"]), 1)
        finally:
            release.set()
            self.pool.shutdown(wait=True, cancel_futures=True)
        fetch.assert_not_called()

    def test_invalid_concurrency_is_explicit(self):
        with self.assertRaisesRegex(ValueError, "concurrency"):
            stage.run_ranked_fetch_stage(_hits(1), fetch=mock.Mock(), timeout=1, concurrency=0)


if __name__ == "__main__":
    unittest.main()
