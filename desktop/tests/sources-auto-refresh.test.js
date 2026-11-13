import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountSources } from '../ui/sources.js';

function fixture() {
  const window = new Window(), root = window.document.createElement('main');
  window.document.body.append(root);
  let listener, unsubscribed = 0, reads = 0, remaining = 80;
  let accountRows = [{ id: 'default', name: '默认账号', source: 'manual', keys: ['sha256:12345678'], balance_credentials: {} }];
  const usageRefresh = {
    subscribe(callback) { listener = callback; return () => { unsubscribed++; }; },
  };
  const api = {
    settingsView: async () => ({ route: 'default', timeout: 60, disabled_sources: [], twitter_cookies_path: null, route_ok: true }),
    credentialStatus: async source => ({ source, store: { state: 'absent', saved_at: null, error: '' }, effective_source: 'none', key_application_available: false }),
    accountsView: async () => ({ status: 'ready', accounts: { brave: accountRows } }),
    usageView: async (...args) => {
      reads++;
      assert.ok(args[1] !== true, 'the provider page only reads the cache when receiving an update');
      return { providers: [{ id: 'brave', label: 'Brave Search', balance_supported: true, alert: null,
        total: { remaining, limit: 100, percent: remaining, unit: 'usd', relative: false } }] };
    },
  };
  return {
    window, root, api, usageRefresh,
    emit: () => listener({}, 'brave'),
    setUpdated() { remaining = 35; accountRows = [...accountRows, {
      id: 'acc_saved', name: 'Example Name', source: 'oauth', login_identity: 'person@example.test', keys: [],
      balance_credentials: { brave_dashboard: 'sha256:87654321' },
    }]; },
    get reads() { return reads; },
    get unsubscribed() { return unsubscribed; },
  };
}

test('automatic quota updates refresh provider meters and account counts without replacing drafts', async () => {
  const f = fixture();
  const mounted = await mountSources(f.root, f.api, { usageRefresh: f.usageRefresh });
  const row = f.root.querySelector('[data-source-row="brave"]');
  const meter = () => row.querySelector('[data-provider-meter]').textContent;
  assert.match(meter(), /80/);
  const draft = f.window.document.createElement('input');
  draft.value = 'unfinished key entry';
  row.querySelector('[data-source-detail]').append(draft);
  f.setUpdated();
  await f.emit();
  assert.match(meter(), /35/);
  assert.match(row.textContent, /2 个账号 · 1 个 Key/);
  assert.equal(row.querySelector('[data-source-detail] input'), draft);
  assert.equal(draft.value, 'unfinished key entry');
  assert.equal(f.reads, 2);
  mounted.dispose();
  assert.equal(f.unsubscribed, 1);
  await f.emit();
  assert.equal(f.reads, 2, 'late automatic notifications do not query an unmounted page');
  f.window.close();
});

test('aborting the provider page releases its global refresh subscription once', async () => {
  const f = fixture(), controller = new AbortController();
  const mounted = await mountSources(f.root, f.api, { signal: controller.signal, usageRefresh: f.usageRefresh });
  controller.abort();
  mounted.dispose();
  assert.equal(f.unsubscribed, 1);
  await f.emit();
  assert.equal(f.reads, 1);
  f.window.close();
});
