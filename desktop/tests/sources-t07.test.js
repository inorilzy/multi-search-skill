import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountSources } from '../ui/sources.js';

const flush = async () => { await new Promise(resolve => setTimeout(resolve, 0)); await new Promise(resolve => setTimeout(resolve, 0)); };
const overview = (extra = {}) => ({ effective_source: 'none', file_key_count: 0, store: { state: 'absent', error: '' }, key_application_available: false, ...extra });
function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root };
}
const baseApi = () => ({
  settingsView: async () => ({ route: 'default', timeout: 60, disabled_sources: ['brave'], twitter_cookies_path: null }),
  credentialStatus: async () => overview(),
  credentialRead: async () => ({ value: '', snapshot: 't07' }),
});
const rowFor = (root, source) => root.querySelector(`[data-source-row="${source}"]`);
const open = async (root, source) => { rowFor(root, source).querySelector('[data-pick]').click(); await flush(); };

test('T07: details keep connection tests while summaries read cached usage once', async () => {
  const { window, root } = setup();
  const tested = [];
  let balanceCalls = 0;
  const usageCalls = [];
  const mounted = await mountSources(root, {
    ...baseApi(),
    usageView: async (...args) => { usageCalls.push(args); return { providers: [] }; },
    balanceView: async () => { balanceCalls += 1; throw Error('balance is not part of provider setup'); },
    credentialTest: async source => { tested.push(source); return { result: 'success', message: 'synthetic connection' }; },
  });
  for (const row of root.querySelectorAll('[data-source-row]')) {
    await open(root, row.dataset.sourceRow);
    assert.equal(row.querySelector('.balance-block'), null, row.dataset.sourceRow);
    assert.equal(row.querySelector('[data-action="refresh-balance"]'), null);
    const testButton = row.querySelector('[data-action="test"]');
    if (row.dataset.sourceRow !== 'jina') {
      testButton.click(); await flush();
      assert.match(row.querySelector('[data-status="test"]').textContent, /测试成功/);
    }
  }
  assert.equal(tested.length, 12);
  assert.equal(balanceCalls, 0);
  assert.deepEqual(usageCalls, [[]], 'mount reads cached usage without a refresh argument');
  assert.equal(root.querySelectorAll('[data-key-count]').length, 13);
  assert.equal(rowFor(root, 'brave').querySelector('[data-toggle-label]').textContent, '未启用');
  assert.equal(rowFor(root, 'tavily').querySelector('[data-toggle-label]').textContent, '已启用');
  mounted.dispose(); window.close();
});

test('T07: visible row summaries count file and environment keys without reading their values', async () => {
  const { window, root } = setup();
  const views = {
    tavily: overview({ effective_source: 'env', env_var: 'TAVILY_API_KEY', file_key_count: 3, store: { state: 'present' } }),
    brave: overview({ effective_source: 'env', env_var: 'BRAVE_API_KEY' }),
    exa: overview({ effective_source: 'file', file_key_count: 2, store: { state: 'present' } }),
    jina: overview({ file_key_count: undefined, store: { state: 'unavailable' } }),
  };
  const mounted = await mountSources(root, {
    ...baseApi(),
    credentialStatus: async source => views[source] || overview(),
    credentialRead: async () => assert.fail('the overview must not read key values'),
  });
  for (const [source, count] of [['tavily', 4], ['brave', 1], ['exa', 2], ['hackernews', 0], ['twitter', 0]]) {
    const summary = rowFor(root, source).querySelector('[data-key-count]');
    assert.equal(summary.textContent, source === 'hackernews' || source === 'twitter' ? '0 个账号 · 0 个 Key' : `账号数未知 · ${count} 个 Key`);
    assert.equal(summary.closest('[aria-hidden="true"], .visually-hidden, .source-key'), null, 'count remains in the visible source column at narrow widths');
  }
  assert.equal(rowFor(root, 'jina').querySelector('[data-key-count]').textContent, '账号数未知 · Key 数未知');
  assert.equal(root.querySelectorAll('[data-login-status]').length, 2, 'only OAuth providers have login status');
  mounted.dispose(); window.close();
});

