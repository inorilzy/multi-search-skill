"""Synthetic regressions for deadline and authorization boundaries."""
import io
import tempfile
import time
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.support import http, url_security
from multi_search_mcp.src.scrape.fetch import _scope_keys
from multi_search_mcp.src.state.key_state import SQLiteKeyManager
from multi_search_mcp.src.state.state_store import StateStore


class RemainingBoundariesTests(unittest.TestCase):
    def test_literal_fake_ip_rejected(self):
        with self.assertRaises(url_security.UrlSecurityError):
            http._ensure_connect_address('198.18.0.1')

    def test_redirect_does_not_resolve_the_target(self):
        req = urllib.request.Request('https://example.com/a')
        req._multi_search_deadline = time.monotonic() + 1
        with mock.patch('socket.getaddrinfo', side_effect=AssertionError('redirect DNS')):
            result = http._SafeHTTPRedirectHandler().redirect_request(
                req, io.BytesIO(), 302, 'Found', {}, 'https://example.com/b',
            )
        self.assertEqual(result.full_url, 'https://example.com/b')

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
