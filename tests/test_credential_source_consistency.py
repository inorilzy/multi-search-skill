"""Consistent credential-source decisions and isolation of broken entries.

Regression coverage for the review findings that the desktop, `doctor`/`keys
status`, and a real search disagreed about a key's effective source, and that a
single unreadable credential-store entry made every search fail, including
sources that need no key at all.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.search.search_runner import (
    ProviderSpec,
    SearchRunner,
    SearchRunnerConfig,
)
from multi_search_mcp.src.state.keys import (
    LoadedKeys,
    key_sources,
    load_keys,
    load_keys_detailed,
)
from multi_search_mcp.src.support.credential_store import CredentialStore, CredentialStoreError


SYNTHETIC_STORE_KEY = "synthetic-store-key-0201"
SYNTHETIC_FILE_KEY = "synthetic-file-key-0202"


class MemoryBackend:
    def __init__(self):
        self.entries: dict[str, bytes] = {}
        self.fail: Exception | None = None

    def read(self, target):
        if self.fail is not None:
            raise self.fail
        return self.entries.get(target)

    def write(self, target, blob):
        if self.fail is not None:
            raise self.fail
        self.entries[target] = blob

    def delete(self, target):
        if self.fail is not None:
            raise self.fail
        return self.entries.pop(target, None) is not None


class CredentialFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="credential-source-")
        self.addCleanup(self.temp.cleanup)
        self.keys_file = Path(self.temp.name) / "search-keys.json"
        self.backend = MemoryBackend()
        self.store = CredentialStore(self.backend, namespace="ns-source")

    def write_file(self, data):
        self.keys_file.write_text(json.dumps(data), encoding="utf-8")

    def corrupt_entry(self, provider):
        self.backend.entries[self.store.target(provider)] = b"{not json"


class SourceDecisionTests(CredentialFixture):
    def test_key_sources_and_load_keys_share_one_decision(self):
        self.write_file({"tavily": SYNTHETIC_FILE_KEY, "brave": SYNTHETIC_FILE_KEY})
        self.store.set("exa", SYNTHETIC_STORE_KEY)
        self.corrupt_entry("tavily")
        environ = {"BRAVE_SEARCH_API_KEY": "synthetic-env-brave-0203"}

        sources = key_sources(self.keys_file, environ=environ, credential_store=self.store)
        loaded = load_keys_detailed(self.keys_file, environ=environ, credential_store=self.store)

        expected = {
            "brave": "env",
            "exa": "credential_store",
            "tavily": "unavailable",
        }
        for provider, effective in expected.items():
            with self.subTest(provider=provider):
                self.assertEqual(sources[provider]["effective_source"], effective)
                if effective == "unavailable":
                    # Fail closed: no plaintext fallback, explicit error instead.
                    self.assertNotIn(provider, loaded.keys)
                    self.assertIn(provider, loaded.errors)
                else:
                    self.assertIn(provider, loaded.keys)
                    self.assertNotIn(provider, loaded.errors)
        # A provider with no env/store/file entry is "none" everywhere and unused.
        for provider in ("baidu", "parallel", "serpapi", "github", "firecrawl"):
            with self.subTest(provider=provider):
                self.assertEqual(sources[provider]["effective_source"], "none")
                self.assertNotIn(provider, loaded.keys)

    def test_one_corrupt_entry_only_affects_that_provider(self):
        self.write_file({"brave": SYNTHETIC_FILE_KEY})
        self.store.set("exa", SYNTHETIC_STORE_KEY)
        self.corrupt_entry("tavily")

        loaded = load_keys_detailed(self.keys_file, environ={}, credential_store=self.store)
        self.assertEqual(loaded.keys["brave"], SYNTHETIC_FILE_KEY)
        self.assertEqual(loaded.keys["exa"], SYNTHETIC_STORE_KEY)
        self.assertNotIn("tavily", loaded.keys)
        self.assertEqual(list(loaded.errors), ["tavily"])
        message = loaded.errors["tavily"]
        self.assertIn("credential store unavailable for tavily", message)
        self.assertIn("unreadable", message)
        for secret in (SYNTHETIC_STORE_KEY, SYNTHETIC_FILE_KEY):
            self.assertNotIn(secret, message)
            self.assertNotIn(secret, json.dumps(key_sources(
                self.keys_file, environ={}, credential_store=self.store,
            )))

    def test_unreadable_store_reports_unavailable_but_env_still_wins(self):
        self.write_file({"brave": SYNTHETIC_FILE_KEY, "tavily": SYNTHETIC_FILE_KEY})
        self.backend.fail = CredentialStoreError("credential store access denied")
        sources = key_sources(
            self.keys_file, environ={"BRAVE_SEARCH_API_KEY": "synthetic-env-brave-0203"},
            credential_store=self.store,
        )
        loaded = load_keys_detailed(
            self.keys_file, environ={"BRAVE_SEARCH_API_KEY": "synthetic-env-brave-0203"},
            credential_store=self.store,
        )
        self.assertEqual(sources["brave"]["effective_source"], "env")
        self.assertEqual(loaded.keys["brave"], "synthetic-env-brave-0203")
        self.assertNotIn("brave", loaded.errors)
        for provider in ("parallel", "tavily", "exa", "firecrawl", "serpapi", "github", "baidu"):
            with self.subTest(provider=provider):
                self.assertEqual(sources[provider]["effective_source"], "unavailable")
                self.assertNotIn(provider, loaded.keys)
                self.assertIn(provider, loaded.errors)

    def test_rows_expose_the_desktop_contract_fields(self):
        self.store.set("exa", SYNTHETIC_STORE_KEY)
        row = key_sources(self.keys_file, environ={}, credential_store=self.store)["exa"]
        for field in ("effective_source", "env_vars_set", "env_overrides_store",
                      "credential_store", "file_present", "file_key_count"):
            self.assertIn(field, row)
        self.assertEqual(row["credential_store"], "present")
        self.corrupt_entry("brave")
        broken = key_sources(self.keys_file, environ={}, credential_store=self.store)["brave"]
        self.assertEqual(broken["credential_store"], "unavailable")
        self.assertTrue(broken["credential_store_error"])


class RuntimeIsolationTests(CredentialFixture):
    def _provider_specs(self):
        return {
            "brave": ProviderSpec(
                name="brave", public_name="brave", key_name="brave",
                call=lambda *_: [{"source": "brave", "error": "must not be called"}],
            ),
            "hackernews": ProviderSpec(
                name="hackernews", public_name="hackernews", key_name=None,
                call=lambda *_: [{
                    "source": "hackernews", "title": "Story",
                    "url": "https://news.ycombinator.com/item?id=fixture",
                }],
            ),
        }

    def test_runner_fails_only_the_provider_with_a_broken_entry(self):
        runner = SearchRunner(
            SearchRunnerConfig(
                "default", {"brave": 1}, 10, "google", {},
                key_errors={"brave": "credential store unavailable for brave: entry is unreadable"},
            ),
            self._provider_specs(),
            route_resolver=lambda _route: {"brave", "hackernews"},
        )
        rows = runner.run("fixture")
        by_source = {row["source"]: row for row in rows}
        self.assertEqual(by_source["brave"]["error_type"], "credential_store")
        self.assertIn("credential store unavailable for brave", by_source["brave"]["error"])
        self.assertNotIn("must not be called", json.dumps(rows))
        self.assertEqual(by_source["hackernews"]["title"], "Story")

    def test_search_keeps_keyless_sources_when_a_key_entry_is_unreadable(self):
        broken = "credential store unavailable for brave: stored credential for brave is unreadable"
        with mock.patch.object(service, "load_keys", return_value=LoadedKeys({}, {"brave": broken})):
            response = service.run_search_web(
                {"query": "fixture", "sources": ["brave", "hackernews"],
                 "use_state": False, "no_fetch": True},
                providers=self._provider_specs(), config={},
            )
        status = {row["source"]: row for row in response["provider_status"]}
        self.assertEqual(status["brave"]["status"], "error")
        self.assertEqual(status["brave"]["errors"][0]["error_type"], "credential_store")
        self.assertIn("stored credential for brave is unreadable",
                      status["brave"]["errors"][0]["error"])
        self.assertEqual(status["hackernews"]["status"], "ok")
        self.assertEqual([row["url"] for row in response["results"]],
                         ["https://news.ycombinator.com/item?id=fixture"])

    def test_broken_entry_never_makes_load_keys_raise(self):
        self.write_file({"tavily": SYNTHETIC_FILE_KEY})
        self.corrupt_entry("tavily")
        # Callers that only need "what keys can I use" still get a mapping.
        keys = load_keys(self.keys_file, environ={}, credential_store=self.store)
        self.assertIsInstance(keys, dict)
        self.assertNotIn("tavily", keys)


class CommandSurfaceTests(CredentialFixture):
    def test_doctor_exposes_the_same_per_provider_source_payload(self):
        from multi_search_mcp.src.state.state_store import StateStore

        self.write_file({"brave": SYNTHETIC_FILE_KEY})
        self.corrupt_entry("tavily")
        report = key_sources(self.keys_file, environ={}, credential_store=self.store)
        for provider in ("tavily", "brave"):
            self.assertNotIn(SYNTHETIC_FILE_KEY, json.dumps(report[provider]))
        self.assertEqual(report["tavily"]["effective_source"], "unavailable")
        self.assertEqual(report["brave"]["effective_source"], "file")

        # `doctor --format json` is the desktop's source of truth for these rows.
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            service, "StateStore", return_value=StateStore(Path(temp) / "state.sqlite"),
        ), mock.patch.object(service, "load_keys", return_value={}), \
                mock.patch.object(service, "key_sources", return_value=report):
            data = service.doctor_data(include_keys=True)
        self.assertEqual(data["key_sources"], report)
        self.assertNotIn(SYNTHETIC_FILE_KEY, json.dumps(data))


if __name__ == "__main__":
    unittest.main()