test('T07: saving and removing keys updates the count in the same row', async () => {
  const { window, root } = setup();
  let keys = [];
  const status = () => overview({ effective_source: keys.length ? 'file' : 'none', file_key_count: keys.length, store: { state: keys.length ? 'present' : 'absent' } });
  const mounted = await mountSources(root, {
    ...baseApi(),
    credentialStatus: async source => source === 'tavily' ? status() : overview(),
    credentialRead: async () => ({ value: keys.map(() => 'masked-key').join('\n'), snapshot: 't07' }),
    credentialAppend: async (source, values) => { assert.equal(source, 'tavily'); keys.push(...values); return status(); },
    credentialRemove: async (source, index, snapshot) => { assert.equal(source, 'tavily'); assert.equal(snapshot, 't07'); keys.splice(index, 1); return status(); },
  });
  await open(root, 'tavily');
  const row = rowFor(root, 'tavily');
  row.querySelector('[data-action="add"]').click();
  row.querySelector('[data-draft-input]').value = 'synthetic-t07';
  row.querySelector('form').dispatchEvent(new window.Event('submit', { cancelable: true })); await flush();
  assert.equal(row.querySelector('[data-key-count]').textContent, '账号数未知 · 1 个 Key');
  row.querySelector('[data-action="remove"]').click();
  row.querySelector('[data-action="confirm-remove"]').click(); await flush();
  assert.equal(row.querySelector('[data-key-count]').textContent, '账号数未知 · 0 个 Key');
  mounted.dispose(); window.close();
});

test('T07: OAuth status follows the shared credential and never treats a Parallel search key as an account login', async () => {
  for (const state of ['none', 'file', 'unavailable']) {
    const { window, root } = setup();
    const mounted = await mountSources(root, {
      ...baseApi(),
      credentialStatus: async source => {
        assert.notEqual(source, 'parallel_account', 'the backend does not expose account overviews');
        if (source === 'firecrawl') {
          if (state === 'unavailable') throw Error('unavailable overview');
          return overview({ effective_source: state, store: { state: state === 'file' ? 'present' : 'absent' } });
        }
        return overview({ effective_source: 'file', file_key_count: 1, store: { state: 'present' } });
      },
    });
    assert.equal(rowFor(root, 'parallel').querySelector('[data-login-status]').textContent, '浏览器登录：状态未知');
    assert.equal(rowFor(root, 'firecrawl').querySelector('[data-login-status]').textContent,
      state === 'file' ? '浏览器登录：凭据已配置' : state === 'none' ? '浏览器登录：未登录' : '浏览器登录：状态未知');
    mounted.dispose(); window.close();
  }
});

test('T07: Exa admin keys remain editable when the API has no balance command', async () => {
  const { window, root } = setup();
  const appended = [];
  const removed = [];
  let keys = [];
  const mounted = await mountSources(root, {
    ...baseApi(),
    credentialRead: async source => ({ value: source === 'exa_admin' ? keys.map(() => 'masked-admin').join('\n') : '', snapshot: 't07' }),
    credentialAppend: async (source, values) => { appended.push([source, values]); keys.push(...values); return overview(); },
    credentialRemove: async (source, index, snapshot) => { removed.push([source, index, snapshot]); keys.splice(index, 1); return overview(); },
  });
  await open(root, 'exa');
  const admin = rowFor(root, 'exa').querySelector('.exa-admin-key');
  assert.ok(admin);
  assert.equal(admin.querySelector('[data-action="test"]').hidden, true);
  admin.querySelector('[data-action="add"]').click();
  admin.querySelector('[data-draft-input]').value = 'synthetic-t07-admin';
  admin.querySelector('form').dispatchEvent(new window.Event('submit', { cancelable: true })); await flush();
  assert.deepEqual(appended, [['exa_admin', ['synthetic-t07-admin']]]);
  admin.querySelector('[data-action="remove"]').click();
  admin.querySelector('[data-action="confirm-remove"]').click(); await flush();
  assert.deepEqual(removed, [['exa_admin', 0, 't07']]);
  assert.equal(admin.querySelector('[data-saved-empty]').hidden, false);
  mounted.dispose(); window.close();
});

test('T07: browser login completion updates the row and refreshes credentials without balance commands', async () => {
  const { window, root } = setup();
  const started = [];
  let reads = 0;
  let balanceCalls = 0;
  const mounted = await mountSources(root, {
    ...baseApi(),
    credentialStatus: async source => {
      if (source === 'parallel_account') throw Error('unsupported account overview');
      return overview();
    },
    credentialRead: async () => { reads += 1; return { value: '', snapshot: 't07' }; },
    oauthLoginStart: async provider => { started.push(provider); return 7; },
    oauthLoginPoll: async () => ({ id: 7, provider: 'parallel', phase: 'complete' }),
    oauthLoginCancel: async () => assert.fail('completed login must not be cancelled'),
    balanceView: async () => { balanceCalls += 1; },
  });
  await open(root, 'parallel');
  const row = rowFor(root, 'parallel');
  const button = row.querySelector('[data-action="oauth-start"]');
  button.focus();
  assert.equal(window.document.activeElement, button);
  button.click(); await flush();
  assert.deepEqual(started, ['parallel']);
  assert.equal(reads, 2, 'initial mount and successful login each read credentials once');
  assert.equal(row.querySelector('[data-login-status]').textContent, '浏览器登录：已登录');
  assert.equal(balanceCalls, 0);
  mounted.dispose(); window.close();
});
