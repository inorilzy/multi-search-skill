"""Plugin ownership, stable legacy registries and the balance extension seam."""
import json
import unittest
from collections import Counter
from datetime import datetime
from unittest import mock

from multi_search_mcp.src.plugins import (
    BalanceContext,
    BalanceReport,
    ProviderPlugin,
    builtin_plugins,
    get_plugin,
)
from multi_search_mcp.src.plugins import base
from multi_search_mcp.src.scrape import scrape
from multi_search_mcp.src.search import registry
from multi_search_mcp.src.search.capabilities import PROVIDER_CAPABILITIES
from multi_search_mcp.src.search.search_runner import SearchContext, SearchRunnerConfig
from multi_search_mcp.src.support import backends


SEARCH_ORDER = (
    "brave", "parallel", "baidu", "tavily", "exa", "serpapi", "firecrawl",
    "sov2ex", "github_repos", "github_code", "hackernews", "stackoverflow", "twitter",
)
CHANNEL_ORDER = ("jina_key", "jina_anon", "exa", "tavily", "firecrawl_key", "firecrawl_anon")


class PluginRegistryTests(unittest.TestCase):
    def test_plugin_ids_are_unique_and_cover_existing_vendors(self):
        plugins = builtin_plugins()
        ids = [plugin.id for plugin in plugins]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {
            "baidu", "brave", "parallel", "tavily", "exa", "firecrawl", "serpapi",
            "github", "hackernews", "stackexchange", "sov2ex", "twitter", "jina",
        })
        for plugin in plugins:
            self.assertIs(get_plugin(plugin.id), plugin)
            if plugin.balance is None:
                self.assertTrue(plugin.balance_note)
        self.assertEqual(get_plugin("stackexchange").search_sources, ("stackoverflow",))
        self.assertEqual(get_plugin("stackexchange").key_provider, "stackexchange")
        with self.assertRaises(KeyError):
            get_plugin("stackoverflow")

    def test_each_capability_has_exactly_one_plugin_owner(self):
        owners = Counter()
        for plugin in builtin_plugins():
            covered = set(plugin.search_sources)
            covered.update(spec.key_provider for spec in plugin.scrape_backends)
            owners.update(covered)
            if plugin.search_specs is not None:
                self.assertEqual(tuple(spec.name for spec in plugin.search_specs()), plugin.search_sources)
        self.assertEqual(owners, Counter({name: 1 for name in PROVIDER_CAPABILITIES}))

    def test_each_channel_and_historical_name_has_exactly_one_owner(self):
        owners = Counter(channel for plugin in builtin_plugins() for channel in plugin.scrape_channels)
        self.assertEqual(owners, Counter({name: 1 for name in CHANNEL_ORDER + ("jina", "firecrawl")}))
        for plugin in builtin_plugins():
            self.assertEqual(plugin.scrape_channels, tuple(spec.name for spec in plugin.scrape_backends))

    def test_auth_methods_keep_search_and_balance_credentials_separate(self):
        for plugin in builtin_plugins():
            if plugin.key_provider is None:
                self.assertEqual(plugin.auth_methods, ())
            else:
                self.assertIn(("api", plugin.key_provider, "search_key"), {
                    (method.type, method.credential, method.purpose) for method in plugin.auth_methods
                })
        self.assertEqual(
            {(plugin.id, method.credential, method.purpose)
             for plugin in builtin_plugins() for method in plugin.auth_methods if method.type == "oauth"},
            {("firecrawl", "firecrawl", "search_key"), ("parallel", "parallel_account", "balance_only")},
        )
        self.assertIn(("api", "exa_admin", "balance_only"), {
            (method.type, method.credential, method.purpose) for method in get_plugin("exa").auth_methods
        })
        self.assertEqual(get_plugin("exa").balance_credential, "exa_admin")
        self.assertEqual(get_plugin("parallel").balance_credential, "parallel_account")
        plugin = ProviderPlugin("fixture", "Fixture", "fixture_key")
        self.assertEqual(plugin.balance_credential, "fixture_key")
        self.assertEqual(plugin.balance_ttl_seconds, 300)

    def test_search_registry_preserves_order_and_every_metadata_field(self):
        providers = registry.build_provider_registry()
        self.assertEqual(tuple(providers), SEARCH_ORDER)
        self.assertEqual(set(providers), set(SEARCH_ORDER))
        # Frozen pre-plugin values, independent of the capability derivation.
        metadata = {
            "brave": ("brave", "brave", True, 15, "missing BRAVE_SEARCH_API_KEY / BRAVE_API_KEY"),
            "parallel": ("parallel", "parallel", True, 15, "missing PARALLEL_API_KEY"),
            "baidu": ("baidu", "baidu", True, 60, "missing BAIDU_QIANFAN_API_KEY / QIANFAN_API_KEY / APPBUILDER_API_KEY"),
            "tavily": ("tavily", "tavily", True, 15, "missing TAVILY_API_KEY"),
            "exa": ("exa", "exa", True, 20, "missing EXA_API_KEY"),
            "serpapi": ("serpapi", "serpapi", True, 20, "missing SERPAPI_API_KEY / SERPAPI_KEY"),
            "firecrawl": ("firecrawl", "firecrawl", True, 60, "missing FIRECRAWL_API_KEY"),
            "sov2ex": ("sov2ex", None, False, 20, "missing API key"),
            "github_repos": ("github-repos", "github", False, 20, "missing API key"),
            "github_code": ("github-code", "github", True, 20, "missing GITHUB_TOKEN / GH_TOKEN (GitHub code search requires a token)"),
            "hackernews": ("hackernews", None, False, 20, "missing API key"),
            "stackoverflow": ("stackoverflow", "stackexchange", False, 20, "missing API key"),
            "twitter": ("twitter", None, False, 20, "missing API key"),
        }
        for name, spec in providers.items():
            with self.subTest(source=name):
                self.assertEqual(spec.name, name)
                self.assertEqual((spec.public_name, spec.key_name, spec.key_required,
                                  spec.timeout_default, spec.missing_message), metadata[name])

    def test_all_search_calls_resolve_patches_after_registry_creation(self):
        providers = registry.build_provider_registry()
        counts = {name: index + 1 for index, name in enumerate(SEARCH_ORDER + ("github",))}
        cookies = {"auth_token": "fixture-cookie"}
        config = SearchRunnerConfig("all", counts, 10, "bing", {"twitter": cookies})
        publish = mock.Mock()
        context = SearchContext("all", 1.25, 123.5, {}, publish_partial=publish)
        for name in SEARCH_ORDER:
            with self.subTest(source=name):
                calls = []
                rows = [{"source": name}]

                def fake(*args, timeout=None, deadline=None, publish_partial=None, api_key=None):
                    calls.append((args, timeout, deadline, publish_partial, api_key))
                    return rows

                if name in {"sov2ex", "hackernews", "stackoverflow"}:
                    args = ("query", counts[name])
                elif name.startswith("github_"):
                    count_key = "github" if name == "github_repos" else name
                    args = ("query", counts[count_key], "fixture-key")
                elif name == "twitter":
                    args = ("query", counts[name], cookies)
                elif name == "serpapi":
                    args = ("query", "fixture-key", counts[name], "bing")
                else:
                    args = ("query", "fixture-key", counts[name])
                with mock.patch.object(registry, f"search_{name}", fake):
                    self.assertIs(providers[name].call("query", config, context, "fixture-key"), rows)
                self.assertEqual(calls, [(args, 1.25, 123.5,
                                         publish if name in {"serpapi", "twitter"} else None,
                                         "fixture-key" if name == "stackoverflow" else None)])

    def test_scrape_registry_preserves_metadata_order_and_dispatch(self):
        self.assertEqual(backends.KNOWN_BACKENDS, CHANNEL_ORDER)
        self.assertEqual(backends.DEFAULT_SCRAPE_CHAIN, CHANNEL_ORDER)
        self.assertEqual(backends.ACCEPTED_BACKENDS, CHANNEL_ORDER + ("jina", "firecrawl"))
        self.assertEqual(backends.KEYED_BACKENDS, ("jina_key", "exa", "tavily", "firecrawl_key"))
        self.assertEqual(scrape.KEYED_BACKENDS, backends.KEYED_BACKENDS)
        self.assertEqual(backends.LEGACY_BACKENDS, {
            "jina": ("jina_anon", "jina_key"), "firecrawl": ("firecrawl_key", "firecrawl_anon"),
        })
        expected = (
            ("jina_key", "jina", True, False), ("jina_anon", "jina", False, True),
            ("exa", "exa", True, False), ("tavily", "tavily", True, False),
            ("firecrawl_key", "firecrawl", True, False), ("firecrawl_anon", "firecrawl", False, True),
            ("jina", "jina", False, True), ("firecrawl", "firecrawl", False, False),
        )
        self.assertEqual(tuple((spec.name, spec.key_provider, spec.key_required, spec.supports_anonymous)
                               for spec in scrape._SCRAPE_BACKENDS + scrape._LEGACY_SPECS), expected)
        self.assertEqual(tuple(scrape._SCRAPE_DISPATCH), backends.ACCEPTED_BACKENDS)
        for name in backends.ACCEPTED_BACKENDS:
            self.assertIs(scrape._SCRAPE_DISPATCH[name], getattr(scrape, f"_scrape_{name}"))
            self.assertEqual(backends.backend_provider(name), scrape._BACKEND_BY_NAME[name].key_provider)

    def test_all_scrape_channels_use_historical_scraper_patch_points(self):
        url = "https://example.com/article"
        for channel in CHANNEL_ORDER + ("jina", "firecrawl"):
            provider = backends.backend_provider(channel)
            with self.subTest(channel=channel):
                with (
                    mock.patch.object(scrape, "_jina_anonymous_cooling_down", return_value=False),
                    mock.patch.object(scrape, f"scrape_url_{provider}",
                                      return_value={"url": url, "markdown": "fixture body"}) as fake,
                ):
                    result = scrape.scrape_url_smart(url, backends=[channel], **{f"{provider}_key": "fixture-key"})
                self.assertEqual(result["markdown"], "fixture body")
                self.assertEqual(result["via"], provider)
                fake.assert_called_once()
                expected_key = "" if channel in {"jina_anon", "firecrawl_anon", "jina"} else "fixture-key"
                self.assertEqual(fake.call_args.args[:2], (url, expected_key))


