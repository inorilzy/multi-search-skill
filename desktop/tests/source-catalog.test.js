// Contract tests for the shared source catalog (issue 09).
// The catalog is generated from Python core metadata; this test proves both
// desktop entry points read the same artifact and, when Python is available,
// that the artifact still equals the built-in catalog. Rust has the mirror test
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
  assert.deepEqual(SOURCE_CATALOG.key_resolution.order, ['env', 'keys_file']);
});

test('catalog has one entry per search source and route with stable aliases', () => {
  const names = SEARCH_SOURCES.map(source => source.name);
  assert.deepEqual(names, [
    'baidu', 'brave', 'parallel', 'tavily', 'exa', 'firecrawl', 'serpapi',
    'github_repos', 'github_code', 'hackernews', 'stackoverflow', 'sov2ex', 'twitter',
  ]);
  assert.equal(new Set(names).size, names.length);
  assert.ok(names.every(name => !name.includes('-')), 'CLI names use underscores');
  assert.equal(ROUTES.length, 5);
  for (const route of ROUTES) {
    assert.ok(route.description?.trim(), `${route.name} describes when to use it`);
  }
  assert.deepEqual(ROUTES.map(route => route.name), ['default', 'fast', 'social', 'dev', 'all']);
  assert.deepEqual(routeSources('web'), routeSources('default'));
  assert.ok(routeSources('default').includes('brave'));
  assert.equal(canonicalSource('github-repos'), 'github_repos');
  assert.equal(canonicalSource('github-code'), 'github_code');
  for (const route of ROUTES) {
    assert.ok(!routeSources(route.name).includes('github_code'), `${route.name} does not include github_code`);
  }
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
  assert.equal(sourceLabel('github_code'), 'GitHub 代码');
  assert.equal(SEARCH_SOURCES.find(source => source.name === 'github_code').key_provider, 'github');
  assert.deepEqual(SETTINGS_SOURCES.map(entry => entry.source), SOURCES.map(entry => entry.source));
  assert.deepEqual(SETTINGS_ROUTES.map(route => route.value), ROUTES.map(route => route.name));
  assert.deepEqual(SOURCE_CATALOG.credential_store_providers, [
    'baidu', 'brave', 'parallel', 'tavily', 'exa', 'firecrawl', 'serpapi', 'github', 'jina',
    'stackexchange',
  ]);
  for (const source of SEARCH_SOURCES) {
    assert.ok(source.label && source.description && source.mark, `${source.name} keeps display metadata`);
    if (source.keyed) assert.ok(source.env.length, `${source.name} documents its env aliases`);
  }
});

test('checked-in catalog still matches the built-in Python catalog', t => {
  const python = process.env.MULTI_SEARCH_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const result = spawnSync(
    python,
    ['-c', 'import json; from multi_search_mcp.src.search.catalog import build_source_catalog; print(json.dumps(build_source_catalog()))'],
    { cwd: ROOT, encoding: 'utf8', timeout: 30_000 },
  );
  if (result.error || result.status !== 0) {
    t.skip(`Python catalog unavailable (${python}): ${result.error || result.stderr}`);
    return;
  }
  assert.deepEqual(JSON.parse(result.stdout), ARTIFACT);
});
