import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.state.content_store import ContentStore
from multi_search_mcp.src.state.state_store import StateStore


class FetchSourceCoreTests(unittest.TestCase):
    def test_fetch_by_source_id_scrapes_once_then_reuses_cached_body(self):
        from multi_search_mcp.src.service import (
            FetchSourceRequest,
            SearchWebRequest,
            run_fetch_source,
            _run_search_candidates,
        )

        provider = ProviderSpec(
            name="brave",
            public_name="brave",
            call=lambda _query, _config, _context, _key: [
                {
                    "source": "brave",
                    "title": "Evidence",
                    "url": "https://evidence.example/article",
                    "description": "candidate excerpt",
                    "content_kind": "excerpt",
                }
            ],
        )
        scrape_calls = []

        def fake_scraper(url, **_kwargs):
            scrape_calls.append(url)
            return {
                "url": url,
                "markdown": "prefix needle content suffix",
                "via": "fake-scraper",
            }

        with TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            search = _run_search_candidates(
                SearchWebRequest(
                    query="evidence",
                    sources=["brave"],
                    count=1,
                ),
                providers={"brave": provider},
                keys={},
                config={},
                state_store=store,
            )
            source_id = search["results"][0]["source_id"]
            request = FetchSourceRequest(source_id=source_id, max_chars=1000)

            first = run_fetch_source(
                request,
                state_store=store,
                scraper=fake_scraper,
                keys={},
                config={},
                url_resolver=lambda _host: ["93.184.216.34"],
            )
            second = run_fetch_source(
                request,
                state_store=store,
                scraper=fake_scraper,
                keys={},
                config={},
                url_resolver=lambda _host: ["93.184.216.34"],
            )

        self.assertEqual(scrape_calls, ["https://evidence.example/article"])
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first["body"], "prefix needle content suffix")
        self.assertEqual(first["backend"], "fake-scraper")
        self.assertTrue(first["untrusted_content"])

    def test_fetch_by_explicit_url_registers_a_reusable_source_id(self):
        from multi_search_mcp.src.service import FetchSourceRequest, run_fetch_source
        from multi_search_mcp.src.state.source_registry import SourceRegistry

        calls = []

        def fake_scraper(url, **_kwargs):
            calls.append(url)
            return {"url": url, "markdown": "explicit body", "via": "fake"}

        with TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            fetched = run_fetch_source(
                FetchSourceRequest(url="https://evidence.example/explicit"),
                state_store=store,
                scraper=fake_scraper,
                keys={},
                config={},
                url_resolver=lambda _host: ["93.184.216.34"],
            )
            registered = SourceRegistry(store).get(fetched["source_id"])
            cached = run_fetch_source(
                FetchSourceRequest(source_id=fetched["source_id"]),
                state_store=store,
                scraper=fake_scraper,
                keys={},
                config={},
                url_resolver=lambda _host: ["93.184.216.34"],
            )

        self.assertTrue(fetched["source_id"].startswith("src_"))
        self.assertEqual(registered["url"], "https://evidence.example/explicit")
        self.assertLessEqual(
            datetime.fromisoformat(registered["expires_at"]),
            datetime.now(timezone.utc) + timedelta(seconds=3_605),
        )
        self.assertTrue(cached["cache_hit"])
        self.assertEqual(calls, ["https://evidence.example/explicit"])

    def test_fetch_uses_its_explicit_config_path(self):
        from multi_search_mcp.src.service import FetchSourceRequest, run_fetch_source

        observed = {}

        def fake_scraper(url, **kwargs):
            observed.update(kwargs)
            return {"url": url, "markdown": "configured body", "via": "fake"}

        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text('{"scrape_timeout": 7}', encoding="utf-8")
            store = StateStore(Path(tmp) / "state.sqlite")
            run_fetch_source(
                FetchSourceRequest(
                    url="https://evidence.example/configured",
                    config_path=str(config_path),
                ),
                state_store=store,
                scraper=fake_scraper,
                keys={},
                url_resolver=lambda _host: ["93.184.216.34"],
            )

        self.assertEqual(observed["timeout"], 7)

    def test_prefetched_provider_body_is_reused_without_scraping(self):
        from multi_search_mcp.src.service import (
            FetchSourceRequest,
            SearchWebRequest,
            run_fetch_source,
            _run_search_candidates,
        )

        provider = ProviderSpec(
            name="tavily",
            public_name="tavily",
            call=lambda _query, _config, _context, _key: [
                {
                    "source": "tavily",
                    "title": "Prefetched",
                    "url": "https://evidence.example/prefetched",
                    "description": "excerpt",
                    "scraped_content": "provider body",
                    "content_kind": "body",
                }
            ],
        )

        with TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            search = _run_search_candidates(
                SearchWebRequest(
                    query="prefetched",
                    sources=["tavily"],
                    count=1,
                ),
                providers={"tavily": provider},
                keys={},
                config={},
                state_store=store,
            )
            fetched = run_fetch_source(
                FetchSourceRequest(source_id=search["results"][0]["source_id"]),
                state_store=store,
                scraper=lambda *_args, **_kwargs: self.fail("scraper must not run"),
                keys={},
                config={},
                url_resolver=lambda _host: ["93.184.216.34"],
            )

        self.assertTrue(fetched["cache_hit"])
        self.assertEqual(fetched["body"], "provider body")

    def test_multi_search_returns_body_separately_from_excerpt(self):
        from multi_search_mcp.src.service import MultiSearchRequest, run_multi_search

        provider = ProviderSpec(
            name="tavily",
            public_name="tavily",
            call=lambda _query, _config, _context, _key: [
                {
                    "source": "tavily",
                    "title": "Prefetched",
                    "url": "https://evidence.example/prefetched",
                    "description": "excerpt",
                    "scraped_content": "provider body",
                    "content_kind": "body",
                }
            ],
        )

        with mock.patch(
            "multi_search_mcp.src.search.registry.build_provider_registry",
            return_value={"tavily": provider},
        ), mock.patch("multi_search_mcp.src.service.load_keys", return_value={}), \
                mock.patch("multi_search_mcp.src.service.validate_public_http_url", return_value=None):
            response = run_multi_search(
                MultiSearchRequest(
                    query="prefetched",
                    route="fast",
                    count=1,
                    use_state=False,
                )
            )

        self.assertNotIn("scraped_content", response["results"][0])
        self.assertEqual(response["results"][0]["body"], "provider body")
        self.assertNotIn("full_content", response["results"][0])
        self.assertEqual(response["results"][0]["content"], "excerpt")

    def test_provider_retention_policy_can_forbid_body_persistence(self):
        from multi_search_mcp.src.search.capabilities import (
            PROVIDER_CAPABILITIES,
            RetentionPolicy,
        )
        from multi_search_mcp.src.service import (
            FetchSourceRequest,
            ReadSourceRequest,
            SearchWebRequest,
            run_fetch_source,
            run_read_source,
            _run_search_candidates,
        )

        provider = ProviderSpec(
            name="brave",
            public_name="brave",
            call=lambda _query, _config, _context, _key: [
                {
                    "source": "brave",
                    "title": "No retention",
                    "url": "https://evidence.example/no-retention",
                    "description": "excerpt",
                    "content_kind": "excerpt",
                }
            ],
        )
        calls = []

        def fake_scraper(url, **_kwargs):
            calls.append(url)
            return {"url": url, "markdown": "one-call body", "via": "fake"}

        no_body = replace(
            PROVIDER_CAPABILITIES["brave"],
            retention=RetentionPolicy(persist_body=False),
        )
        with TemporaryDirectory() as tmp, mock.patch.dict(
            PROVIDER_CAPABILITIES, {"brave": no_body}
        ):
            store = StateStore(Path(tmp) / "state.sqlite")
            search = _run_search_candidates(
                SearchWebRequest(
                    query="no retention", sources=["brave"], count=1
                ),
                providers={"brave": provider},
                keys={},
                config={},
                state_store=store,
            )
            source_id = search["results"][0]["source_id"]
            fetched = run_fetch_source(
                FetchSourceRequest(source_id=source_id),
                state_store=store,
                scraper=fake_scraper,
                keys={},
                config={},
                url_resolver=lambda _host: ["93.184.216.34"],
            )
            with self.assertRaisesRegex(ValueError, "call fetch_source"):
                run_read_source(
                    ReadSourceRequest(source_id=source_id), state_store=store
                )

        self.assertEqual(fetched["body"], "one-call body")
        self.assertFalse(fetched["persisted"])
        self.assertEqual(calls, ["https://evidence.example/no-retention"])


