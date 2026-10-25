"""Synthetic regressions for deadline, authorization and managed-cookie boundaries."""
import io
import os
import tempfile
import threading
import time
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.support import http, url_security
from multi_search_mcp.src.support.credential_store import validate_twitter_cookies, CredentialStore, CredentialStoreError
from multi_search_mcp.src.providers.xkit import ManagedTwitterCookies, load_twitter_cookies
from multi_search_mcp.src.state import runtime
from multi_search_mcp.src.scrape.fetch import _scope_keys
from multi_search_mcp.src.state.key_state import SQLiteKeyManager
from multi_search_mcp.src.state.state_store import StateStore


class RemainingBoundariesTests(unittest.TestCase):
    def test_literal_fake_ip_rejected_even_with_opt_in(self):
        with mock.patch.dict(os.environ, {url_security.FAKE_IP_ENV: '1'}):
            with self.assertRaises(url_security.UrlSecurityError):
                http._ensure_connect_address('198.18.0.1')
            http._ensure_connect_address('198.18.0.1', resolved=True)

    def test_redirect_resolver_called_once_and_answers_pinned(self):
        resolver = mock.Mock(side_effect=[['93.184.216.34'], ['127.0.0.1']])
        req = urllib.request.Request('https://example.com/a')
        req._multi_search_deadline = time.monotonic() + 1
        result = http._SafeHTTPRedirectHandler(resolver=resolver).redirect_request(req, io.BytesIO(), 302, 'Found', {}, 'https://example.com/b')
        resolver.assert_called_once_with('example.com')
        self.assertEqual(result._multi_search_pinned_addresses[('example.com', 443)][0][4][0], '93.184.216.34')

    def test_slow_redirect_resolver_is_deadline_bounded(self):
        release = threading.Event()
        req = urllib.request.Request('https://example.com/a')
        req._multi_search_deadline = time.monotonic() + .03
        start = time.monotonic()
        try:
            with self.assertRaises(url_security.UrlSecurityError):
                http._SafeHTTPRedirectHandler(resolver=lambda _: (release.wait(1), ['93.184.216.34'])[1]).redirect_request(req, io.BytesIO(), 302, 'Found', {}, 'https://example.com/b')
            self.assertLess(time.monotonic() - start, .3)
        finally:
            release.set()

    def test_dns_remaining_recomputed_after_admission(self):
        future = mock.Mock()
        pool = mock.Mock()
        clock = [10.0]
        def submit(*args):
            clock[0] = 10.8
            return future
        pool.submit_nowait.side_effect = submit
        with mock.patch.object(url_security, '_DNS_POOL', pool), mock.patch.object(url_security.time, 'monotonic', side_effect=lambda: clock[0]):
            url_security._run_bounded_dns(lambda: [], deadline=11.0)
        self.assertAlmostEqual(future.result.call_args.kwargs['timeout'], .2)

    def test_atomic_reservation_distributes_two_simultaneous_attempts(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = SQLiteKeyManager(StateStore(Path(temp)/'state.sqlite'))
            candidates = manager.candidates('exa', ['one', 'two'])
            with ThreadPoolExecutor(max_workers=2) as pool:
                selected = list(pool.map(lambda _: manager.reserve('exa', candidates), range(2)))
            self.assertEqual({c.key for c in selected}, {'one', 'two'})
            self.assertEqual([r['use_count'] for r in manager.status_rows()], [1, 1])

    def test_scope_only_tracks_relevant_backend_keys(self):
        a = _scope_keys({'exa': 'one', 'brave': 'unrelated'}, ['direct'], ['exa'])
        b = _scope_keys({'exa': 'one', 'brave': 'rotated'}, ['direct'], ['exa'])
        self.assertEqual(a, b)
        self.assertNotEqual(a, _scope_keys({'exa': 'two'}, ['direct'], ['exa']))


class ManagedCookieTests(unittest.TestCase):
    cookies = {'auth_token': 'synthetic-auth', 'ct0': 'synthetic-csrf'}

    def test_runtime_reference_does_not_decrypt_or_read_file(self):
        with mock.patch.object(runtime, 'load_keys', return_value={}), mock.patch('multi_search_mcp.src.support.credential_store.default_store') as store:
            keys = runtime.load_runtime_keys({'twitter_cookies_mode': 'managed'})
        self.assertIsInstance(keys['twitter_cookies_path'], ManagedTwitterCookies)
        store.assert_not_called()

    def test_managed_load_returns_map_directly_without_files(self):
        with mock.patch('multi_search_mcp.src.providers.xkit.sys.platform', 'win32'), mock.patch('multi_search_mcp.src.support.credential_store.default_store') as store, mock.patch('builtins.open', side_effect=AssertionError('no plaintext file')):
            store.return_value.get.return_value = self.cookies
            self.assertEqual(load_twitter_cookies(ManagedTwitterCookies()), self.cookies)
            store.return_value.get.assert_called_once_with('twitter_cookies')

    def test_missing_corrupt_and_unsupported_fail_closed(self):
        with mock.patch('builtins.open', side_effect=AssertionError('no fallback')):
            with mock.patch('multi_search_mcp.src.providers.xkit.sys.platform', 'linux'):
                with self.assertRaisesRegex(ValueError, 'Windows DPAPI'):
                    load_twitter_cookies(ManagedTwitterCookies())
            with mock.patch('multi_search_mcp.src.providers.xkit.sys.platform', 'win32'), mock.patch('multi_search_mcp.src.support.credential_store.default_store') as store:
                for value in (None, {'auth_token': 'secret'}, {'auth_token': '\nsecret', 'ct0': 'secret'}):
                    store.return_value.get.return_value = value
                    with self.assertRaisesRegex(ValueError, 'unavailable or invalid') as exc:
                        load_twitter_cookies(ManagedTwitterCookies())
                    self.assertNotIn('secret', str(exc.exception))

    def test_cookie_contract_and_independent_provider(self):
        from multi_search_mcp.src.state.keys import CREDENTIAL_STORE_PROVIDERS
        self.assertNotIn('twitter_cookies', CREDENTIAL_STORE_PROVIDERS)
        self.assertEqual(validate_twitter_cookies(self.cookies), self.cookies)
        for value in ({**self.cookies, 'bad-name': 'x'}, {**self.cookies, 'big': '中'*2000}, {**self.cookies, 'control': '\x85'}):
            with self.assertRaises(ValueError):
                validate_twitter_cookies(value)

    def test_unknown_mode_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'unsupported Twitter'):
            runtime.load_runtime_keys({'twitter_cookies_mode': 'other'})


