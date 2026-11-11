// Ticket 08: the settings page must say when the CLI reads a DIFFERENT config
// because MULTI_SEARCH_CONFIG is set. The value travels in the existing
// SettingsView.read_source string; no IPC field is added.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountSettings } from '../ui/settings.js';

const clone = value => JSON.parse(JSON.stringify(value));

const ROUTE = {
  label: '默认（网页综合）',
  description: null,
  sources: ['brave'],
  timeout: null,
};

function view(overrides = {}) {
  return {
    config_path: 'C:/Users/test/.multi-search/config.sqlite',
    path_source: 'user',
    file_present: true,
    read_source: 'sqlite',
    route: 'default',
    timeout: 60,
    timeout_configured: true,
    timeout_min: 1,
    timeout_max: 90,
    timeout_out_of_range: false,
    effective_timeout: 60,
    effective_timeouts: { default: 60 },
    routes: { default: clone(ROUTE) },
    builtin_routes: { default: clone(ROUTE) },
    disabled_sources: [],
    unknown_disabled_sources: [],
    twitter_cookies_path: null,
    scrape_backends: ['jina', 'exa', 'tavily', 'firecrawl'],
    scrape_backends_invalid: false,
    builtin_scrape_backends: ['jina', 'exa', 'tavily', 'firecrawl'],
    scrape_backend_options: [
      { name: 'jina', label: 'Jina Reader' },
      { name: 'exa', label: 'Exa' },
      { name: 'tavily', label: 'Tavily' },
      { name: 'firecrawl', label: 'Firecrawl' },
    ],
    scrape_backend_timeout: 10,
    scrape_backend_timeout_invalid: false,
    scrape_backend_timeout_min: 1,
    scrape_backend_timeout_max: 60,
    active_sources: ['brave'],
    ranking: { mode: 'rrf', base_url: '', model: '', candidate_limit: 50, batch_size: 20, rerank_timeout: 10 },
    ranking_invalid: false,
    ranking_candidate_limit_min: 10,
    ranking_candidate_limit_max: 200,
    ranking_batch_size_min: 1,
    ranking_batch_size_max: 50,
    ranking_rerank_timeout_min: 1,
    ranking_rerank_timeout_max: 60,
    rerank_key: { source: 'none', keys_file: null, env_var: 'SYSTEMONE_API_KEY' },
    debug_log: false,
    status: 'ok',
    message: '',
    ...overrides,
  };
}

function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root };
}

test('settings page names MULTI_SEARCH_CONFIG when the CLI reads its own file', async () => {
  const { window, root } = setup();
  await mountSettings(root, { settingsView: async () => view({ read_source: 'cli_env' }) });

  const visible = root.querySelector('[data-info="config-source"]').textContent;
  assert.match(visible, /CLI/);
  assert.match(visible, /MULTI_SEARCH_CONFIG/);
  assert.match(visible, /指定的配置文件/);
  const notice = root.querySelector('[data-info="env"]').textContent;
  assert.match(notice, /CLI 正在使用/);
  assert.doesNotMatch(notice, /SQLite 是唯一生效配置来源/);
  window.close();
});

test('settings page keeps the SQLite-only note without MULTI_SEARCH_CONFIG', async () => {
  const { window, root } = setup();
  await mountSettings(root, { settingsView: async () => view() });

  assert.equal(root.querySelector('[data-info="config-source"]').textContent, '');
  const notice = root.querySelector('[data-info="env"]').textContent;
  assert.match(notice, /SQLite 是唯一生效配置来源/);
  assert.doesNotMatch(notice, /MULTI_SEARCH_CONFIG/);
  window.close();
});