class ReadSourceCoreTests(unittest.TestCase):
    def test_read_is_cache_only_and_supports_keyword_offset_and_limit(self):
        from multi_search_mcp.src.service import (
            ReadSourceRequest,
            run_read_source,
        )

        with TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            ContentStore(store).put(
                "src_readable", "prefix needle content suffix"
            )
            response = run_read_source(
                ReadSourceRequest(
                    source_id="src_readable",
                    keyword="needle",
                    offset=0,
                    limit=10,
                ),
                state_store=store,
            )

        self.assertEqual(response["content"], "needle con")
        self.assertEqual(response["match_offset"], 7)
        self.assertEqual(response["start"], 7)
        self.assertEqual(response["end"], 17)
        self.assertTrue(response["untrusted_content"])

    def test_read_supports_stable_keyword_pagination(self):
        from multi_search_mcp.src.service import ReadSourceRequest, run_read_source

        with TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            ContentStore(store).put(
                "src_readable", "prefix needle content suffix"
            )
            first = run_read_source(
                ReadSourceRequest(
                    source_id="src_readable",
                    keyword="needle",
                    offset=0,
                    limit=6,
                ),
                state_store=store,
            )
            second = run_read_source(
                ReadSourceRequest(
                    source_id="src_readable",
                    keyword="needle",
                    offset=first["next_offset"],
                    limit=8,
                ),
                state_store=store,
            )

        self.assertEqual(first["content"], "needle")
        self.assertEqual(first["next_offset"], 6)
        self.assertEqual(second["content"], " content")
        self.assertEqual(second["match_offset"], 7)
        self.assertEqual(second["start"], 13)

    def test_read_clamps_out_of_range_offset_and_limit_and_caps_limit(self):
        from multi_search_mcp.src.service import ReadSourceRequest, run_read_source

        with TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            ContentStore(store).put("src_readable", "x" * 9_000)
            clamped = run_read_source(
                ReadSourceRequest(
                    source_id="src_readable",
                    offset=-1,
                    limit=0,
                ),
                state_store=store,
            )

            response = run_read_source(
                ReadSourceRequest(source_id="src_readable", limit=9_000),
                state_store=store,
            )

        self.assertEqual(clamped["content"], "x")
        self.assertEqual(clamped["start"], 0)
        self.assertEqual(clamped["next_offset"], 1)
        self.assertEqual(len(response["content"]), 8_000)
        self.assertTrue(response["has_more"])
        self.assertEqual(response["next_offset"], 8_000)

    def test_read_fails_explicitly_for_missing_cache_or_keyword(self):
        from multi_search_mcp.src.service import (
            ReadSourceRequest,
            run_read_source,
        )

        with TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            ContentStore(store).put("src_readable", "known body")
            with self.assertRaisesRegex(ValueError, "keyword was not found"):
                run_read_source(
                    ReadSourceRequest(
                        source_id="src_readable", keyword="absent"
                    ),
                    state_store=store,
                )
            with self.assertRaisesRegex(ValueError, "call fetch_source"):
                run_read_source(
                    ReadSourceRequest(source_id="src_missing"),
                    state_store=store,
                )

    def test_read_fails_for_expired_or_deleted_cached_content(self):
        from multi_search_mcp.src.service import ReadSourceRequest, run_read_source

        with TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
            content_store = ContentStore(
                store,
                ttl_seconds=60,
                clock=lambda: now[0],
            )
            content_store.put("src_expired", "known body")
            now[0] += timedelta(seconds=61)
            with self.assertRaisesRegex(ValueError, "call fetch_source"):
                run_read_source(
                    ReadSourceRequest(source_id="src_expired"),
                    state_store=store,
                    content_store=content_store,
                )

            content_store.put("src_deleted", "known body")
            self.assertEqual(content_store.delete_source("src_deleted"), 1)
            with self.assertRaisesRegex(ValueError, "call fetch_source"):
                run_read_source(
                    ReadSourceRequest(source_id="src_deleted"),
                    state_store=store,
                    content_store=content_store,
                )

    def test_repeated_reads_update_lru_without_extending_expiry(self):
        from multi_search_mcp.src.service import ReadSourceRequest, run_read_source

        with TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
            content_store = ContentStore(
                store,
                ttl_seconds=60,
                clock=lambda: now[0],
            )
            content_store.put("src_readable", "known body")
            before = store.rows(
                """
                SELECT s.expires_at, o.last_access_at
                FROM content_sources AS s
                JOIN content_objects AS o ON o.content_hash = s.content_hash
                WHERE s.source_id = ?
                """,
                ("src_readable",),
            )[0]

            now[0] += timedelta(seconds=1)
            first = run_read_source(
                ReadSourceRequest(source_id="src_readable"),
                state_store=store,
                content_store=content_store,
            )
            now[0] += timedelta(seconds=1)
            second = run_read_source(
                ReadSourceRequest(source_id="src_readable"),
                state_store=store,
                content_store=content_store,
            )
            after = store.rows(
                """
                SELECT s.expires_at, o.last_access_at
                FROM content_sources AS s
                JOIN content_objects AS o ON o.content_hash = s.content_hash
                WHERE s.source_id = ?
                """,
                ("src_readable",),
            )[0]

        self.assertEqual(first["expires_at"], before["expires_at"])
        self.assertEqual(second["expires_at"], before["expires_at"])
        self.assertEqual(after["expires_at"], before["expires_at"])
        self.assertEqual(after["last_access_at"], now[0].isoformat())


