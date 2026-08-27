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
            run_search_web,
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
            search = run_search_web(
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
            run_search_web,
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
            search = run_search_web(
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
            run_search_web,
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
            search = run_search_web(
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
