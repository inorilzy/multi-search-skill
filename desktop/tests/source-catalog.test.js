// Contract tests for the shared source catalog (issue 09).
// The catalog is generated from Python core metadata; this test proves both
// desktop entry points read the same artifact and, when Python is available,
// that the artifact still equals the live CLI output. Rust has the mirror test
// in src-tauri/tests/source_catalog.rs.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { SOURCE_CATALOG } from '../ui/source-catalog.js';
import {
  CATALOG, SEARCH_SOURCES, ROUTES, canonicalSource, isAllowedSource, routeSources, sourceLabel,
} from '../ui/catalog.js';
import { SOURCES } from '../ui/credentials.js';
import { ROUTES as SETTINGS_ROUTES, SETTINGS_SOURCES } from '../ui/settings.js';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const ARTIFACT = JSON.parse(readFileSync(new URL('../source-catalog.json', import.meta.url), 'utf8'));

test('runtime module and checked-in JSON are the same catalog', () => {
  assert.deepEqual(SOURCE_CATALOG, ARTIFACT);
  assert.deepEqual(CATALOG, ARTIFACT);
  assert.equal(SOURCE_CATALOG.schema_version, 1);
  assert.equal(SOURCE_CATALOG.key_resolution.env_alias_priority, 'last_non_empty_wins');
  assert.deepEqual(SOURCE_CATALOG.key_resolution.order, ['env', 'credential_store', 'keys_file']);
});

test('catalog has one entry per search source and route with stable aliases', () => {
  const names = SEARCH_SOURCES.map(source => source.name);
  assert.deepEqual(names, [
    'baidu', 'brave', 'parallel', 'tavily', 'exa', 'firecrawl', 'serpapi',
    'github_repos', 'hackernews', 'stackoverflow', 'sov2ex', 'twitter',
  ]);
  assert.equal(new Set(names).size, names.length);
  assert.ok(names.every(name => !name.includes('-')), 'CLI names use underscores');
  assert.equal(ROUTES.length, 5);
  assert.deepEqual(ROUTES.map(route => route.name), ['default', 'fast', 'social', 'dev', 'all']);
  assert.deepEqual(routeSources('web'), routeSources('default'));
  assert.ok(routeSources('default').includes('brave'));
  assert.equal(canonicalSource('github-repos'), 'github_repos');
  assert.equal(canonicalSource('v2ex'), 'sov2ex');
  assert.equal(canonicalSource('qianfan'), 'baidu');
  assert.equal(isAllowedSource('github'), true);
  assert.equal(isAllowedSource('jina'), false, 'Jina is scrape-only, not a search source');
});

test('credentials and settings derive from the same catalog', () => {
  assert.deepEqual(SOURCES.map(entry => entry.source), SEARCH_SOURCES.map(source => source.name));
  assert.deepEqual(SOURCES.map(entry => entry.label), SEARCH_SOURCES.map(source => source.label));
  assert.deepEqual(
    SOURCES.filter(entry => entry.keyed).map(entry => entry.source),
    SEARCH_SOURCES.filter(source => source.keyed).map(source => source.name),
  );
  assert.deepEqual(
    SOURCES.filter(entry => entry.cookie).map(entry => entry.source),
    ['twitter'],
  );
  assert.equal(sourceLabel('github'), 'GitHub 仓库');
  assert.deepEqual(SETTINGS_SOURCES.map(entry => entry.source), SOURCES.map(entry => entry.source));
  assert.deepEqual(SETTINGS_ROUTES.map(route => route.value), ROUTES.map(route => route.name));
  assert.deepEqual(SOURCE_CATALOG.credential_store_providers, [
    'baidu', 'brave', 'parallel', 'tavily', 'exa', 'firecrawl', 'serpapi', 'github', 'jina',
  ]);
  for (const source of SEARCH_SOURCES) {
    assert.ok(source.label && source.description && source.mark, `${source.name} keeps display metadata`);
    if (source.keyed) assert.ok(source.env.length, `${source.name} documents its env aliases`);
  }
});

test('checked-in catalog still matches the live Python CLI', t => {
  const python = process.env.MULTI_SEARCH_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const result = spawnSync(
    python,
    ['-m', 'multi_search_mcp.cli', 'sources', '--format', 'json'],
    { cwd: ROOT, encoding: 'utf8', timeout: 30_000 },
  );
  if (result.error || result.status !== 0) {
    t.skip(`Python CLI unavailable (${python}): ${result.error || result.stderr}`);
    return;
  }
  assert.deepEqual(JSON.parse(result.stdout), ARTIFACT);
});
