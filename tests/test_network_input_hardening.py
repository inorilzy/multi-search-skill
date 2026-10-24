"""Clear errors for abnormal CLI/tool input and single-layer Jina rate-limit recording."""
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import multi_search_mcp.cli as cli
from multi_search_mcp.src import service
from multi_search_mcp.src.search.candidate import fuse_search_results
from multi_search_mcp.src.state.content_store import ContentStore
from multi_search_mcp.src.state.state_store import StateStore


def run_cli(argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    code = cli.main(argv, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def _fake_search(captured):
    def fake(request):
        captured.append(request)
        return {"query": request.query, "results": [], "provider_status": [], "diagnostics": {}}

    return fake


class DashQueryTests(unittest.TestCase):
    def test_query_after_option_terminator_is_a_query_even_when_it_looks_like_an_option(self):
        for query in ("-v flag meaning", "--version", "--count=999", "-h"):
            with self.subTest(query=query):
                captured = []
                with mock.patch.object(cli, "run_search_web", side_effect=_fake_search(captured)):
                    code, _stdout, stderr = run_cli(
                        ["search", "--count", "3", "--source", "brave", "--", query],
                    )
                self.assertEqual(code, 0, stderr)
                self.assertEqual(captured[0].query, query)
                self.assertEqual(captured[0].count, 3)

    def test_unterminated_dash_query_is_a_usage_error_not_a_search(self):
        with mock.patch.object(cli, "run_search_web", side_effect=AssertionError("unexpected search")):
            code, _stdout, stderr = run_cli(["search", "-foo"])
        self.assertEqual(code, 2)
        self.assertIn("usage error", stderr)

    def test_help_documents_the_option_terminator(self):
        help_text = cli.build_parser()._subparsers._group_actions[0].choices["search"].format_help()
        self.assertIn("-- <query>", help_text)

    def test_skills_document_the_option_terminator(self):
        root = Path(__file__).resolve().parents[1]
        for relative in (
            "desktop/skill/multi-search/SKILL.md",
            "desktop/skill/multi-search/references/cli.md",
            "skills/multi-search/references/cli.md",
        ):
            with self.subTest(file=relative):
                text = (root / relative).read_text(encoding="utf-8")
                # Single quotes, per the Skill shell-safety contract (fix 07).
                self.assertIn("-- '<query>'", text)


class CliNumericValidationTests(unittest.TestCase):
    def test_read_offset_and_limit_must_be_valid_integers(self):
        for argv in (
            ["read", "src_x", "--offset", "abc"],
            ["read", "src_x", "--offset", "-1"],
            ["read", "src_x", "--limit", "many"],
            ["read", "src_x", "--limit", "0"],
        ):
            with self.subTest(argv=argv):
                with mock.patch.object(cli, "run_read_source", side_effect=AssertionError("unexpected read")):
                    code, _stdout, stderr = run_cli(argv)
                self.assertEqual(code, 2)
                self.assertIn("usage error", stderr)
                self.assertIn(argv[2], stderr)

    def test_fetch_max_chars_zero_or_negative_is_rejected_not_silently_clamped(self):
        for value in ("0", "-5", "lots"):
            with self.subTest(value=value):
                with mock.patch.object(cli, "run_fetch_source", side_effect=AssertionError("unexpected fetch")):
                    code, _stdout, stderr = run_cli(
                        ["fetch", "--url", "https://example.com", "--max-chars", value],
                    )
                self.assertEqual(code, 2)
                self.assertIn("--max-chars", stderr)

    def test_valid_and_above_cap_values_still_reach_the_service(self):
        captured = []
        with mock.patch.object(cli, "run_read_source", side_effect=lambda request: captured.append(request) or {}):
            code, _stdout, stderr = run_cli(["read", "src_x", "--offset", "0", "--limit", "9000"])
        self.assertEqual(code, 0, stderr)
        self.assertEqual((captured[0].offset, captured[0].limit), (0, 9000))


class ServiceNumericValidationTests(unittest.TestCase):
    """The dict/tools entry gets a named, clear error instead of a bare int() failure."""

    def test_read_source_names_the_bad_field(self):
        with TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            ContentStore(store).put("src_readable", "x" * 20)
            for field, value in (("offset", "abc"), ("limit", "many"), ("limit", None), ("offset", True)):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValueError, f"^{field} must be an integer"):
                        service.run_read_source(
                            {"source_id": "src_readable", field: value}, state_store=store,
                        )

    def test_fetch_source_names_a_bad_max_chars(self):
        with self.assertRaisesRegex(ValueError, "^max_chars must be an integer"):
            service.run_fetch_source(
                service.FetchSourceRequest(url="https://example.com/a", max_chars="lots", use_state=False),
                scraper=mock.Mock(return_value={"markdown": "body", "via": "fake"}),
                keys={}, config={}, url_resolver=lambda _host: ["93.184.216.34"],
            )

    def test_tools_entry_reports_invalid_request(self):
        from multi_search_mcp import tools

        result = tools.read_source_tool("src_x", offset="abc")
        self.assertEqual(result["error_type"], "invalid_request")
        self.assertIn("offset must be an integer", result["error"])


class ProviderRankTests(unittest.TestCase):
    def test_malformed_provider_rank_does_not_fail_fusion(self):
        rows = [
            {"source": "brave", "title": "Bad rank", "url": "https://example.com/a", "provider_rank": "first"},
            {"source": "brave", "title": "Good", "url": "https://example.com/b", "provider_rank": 1},
            {"source": "tavily", "title": "Odd", "url": "https://example.com/c", "provider_rank": [2]},
        ]
        hits = fuse_search_results([("q", rows)], response_id="malformed-rank")
        self.assertEqual(
            sorted(hit["canonical_url"] for hit in hits),
            ["https://example.com/a", "https://example.com/b", "https://example.com/c"],
        )
        for hit in hits:
            for rank in hit["provider_ranks"]:
                self.assertIsInstance(rank["rank"], int)
                self.assertGreaterEqual(rank["rank"], 1)


class JinaAnonymousRateLimitTests(unittest.TestCase):
    def test_anonymous_rate_limit_is_recorded_exactly_once(self):
        from multi_search_mcp.src.scrape import scrape
        from multi_search_mcp.src.scrape.scrapers import jina
        import email.message
        import urllib.error

        def rate_limited(*_args, **_kwargs):
            raise urllib.error.HTTPError(
                "https://r.jina.ai/x", 429, "Too Many Requests",
                email.message.Message(), io.BytesIO(b'{"message": "rate limit"}'),
            )

        jina._reset_jina_anonymous_rate_limit()
        self.addCleanup(jina._reset_jina_anonymous_rate_limit)
        with mock.patch.object(jina, "urlopen_retry", side_effect=rate_limited), \
             mock.patch.object(jina, "_record_jina_anonymous_rate_limit",
                               wraps=jina._record_jina_anonymous_rate_limit) as recorded, \
             mock.patch.object(scrape, "scrape_url_firecrawl",
                               return_value={"url": "https://example.com/p", "error": "fixture"}), \
             mock.patch.object(scrape, "scrape_url_exa",
                               return_value={"url": "https://example.com/p", "error": "fixture"}), \
             mock.patch.object(scrape, "scrape_url_tavily",
                               return_value={"url": "https://example.com/p", "error": "fixture"}):
            scrape.scrape_url_smart(
                "https://example.com/p", backends=("jina",),
                url_resolver=lambda _host: ["93.184.216.34"],
            )
        self.assertEqual(recorded.call_count, 1)
        self.assertTrue(jina._jina_anonymous_cooling_down())

    def test_scrape_layer_no_longer_records_the_limit_itself(self):
        source = Path(__file__).resolve().parents[1] / "multi_search_mcp" / "src" / "scrape" / "scrape.py"
        self.assertNotIn("_record_jina_anonymous_rate_limit", source.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
