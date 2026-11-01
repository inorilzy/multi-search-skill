"""Provider HTTP errors are classified as each vendor documents them.

The specs are saved under docs/<provider>/. These cases are the ones where the
old adapters stopped a healthy key (403 treated as "invalid") or ignored the
server's wait (Retry-After / backoff).
"""
import gzip
import io
import json
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.scrape.scrapers import exa as exa_scraper
from multi_search_mcp.src.scrape.scrapers import firecrawl as firecrawl_scraper
from multi_search_mcp.src.scrape.scrapers import jina as jina_scraper
from multi_search_mcp.src.search.searchers import (
    baidu,
    brave,
    exa,
    firecrawl,
    hackernews,
    parallel,
    serpapi,
    sov2ex,
    stackoverflow,
    tavily,
)
from multi_search_mcp.src.state import backoff
from multi_search_mcp.src.state.key_state import BasicKeyManager
from multi_search_mcp.src.support import http_errors
from multi_search_mcp.src.support.query_limits import limit_query


def http_error(code, body=None, headers=None, raw=None):
    msg = Message()
    for name, value in (headers or {}).items():
        msg[name] = value
    data = raw if raw is not None else json.dumps(body or {}).encode()
    return urllib.error.HTTPError("https://api.example/", code, "error", msg, io.BytesIO(data))


def response(payload):
    result = mock.MagicMock()
    result.__enter__.return_value = result
    result.read.return_value = json.dumps(payload).encode()
    result.headers = Message()
    return result


class SharedHelperTests(unittest.TestCase):
    def test_retry_after_seconds_and_http_date(self):
        self.assertEqual(http_errors.parse_retry_after("30"), 30)
        self.assertEqual(http_errors.parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412470), 10)
        self.assertIsNone(http_errors.parse_retry_after("soon"))

    def test_row_reads_body_message_and_retry_after(self):
        row = http_errors.http_error_row(
            "x", http_error(429, {"error": {"code": "rpm", "message": "slow down"}}, {"Retry-After": "7"}),
            kinds={429: "rate_limit"},
        )
        self.assertEqual(row["kind"], "rate_limit")
        self.assertEqual(row["retry_after"], 7)
        self.assertIn("rpm slow down", row["error"])

    def test_retry_after_drives_the_key_cooldown(self):
        outcome = BasicKeyManager().classify_result("x", [{"source": "x", "error": "429", "kind": "rate_limit", "retry_after": 42}])
        self.assertEqual(outcome.error_type, "rate_limit")
        self.assertEqual(outcome.retry_after, 42)


class ForbiddenIsNotABadKeyTests(unittest.TestCase):
    # docs/exa/error-codes.md, docs/firecrawl/errors.md: 403 = feature/policy/site.
    def test_exa_search_and_contents_403(self):
        with mock.patch.object(exa, "urlopen_retry", side_effect=http_error(403, {"tag": "FEATURE_DISABLED"})):
            row = exa.search_exa("q", "k")[0]
        self.assertEqual(row["kind"], "provider")
        with mock.patch.object(exa_scraper, "urlopen_retry", side_effect=http_error(403, {"tag": "CONTENT_FILTER_ERROR"})):
            row = exa_scraper.scrape_url_exa("https://example.com/", "k")
        self.assertEqual(row["kind"], "provider")
        with mock.patch.object(exa, "urlopen_retry", side_effect=http_error(402, {"tag": "NO_MORE_CREDITS"})):
            self.assertEqual(exa.search_exa("q", "k")[0]["kind"], "quota_exhausted")

    def test_firecrawl_unsupported_site_is_a_target_failure(self):
        body = {"success": False, "code": "UNSUPPORTED_SITE",
                "error": "We apologize for the inconvenience but we do not support this site"}
        with mock.patch.object(firecrawl_scraper, "urlopen_retry", side_effect=http_error(403, body)):
            row = firecrawl_scraper.scrape_url_firecrawl("https://example.com/", "k")
        self.assertEqual(row["error_type"], "target")
        with mock.patch.object(firecrawl_scraper, "urlopen_retry", side_effect=http_error(403, {"success": False, "error": "Forbidden"})):
            self.assertEqual(firecrawl_scraper.scrape_url_firecrawl("https://example.com/", "k")["error_type"], "provider")

    def test_firecrawl_search_classifies_status_codes(self):
        for code, kind in ((401, "invalid"), (402, "quota_exhausted"), (429, "rate_limit")):
            with self.subTest(code=code), mock.patch.object(firecrawl, "urlopen_retry", side_effect=http_error(code, {"error": "x"})):
                self.assertEqual(firecrawl.search_firecrawl("q", "k")[0]["kind"], kind)

    def test_firecrawl_target_page_error_status_is_not_content(self):
        page = {"success": True, "data": {"markdown": "Not Found", "metadata": {"statusCode": 404}}}
        with mock.patch.object(firecrawl_scraper, "urlopen_retry", return_value=response(page)):
            row = firecrawl_scraper.scrape_url_firecrawl("https://example.com/missing", "k")
        self.assertEqual(row["error_type"], "target")


