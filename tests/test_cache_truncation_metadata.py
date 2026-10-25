"""Acquisition truncation survives source binding, reuse and old-schema migration."""
import tempfile
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.scrape.fetch import run_fetch_source
from multi_search_mcp.src.read import run_read_source
from multi_search_mcp.src.state.content_store import ContentStore, ContentStoreError
from multi_search_mcp.src.state.state_store import StateStore


class CacheTruncationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'state.sqlite'
        self.store = StateStore(self.path)

    def fetch(self, body, **request):
        return run_fetch_source(
            {'url': 'https://example.com/article', 'full_content': True, **request},
            state_store=self.store, keys={}, config={},
            url_resolver=lambda _: ['93.184.216.34'],
            scraper=lambda url, **kw: {'markdown': body, 'via': 'fixture'},
        )


    def test_metadata_is_per_acquisition_not_shared_content_hash(self):
        cache = ContentStore(self.store)
        cache.put('short', 'same', truncated=True, canonical_url='https://example.com/a', cache_scope='scope')
        cache.put('complete', 'same')
        self.assertTrue(cache.get('short')['truncated'])
        self.assertFalse(cache.get('complete')['truncated'])
        reused = cache.reuse_for_url('reuse', canonical_url='https://example.com/a', cache_scope='scope')
        self.assertTrue(reused['truncated'])
        cache.put('short', 'same', truncated=False)
        self.assertFalse(cache.get('short')['truncated'])

    def test_version_one_migrates_without_losing_body(self):
        cache = ContentStore(self.store)
        cache.put('legacy', 'old body')
        with self.store.connect() as conn:
            conn.execute('ALTER TABLE content_sources DROP COLUMN truncated')
            conn.execute('PRAGMA user_version=1')
        migrated = StateStore(self.path)
        row = ContentStore(migrated).get('legacy')
        self.assertEqual(row['content'], 'old body')
        self.assertFalse(row['truncated'])  # legacy acquisition has no truncation evidence
        self.assertEqual(migrated.rows('PRAGMA user_version')[0]['user_version'], 2)


    def test_preview_truncation_does_not_mark_complete_acquisition(self):
        first = self.fetch('complete body', full_content=False, max_chars=2)
        self.assertTrue(first['truncated'])
        self.assertFalse(ContentStore(self.store).get(first['source_id'])['truncated'])
        self.assertFalse(run_read_source({'source_id': first['source_id']}, state_store=self.store)['truncated'])
