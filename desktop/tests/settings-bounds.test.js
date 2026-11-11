// Settings editor bounds must come from the Rust SettingsView (T07): a route
// timeout of 61–90 seconds is a valid CLI value and the desktop must accept it.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountSettings } from '../ui/settings.js';

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

const ROUTES = {
  default: { label: '默认', description: null, sources: ['tavily'], timeout: null },
  all: { label: '全部', description: null, sources: ['tavily'], timeout: null },
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
    effective_timeouts: { default: 60, all: 60 },
    routes: ROUTES,
    builtin_routes: ROUTES,
    disabled_sources: [],
    unknown_disabled_sources: [],
    twitter_cookies_path: null,
    active_sources: ['tavily'],
    scrape_backends: ['jina'],
    scrape_backends_invalid: false,
    builtin_scrape_backends: ['jina'],
    scrape_backend_options: [{ name: 'jina', label: 'Jina Reader' }],
    scrape_backend_timeout: 10,
    scrape_backend_timeout_invalid: false,
    scrape_backend_timeout_min: 1,
    scrape_backend_timeout_max: 60,
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

let current = null;
function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  current = window;
  return { window, root };
}
test.afterEach(() => { try { current?.close(); } catch { /* already closed */ } current = null; });

async function openNew(root) {
  root.querySelector('[data-action="new-route"]').click();
  await flush();
  return root.querySelector('.route-editor');
}

function fillRoute(editor, id, timeout) {
  editor.querySelector('[data-edit="id"]').value = id;
  editor.querySelector('[data-edit="label"]').value = 'Research';
  editor.querySelector('[data-route-source][value="tavily"]').checked = true;
  editor.querySelector('[data-edit="timeout"]').value = timeout;
}

test('route editor accepts a 90-second timeout and advertises the backend bounds', async () => {
  const { window, root } = setup();
  let sent = null;
  await mountSettings(root, {
    settingsView: async () => view(),
    settingsSave: async input => { sent = input; return view({ routes: input.routes, route: input.route }); },
  });
  const editor = await openNew(root);
  const timeout = editor.querySelector('[data-edit="timeout"]');
  assert.equal(timeout.min, '1');
  assert.equal(timeout.max, '90');
  fillRoute(editor, 'research', '90');
  editor.querySelector('[data-action="apply-route"]').click();
  assert.equal(editor.querySelector('[data-edit-error]').textContent, '');
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(sent.routes.research.timeout, 90);
  window.close();
});

test('route editor rejects 91 seconds against the backend maximum', async () => {
  const { window, root } = setup();
  await mountSettings(root, { settingsView: async () => view() });
  const editor = await openNew(root);
  fillRoute(editor, 'research', '91');
  editor.querySelector('[data-action="apply-route"]').click();
  assert.match(editor.querySelector('[data-edit-error]').textContent, /1–90 秒/);
  window.close();
});

test('global timeout accepts the backend maximum of 90 seconds', async () => {
  const { window, root } = setup();
  let sent = null;
  await mountSettings(root, {
    settingsView: async () => view(),
    settingsSave: async input => { sent = input; return view({ timeout: input.timeout ?? 60 }); },
  });
  const field = root.querySelector('[data-field="timeout"]');
  assert.equal(field.max, '90');
  field.value = '90';
  field.dispatchEvent(new window.Event('input'));
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(sent.timeout, 90);
  window.close();
});