class RateLimitAndQuotaTests(unittest.TestCase):
    def test_baidu_reads_the_documented_error_body(self):
        body = {"error": {"code": "rpm_rate_limit_exceeded", "message": "Rate limit reached for RPM",
                          "type": "rate_limit_exceeded"}, "id": "req-1"}
        with mock.patch.object(baidu, "urlopen_retry", side_effect=http_error(429, body, {"X-Request-Id": "req-1"})):
            row = baidu.search_baidu("q", "k")[0]
        self.assertEqual(row["kind"], "rate_limit")
        self.assertEqual(row["request_id"], "req-1")
        quota = {"error": {"code": "coding_plan_hour_quota_exceeded", "type": "quota_exceeded"}}
        with mock.patch.object(baidu, "urlopen_retry", side_effect=http_error(429, quota)):
            self.assertEqual(baidu.search_baidu("q", "k")[0]["kind"], "quota_exhausted")

    def test_serpapi_429_out_of_searches_is_quota(self):
        with mock.patch.object(serpapi, "urlopen_retry", side_effect=http_error(429, {"error": "Your account has run out of searches."})):
            self.assertEqual(serpapi.search_serpapi("q", "k")[0]["kind"], "quota_exhausted")
        with mock.patch.object(serpapi, "urlopen_retry", side_effect=http_error(429, {"error": "hourly throughput"})):
            self.assertEqual(serpapi.search_serpapi("q", "k")[0]["kind"], "rate_limit")

    def test_tavily_and_brave_carry_retry_after(self):
        with mock.patch.object(tavily, "urlopen_retry", side_effect=http_error(429, {"detail": {"error": "slow"}}, {"Retry-After": "12"})):
            self.assertEqual(tavily.search_tavily("q", "k")[0]["retry_after"], 12)
        with mock.patch.object(brave, "urlopen_retry", side_effect=http_error(429, {}, {"X-RateLimit-Reset": "1, 1500000"})):
            row = brave.search_brave("q", "k")[0]
        self.assertEqual((row["kind"], row["retry_after"]), ("rate_limit", 1))

    def test_jina_tier_restriction_does_not_exhaust_the_key(self):
        jina_scraper.reset_jina_anonymous_rate_limit()
        tier = http_error(402, {"code": 402, "status": 40202, "message": "feature not in tier"})
        with mock.patch.object(jina_scraper, "urlopen_retry", side_effect=tier):
            row = jina_scraper.scrape_url_jina("https://example.com/", "k", skip_anonymous=True)
        self.assertEqual(row["error_type"], "provider")
        self.assertNotIn("key_exhausted", row)
        balance = http_error(402, {"code": 402, "status": 40203, "message": "insufficient balance"})
        with mock.patch.object(jina_scraper, "urlopen_retry", side_effect=balance):
            row = jina_scraper.scrape_url_jina("https://example.com/", "k", skip_anonymous=True)
        self.assertEqual(row["error_type"], "quota_exhausted")

    def test_jina_anonymous_cooldown_uses_retry_after(self):
        jina_scraper.reset_jina_anonymous_rate_limit()
        jina_scraper.record_jina_anonymous_rate_limit(now=100.0, seconds=5)
        self.assertTrue(jina_scraper.jina_anonymous_cooling_down(now=104.0))
        self.assertFalse(jina_scraper.jina_anonymous_cooling_down(now=106.0))
        jina_scraper.reset_jina_anonymous_rate_limit()


class StackExchangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(backoff, "backoff_path", return_value=Path(self.temp.name) / "b.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def test_gzipped_400_error_body_is_read(self):
        raw = gzip.compress(json.dumps({"error_id": 502, "error_name": "throttle_violation",
                                        "error_message": "too many requests from this IP"}).encode())
        err = http_error(400, raw=raw, headers={"Content-Encoding": "gzip"})
        with mock.patch.object(stackoverflow, "urlopen_retry", side_effect=err):
            row = stackoverflow.search_stackoverflow("q")[0]
        self.assertEqual(row["kind"], "rate_limit")
        self.assertIn("throttle_violation", row["error"])

    def test_backoff_is_honoured_by_the_next_call(self):
        body = {"items": [], "backoff": 30, "quota_remaining": 100}
        with mock.patch.object(stackoverflow, "urlopen_retry", return_value=response(body)):
            self.assertEqual(stackoverflow.search_stackoverflow("q"), [])
        with mock.patch.object(stackoverflow, "urlopen_retry", side_effect=AssertionError("must not call")):
            row = stackoverflow.search_stackoverflow("q")[0]
        self.assertTrue(row["rate_limited"])
        self.assertGreater(row["retry_after"], 0)

    def test_quota_remaining_zero_is_reported(self):
        with mock.patch.object(stackoverflow, "urlopen_retry", return_value=response({"items": [], "quota_remaining": 0})):
            rows = stackoverflow.search_stackoverflow("q")
        self.assertEqual(rows[-1]["kind"], "quota_exhausted")

    def test_optional_key_uses_bearer_header(self):
        sent = []
        def capture(req, **_kw):
            sent.append(dict(req.header_items()))
            return response({"items": []})
        with mock.patch.object(stackoverflow, "urlopen_retry", side_effect=capture):
            stackoverflow.search_stackoverflow("q", api_key="se-key")
            stackoverflow.search_stackoverflow("q")
        self.assertEqual(sent[0]["Authorization"], "Bearer se-key")
        self.assertNotIn("Authorization", sent[1])


class QueryLimitAndPagingTests(unittest.TestCase):
    def test_limit_query_truncates_and_reports(self):
        text, notes = limit_query("brave", " ".join(["word"] * 100), max_chars=600, max_words=75)
        self.assertEqual(len(text.split()), 75)
        self.assertEqual(notes[0]["error_type"], "target")
        self.assertEqual(limit_query("brave", "short", max_chars=600)[1], [])

    def test_brave_and_firecrawl_send_truncated_queries(self):
        sent = []
        def capture(req, **_kw):
            sent.append(req)
            return response({"web": {"results": []}, "success": True, "data": {"web": []}})
        long_query = "x" * 900
        with mock.patch.object(brave, "urlopen_retry", side_effect=capture):
            rows = brave.search_brave(long_query, "k")
        self.assertLessEqual(len(dict(__import__("urllib.parse").parse.parse_qsl(sent[0].full_url.split("?", 1)[1]))["q"]), 600)
        self.assertEqual(rows[-1]["error_type"], "target")
        with mock.patch.object(firecrawl, "urlopen_retry", side_effect=capture):
            firecrawl.search_firecrawl(long_query, "k", count=500)
        body = json.loads(sent[-1].data)
        self.assertLessEqual(len(body["query"]), 500)
        self.assertEqual(body["limit"], 100)

    def test_serpapi_requests_one_page_only(self):
        page = {"search_metadata": {"status": "Success"}, "organic_results": [
            {"title": str(i), "link": f"https://example.com/{i}"} for i in range(10)]}
        with mock.patch.object(serpapi, "urlopen_retry", return_value=response(page)) as http:
            rows = serpapi.search_serpapi("q", "k", count=30)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(len(rows), 10)

    def test_parallel_empty_query_is_not_sent(self):
        with mock.patch.object(parallel, "urlopen_retry", side_effect=AssertionError("must not call")):
            self.assertEqual(parallel.search_parallel("   ", "k")[0]["error"], "empty query")

    def test_hackernews_and_sov2ex_params(self):
        sent = []
        def capture(req, **_kw):
            sent.append(req.full_url)
            return response({"hits": []})
        with mock.patch.object(hackernews, "urlopen_retry", side_effect=capture):
            hackernews.search_hackernews("q", count=5000)
        self.assertIn("hitsPerPage=1000", sent[-1])
        with mock.patch.object(sov2ex, "urlopen_retry", side_effect=capture):
            sov2ex.search_sov2ex("python asyncio")
        self.assertIn("operator=and", sent[-1])

    def test_exa_sends_only_documented_headers_and_no_forced_livecrawl(self):
        sent = []
        def capture(req, **_kw):
            sent.append(req)
            return response({"results": [], "statuses": []})
        with mock.patch.object(exa, "urlopen_retry", side_effect=capture):
            exa.search_exa("q", "k")
        headers = {k.lower() for k in dict(sent[0].header_items())}
        self.assertEqual(headers, {"x-api-key", "content-type"})
        with mock.patch.object(exa_scraper, "urlopen_retry", side_effect=capture):
            exa_scraper.scrape_url_exa("https://example.com/", "k")
        self.assertNotIn("maxAgeHours", json.loads(sent[-1].data))


if __name__ == "__main__":
    unittest.main()