class SiteHistoryMigrationTests(unittest.TestCase):
    def test_history_sanitizes_without_erasing_site_preferences(self):
        from multi_search_mcp.src.state.site_memory import SiteScraperMemory, ScrapeAttempt
        with tempfile.TemporaryDirectory() as temp:
            store = StateStore(Path(temp)/'state.sqlite')
            memory = SiteScraperMemory(store)
            memory.record_attempt(ScrapeAttempt('https://example.com/a', 'jina', True, 900))
            memory.set_preference('example.com', 'jina', 7)
            store.execute("DELETE FROM privacy_migrations")
            secret = 'https://user:password@example.com/token-in-path?token=value#fragment'
            store.execute("UPDATE scrape_attempts SET url=?,error_message='unstructured-secret'", (secret,))
            store.execute("UPDATE site_scraper_stats SET sample_url=?,last_error_message='unstructured-secret'", (secret,))
            SiteScraperMemory(store)
            row = store.rows('SELECT * FROM site_scraper_stats')[0]
            self.assertEqual(row['sample_url'], 'https://example.com/')
            self.assertEqual(row['last_error_message'], '')
            self.assertEqual(row['success_count'], 1)
            self.assertEqual(row['manual_priority'], 7)
            self.assertTrue(row['manually_pinned'])
            self.assertEqual(store.rows('SELECT url,error_message FROM scrape_attempts'), [{'url':'https://example.com/', 'error_message':''}])

    def test_many_sites_obey_global_history_bound(self):
        from multi_search_mcp.src.state import site_memory as module
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(module, 'MAX_ATTEMPTS_TOTAL', 3):
            store = StateStore(Path(temp)/'state.sqlite')
            memory = module.SiteScraperMemory(store)
            for index in range(6):
                memory.record_attempt(module.ScrapeAttempt(f'https://u:secret@site{index}.example/private-secret', 'jina', True, 900))
            self.assertEqual(len(store.rows('SELECT * FROM scrape_attempts')), 3)
            self.assertEqual(len(store.rows('SELECT * FROM site_scraper_stats')), 6)
            self.assertNotIn('secret', str(store.rows('SELECT * FROM scrape_attempts')))