class BalanceContractTests(unittest.TestCase):
    def test_report_to_dict_is_json_serializable_without_losing_unknowns(self):
        report = BalanceReport(
            provider="fixture", status="ok", scope="team", unit="usd", remaining=1.5,
            limit=None, used=2, resets_at="2026-12-01T00:00:00+00:00", period="month",
            key_fingerprint="sha256:fixture", error_kind=None, message="fixture report",
            fetched_at="2026-11-11T00:00:00+00:00",
        )
        data = report.to_dict()
        self.assertEqual(json.loads(json.dumps(data, allow_nan=False)), {
            "provider": "fixture", "status": "ok", "scope": "team", "unit": "usd",
            "remaining": 1.5, "limit": None, "used": 2, "resets_at": "2026-12-01T00:00:00+00:00",
            "period": "month", "key_fingerprint": "sha256:fixture", "error_kind": None,
            "message": "fixture report", "fetched_at": "2026-11-11T00:00:00+00:00",
        })
        unknown = BalanceReport("fixture", "unsupported")
        self.assertIsNone(unknown.remaining)
        self.assertIsNone(unknown.limit)
        self.assertIsNone(unknown.used)
        self.assertIsNotNone(datetime.fromisoformat(unknown.fetched_at).tzinfo)

    def test_context_injects_http_and_caps_timeout_at_monotonic_deadline(self):
        response = object()
        http = mock.Mock(return_value=response)
        context = BalanceContext(timeout=10, deadline=105, http=http)
        with mock.patch.object(base.time, "monotonic", return_value=100):
            self.assertIs(context.open("https://example.com/balance", retries=0), response)
        http.assert_called_once_with("https://example.com/balance", timeout=5.0, retries=0, deadline=105)

    def test_expired_context_never_calls_http(self):
        http = mock.Mock()
        context = BalanceContext(timeout=10, deadline=99, http=http)
        with mock.patch.object(base.time, "monotonic", return_value=100):
            with self.assertRaises(TimeoutError):
                context.open("https://example.com/balance")
        http.assert_not_called()

    def test_context_defaults_to_shared_retry_http(self):
        with mock.patch.object(base.support_http, "urlopen_retry") as http:
            context = BalanceContext(timeout=2)
            context.open("https://example.com/balance")
        http.assert_called_once_with("https://example.com/balance", timeout=2.0, retries=2, deadline=None)


if __name__ == "__main__":
    unittest.main()