class SourceContentToolTests(unittest.TestCase):
    def test_fetch_tool_does_not_replace_an_omitted_timeout(self):
        from multi_search_mcp import tools

        captured = {}

        def fake_run(request):
            captured["request"] = request
            return {"source_id": request.source_id, "body": "body"}

        with mock.patch.object(tools, "run_fetch_source", side_effect=fake_run):
            response = tools.fetch_source_tool("src_tool")

        self.assertEqual(response["source_id"], "src_tool")
        self.assertIsNone(captured["request"].timeout)

    def test_fetch_and_read_tools_share_the_same_core_state(self):
        from multi_search_mcp.src.state.source_registry import SourceRegistry
        from multi_search_mcp.tools import fetch_source_tool, read_source_tool

        with TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            SourceRegistry(store).register(
                "resp_tool",
                [{
                    "source_id": "src_tool",
                    "title": "Tool source",
                    "url": "https://93.184.216.34/tool-source",
                    "canonical_url": "https://93.184.216.34/tool-source",
                    "content": "excerpt",
                    "content_kind": "excerpt",
                    "providers": ["brave"],
                    "body_available": False,
                }],
            )
            with (
                mock.patch(
                    "multi_search_mcp.src.service.StateStore", return_value=store
                ),
                mock.patch(
                    "multi_search_mcp.src.service.load_keys", return_value={}
                ),
                mock.patch(
                    "multi_search_mcp.src.service.scrape_url_smart",
                    return_value={
                        "url": "https://93.184.216.34/tool-source",
                        "markdown": "tool needle body",
                        "via": "fake",
                    },
                ),
            ):
                fetched = fetch_source_tool("src_tool")
                read = read_source_tool(
                    "src_tool", keyword="needle", limit=6
                )

        self.assertFalse(fetched["cache_hit"])
        self.assertEqual(read["content"], "needle")


if __name__ == "__main__":
    unittest.main()
