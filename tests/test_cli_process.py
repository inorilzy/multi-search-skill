"""Real CLI processes against controlled HTTP responses, with no MCP or keys."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from scripts.test_isolation import isolated_test_environment


ROOT = Path(__file__).resolve().parents[1]
URL = "https://93.184.216.34/article"
BODY = "# Fixture article\n\n" + "正文 evidence passage. " * 200

# Inject only external HTTP/time boundaries. Core, adapters, RRF, URL validation,
# source registration and SQLite persistence are the real installed implementation.
BOOTSTRAP = r'''
import datetime
import email.message
import importlib.abc
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.response
import test_isolation

test_isolation.activate_from_environment()

if os.environ.get("CLI_FIXTURE_KEYLESS"):
    import socket
    guarded_getaddrinfo = socket.getaddrinfo
    def fixture_getaddrinfo(host, port, *args, **kwargs):
        if host == "www.v2ex.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 443))]
        return guarded_getaddrinfo(host, port, *args, **kwargs)
    socket.getaddrinfo = fixture_getaddrinfo

class NoMCP(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mcp" or fullname.startswith("mcp."):
            raise ImportError("MCP is unavailable in this acceptance process")
sys.meta_path.insert(0, NoMCP())

if os.environ.get("CLI_FIXTURE_FUTURE"):
    OriginalDateTime = datetime.datetime
    class FutureDateTime(OriginalDateTime):
        @classmethod
        def now(cls, tz=None):
            return OriginalDateTime.now(tz) + datetime.timedelta(days=2)
    datetime.datetime = FutureDateTime

class ProviderHTTP(urllib.request.BaseHandler):
    handler_order = 100
    def https_open(self, request):
        parsed = urllib.parse.urlsplit(request.full_url)
        if parsed.hostname == "hn.algolia.com":
            query = urllib.parse.parse_qs(parsed.query)["query"][0]
            if query == "failure":
                raise urllib.error.HTTPError(request.full_url, 503, "fixture provider unavailable", {}, io.BytesIO(b""))
            hits = [] if query == "empty" else [{"objectID": "42", "title": "Fixture article", "url": "https://93.184.216.34/article", "points": 7}]
            payload = {"hits": hits}
        elif parsed.hostname == "api.stackexchange.com":
            payload = {"items": [{"title": "Fixture Stack Overflow", "link": "https://93.184.216.34/question", "tags": []}]}
        elif parsed.hostname == "www.sov2ex.com":
            payload = {"hits": [{"_source": {"id": 42, "title": "Fixture V2EX"}}]}
        elif parsed.hostname == "api.tavily.com":
            # The Bearer must equal the expected synthetic key; the query selects the outcome.
            if (request.get_header("Authorization") or "") != "Bearer " + os.environ.get("CLI_FIXTURE_TAVILY_KEY", ""):
                raise urllib.error.HTTPError(request.full_url, 401, "fixture rejects key", {}, io.BytesIO(b'{"detail":{"error":"bad key"}}'))
            query = json.loads(request.data.decode())["query"]
            if query == "quota":
                raise urllib.error.HTTPError(request.full_url, 432, "fixture quota", {}, io.BytesIO(b'{"detail":{"error":"Plan usage limit exceeded"}}'))
            if query == "network":
                raise urllib.error.URLError("fixture network down")
            payload = {"results": [{"title": "Fixture tavily", "url": "https://93.184.216.34/article", "content": "snippet", "score": 0.9}]}
        elif parsed.hostname == "r.jina.ai":
            if os.environ.get("CLI_FIXTURE_NO_HTTP"):
                raise AssertionError("cached fetch/read unexpectedly contacted a provider")
            payload = {"data": {"title": "Fixture article", "content": "# Fixture article\n\n" + "正文 evidence passage. " * 200}}
        else:
            raise AssertionError("unexpected external HTTP endpoint: " + request.full_url)
        response = urllib.response.addinfourl(io.BytesIO(json.dumps(payload).encode()), email.message.Message(), request.full_url, 200)
        response.msg = "OK"
        return response

from multi_search_mcp.src.support import http
if os.environ.get("MULTI_SEARCH_ACCEPTANCE_INSTALLED"):
    assert "site-packages" in str(http.__file__), http.__file__
http._shared_opener.add_handler(ProviderHTTP())
'''


class CliProcessTests(unittest.TestCase):
    def setUp(self):
        self.installed = os.environ.get("MULTI_SEARCH_ACCEPTANCE_INSTALLED") == "1"
        self.context = isolated_test_environment(source_root=None if self.installed else ROOT,
                                                 include_inherited_pythonpath=False)
        self.isolation = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.addCleanup(self.isolation.assert_clean)
        # Extend the disposable runner bootstrap, not any product installation.
        (self.isolation.root / "bootstrap" / "sitecustomize.py").write_text(BOOTSTRAP, encoding="utf-8")
        self.environment = dict(os.environ)

    def run_cli(self, *args, future=False, no_http=False):
        if self.installed:
            import sysconfig
            console = Path(sysconfig.get_path("scripts")) / ("multi-search.exe" if os.name == "nt" else "multi-search")
            command = [str(console), *args]
        else:
            command = [sys.executable, "-B", "-m", "multi_search_mcp.cli", *args]
        return subprocess.run(command, cwd=self.isolation.root,
                              env=dict(self.environment, CLI_FIXTURE_FUTURE="1" if future else "",
                                       CLI_FIXTURE_NO_HTTP="1" if no_http else ""),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)

    def test_keyless_source_controls_reach_real_cli_and_controlled_http_independently(self):
        config = self.isolation.root / "source-test.json"
        config.write_text(json.dumps({"no_scrape": True}), encoding="utf-8")
        self.environment["MULTI_SEARCH_CONFIG"] = str(config)
        self.environment["CLI_FIXTURE_KEYLESS"] = "1"
        for source in ("hackernews", "stackoverflow", "sov2ex"):
            with self.subTest(source=source):
                result = self.run_cli("search", "fixture", "--source", source, "--format", "json")
                self.assertEqual(result.returncode, 0, result.stderr)
                rows = json.loads(result.stdout)["provider_status"]
                self.assertEqual([row["source"] for row in rows], [source])
                self.assertEqual(rows[0]["status"], "ok")

    def test_packaging_has_only_the_cli_entry_and_no_mcp_dependency(self):
        # Python 3.10 has no tomllib; use the stable declared console/dependency
        # lines here and inspect actual wheel metadata in smoke_install.py.
        import configparser
        import re
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        scripts = configparser.ConfigParser()
        scripts.read_string("[scripts]\n" + text.split("[project.scripts]\n")[1].split("\n[", 1)[0])
        metadata = {"scripts": {name: value.strip('\"') for name, value in scripts["scripts"].items()},
                    "dependencies": re.findall(r'\"([^\"]+)\"', text.split("dependencies = [", 1)[1].split("]", 1)[0])}
        self.assertEqual(metadata["scripts"], {"multi-search": "multi_search_mcp.cli:entrypoint"})
        self.assertFalse(any(dep.startswith("mcp") for dep in metadata["dependencies"]))

    def test_search_fetch_read_preserve_reference_and_complete_body_across_processes(self):
        searched = self.run_cli("search", "fixture", "--source", "hackernews")
        self.assertEqual(searched.returncode, 0, searched.stderr)
        payload = json.loads(searched.stdout)
        hit = payload["results"][0]
        self.assertEqual(hit["url"], URL)
        self.assertEqual(hit["providers"], ["hackernews"])
        self.assertTrue(hit["source_id"].startswith("src_"))
        self.assertEqual(payload["scrapes"][0]["markdown"], BODY[:1200])
        fetched = self.run_cli("fetch", hit["source_id"], "--full-content", no_http=True)
        self.assertEqual(fetched.returncode, 0, fetched.stderr)
        self.assertEqual(json.loads(fetched.stdout)["body"], BODY)
        self.assertTrue(json.loads(fetched.stdout)["cache_hit"])
        read = self.run_cli("read", hit["source_id"], "--offset", "1200", "--limit", "200", no_http=True)
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertEqual(json.loads(read.stdout)["content"], BODY[1200:1400])

    def test_version_probe_reports_installed_distribution_without_configuration(self):
        import importlib.metadata
        result = self.run_cli("--version", no_http=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "multi-search " + importlib.metadata.version("multi-search-mcp"))

    def test_missing_and_expired_references_are_structured_errors(self):
        missing = self.run_cli("fetch", "src_missing")
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(json.loads(missing.stdout)["error_type"], "invalid_request")
        self.assertIn("unknown or expired", json.loads(missing.stdout)["error"])
        searched = self.run_cli("search", "fixture", "--source", "hackernews")
        source_id = json.loads(searched.stdout)["results"][0]["source_id"]
        read = self.run_cli("read", source_id, future=True, no_http=True)
        self.assertEqual(read.returncode, 1)
        self.assertIn("missing or expired", json.loads(read.stdout)["error"])
        fetch = self.run_cli("fetch", source_id, future=True, no_http=True)
        self.assertEqual(fetch.returncode, 1)
        self.assertIn("unknown or expired", json.loads(fetch.stdout)["error"])

    def test_production_url_validation_rejects_loopback_even_with_fixture(self):
        result = self.run_cli("fetch", "--url", "http://127.0.0.1/private")
        self.assertEqual(result.returncode, 1)
        self.assertIn("loopback", json.loads(result.stdout)["error"])

    def test_zero_partial_and_all_failed_searches_have_distinct_outcomes(self):
        cases = (("empty", ["hackernews"], "empty", 0),
                 ("fixture", ["hackernews", "brave"], "partial", 0),
                 ("failure", ["hackernews", "brave"], "failed", 1))
        for query, sources, outcome, exit_code in cases:
            for output_format in ("json", "human", "markdown"):
                with self.subTest(query=query, output_format=output_format):
                    args = ["search", query, "--format", output_format]
                    for source in sources:
                        args.extend(["--source", source])
                    result = self.run_cli(*args)
                    self.assertEqual(result.returncode, exit_code, result.stderr)
                    if output_format == "json":
                        payload = json.loads(result.stdout)
                        self.assertEqual(payload["outcome"], outcome)
                        if "brave" in sources:
                            self.assertTrue(any(row["source"] == "brave" and "missing" in row["error"] for row in payload["errors"]))
                        if query == "failure":
                            self.assertTrue(any(row["source"] == "hackernews" and "503" in row["error"] for row in payload["errors"]))
                    else:
                        self.assertIn("outcome: " + outcome, result.stdout)
                        if "brave" in sources:
                            self.assertIn("missing BRAVE", result.stdout)
                        if query == "failure":
                            self.assertIn("503", result.stdout)

    @unittest.skipUnless(sys.platform == "win32", "Windows Credential Manager is Windows-only")
    def test_store_backed_tavily_search_follows_save_replace_and_delete(self):
        from multi_search_mcp.src.support.credential_store import default_store
        namespace = f"ticket04-search-{os.getpid()}"
        env = dict(self.environment, MULTI_SEARCH_CREDENTIAL_NAMESPACE=namespace)
        env.pop("TAVILY_API_KEY", None)
        store = default_store(env)
        self.addCleanup(store.delete, "tavily")

        def search(expected_key_value):
            child_env = dict(env, CLI_FIXTURE_TAVILY_KEY=expected_key_value)
            return subprocess.run(
                [sys.executable, "-B", "-m", "multi_search_mcp.cli", "search", "ok",
                 "--source", "tavily", "--format", "json"],
                cwd=self.isolation.root, env=child_env,
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )

        store.set("tavily", "synthetic-search-key-0013")
        first = search("synthetic-search-key-0013")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)["provider_status"][0]["status"], "ok")
        self.assertNotIn("synthetic-search-key-0013", first.stdout + first.stderr)

        store.set("tavily", "synthetic-search-key-0014")
        replaced = search("synthetic-search-key-0014")
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        stale = search("synthetic-search-key-0013")
        self.assertEqual(json.loads(stale.stdout)["provider_status"][0]["errors"][0]["error_type"], "invalid")

        store.delete("tavily")
        missing = search("synthetic-search-key-0014")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("missing TAVILY_API_KEY", missing.stdout + missing.stderr)
        self.assertNotIn("synthetic-search-key-0014", missing.stdout + missing.stderr)

        # Outcome classes through the same store-backed process path, including the key-pool
        # wrapper (search_runner.py), which must preserve the provider's error_type.
        # A fresh key per case: a 432 persists key cooldown in the isolated state DB, so reusing
        # one key would make later children report "missing API key" instead of the outcome.
        for index, (query, expected) in enumerate((("quota", "quota_exhausted"), ("network", "network"))):
            key_value = f"synthetic-search-key-001{5 + index}"
            store.set("tavily", key_value)
            outcome = subprocess.run(
                [sys.executable, "-B", "-m", "multi_search_mcp.cli", "search", query,
                 "--source", "tavily", "--format", "json"],
                cwd=self.isolation.root, env=dict(env, CLI_FIXTURE_TAVILY_KEY=key_value),
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            errors = json.loads(outcome.stdout)["provider_status"][0]["errors"]
            self.assertEqual(errors[0]["error_type"], expected, query)
            self.assertNotIn(key_value, outcome.stdout + outcome.stderr)

    @unittest.skipUnless(sys.platform == "win32", "Windows Credential Manager is Windows-only")
    def test_migrated_legacy_key_is_used_by_independent_search_without_env_override(self):
        """Migrate a synthetic legacy key with the real `migrate-legacy` CLI, then search in a
        separate process. External HTTP is replaced only at the urllib opener inside the child
        (ProviderHTTP in BOOTSTRAP); no real network is used and NetworkGuard is active in the
        child via test_isolation.activate_from_environment. The expected key lives only in this
        fixture and is supplied to the child as CLI_FIXTURE_TAVILY_KEY, never as a provider env
        var, so the store is the only key source. Key values are never printed or asserted in output.
        """
        import tempfile
        from multi_search_mcp.src.state.keys import key_sources
        from multi_search_mcp.src.support.credential_store import default_store

        migrated_value = "synthetic-migrate-key-0021"
        namespace = f"ticket09-search-{os.getpid()}"
        env = dict(self.environment, MULTI_SEARCH_CREDENTIAL_NAMESPACE=namespace)
        env.pop("TAVILY_API_KEY", None)
        store = default_store(env)
        self.addCleanup(store.delete, "tavily")
        store.delete("tavily")

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        keys_file = Path(tmp.name) / "search-keys.json"
        keys_file.write_text(json.dumps({"tavily": migrated_value}), encoding="utf-8")
        source_bytes = keys_file.read_bytes()
        request_file = Path(tmp.name) / "request.json"

        def migrate(*args):
            return subprocess.run(
                [sys.executable, "-B", "-m", "multi_search_mcp.cli", "migrate-legacy", *args,
                 "--keys-file", str(keys_file), "--format", "json"],
                cwd=self.isolation.root, env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=30,
            )

        def plan_and_apply():
            plan_run = migrate("plan")
            self.assertEqual(plan_run.returncode, 0, plan_run.stderr)
            self.assertNotIn(migrated_value, plan_run.stdout + plan_run.stderr)
            plan = json.loads(plan_run.stdout)
            request_file.write_text(json.dumps({"plan_token": plan["plan_token"],
                                                "approved": ["tavily"], "choices": {}}), encoding="utf-8")
            apply_run = migrate("apply", "--request", str(request_file))
            self.assertEqual(apply_run.returncode, 0, apply_run.stderr)
            self.assertNotIn(migrated_value, apply_run.stdout + apply_run.stderr)
            return json.loads(apply_run.stdout)

        first = plan_and_apply()
        self.assertEqual(first["written"], ["tavily"])
        self.assertEqual(first["unchanged"], [])
        self.assertTrue(first["complete"])
        self.assertEqual(store.get("tavily"), migrated_value)

        # No provider env var is set, so the store must be the effective source.
        report = key_sources(keys_file=keys_file, environ=env, credential_store=store)
        self.assertEqual(report["tavily"]["effective_source"], "credential_store")
        self.assertFalse(report["tavily"]["env_overrides_store"])

        searched = subprocess.run(
            [sys.executable, "-B", "-m", "multi_search_mcp.cli", "search", "ok",
             "--source", "tavily", "--format", "json"],
            cwd=self.isolation.root, env=dict(env, CLI_FIXTURE_TAVILY_KEY=migrated_value),
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(searched.returncode, 0, searched.stderr)
        self.assertEqual(json.loads(searched.stdout)["provider_status"][0]["status"], "ok")
        self.assertNotIn(migrated_value, searched.stdout + searched.stderr)

        # Repeat is idempotent: the same key is already current and nothing is written.
        second = plan_and_apply()
        self.assertEqual(second["written"], [])
        self.assertEqual(second["unchanged"], ["tavily"])
        self.assertTrue(second["complete"])

        # The legacy source file is never modified by plan or apply.
        self.assertEqual(keys_file.read_bytes(), source_bytes)


if __name__ == "__main__":
    unittest.main()
