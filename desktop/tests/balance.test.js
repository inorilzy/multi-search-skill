import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountBalance, providerForSource, formatAmount, formatTimestamp } from '../ui/balance.js';
import { mountCredentialBody } from '../ui/credentials.js';
import { mountSources } from '../ui/sources.js';

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root };
}

const report = (overrides = {}) => ({
  provider: 'tavily',
  status: 'ok',
  scope: 'key',
  unit: 'credits',
  remaining: 1234,
  limit: 5000,
  used: 3766,
  resets_at: '2026-12-01T00:00:00Z',
  period: 'month',
  key_fingerprint: null,
  error_kind: null,
  message: '',
  fetched_at: '2026-11-01T09:30:00Z',
  ...overrides,
});

const view = (reports, overrides = {}) => ({
  schema_version: 1,
  providers: [{
    id: 'tavily',
    label: 'Tavily',
    auth_methods: [],
    balance_supported: true,
    balance_note: '',
    reports,
    ...overrides,
  }],
});

const mount = async (root, api, options = {}) => mountBalance(root, api, { provider: 'tavily', label: 'Tavily', ...options });

test('ok reports show remaining, limit, unit and both timestamps', async () => {
  const { window, root } = setup();
  const mounted = await mount(root, { balanceView: async () => view([report()]) });
  const text = root.textContent;
  assert.match(text, /余额/);
  assert.match(text, /剩余/);
  assert.match(text, /1,234/);
  assert.match(text, /5,000/);
  assert.match(text, /credits/);
  assert.match(text, /2026-12-01 00:00 UTC/);
  assert.match(text, /2026-11-01 09:30 UTC/);
  assert.equal(root.querySelector('[data-balance-rows]').getAttribute('aria-live'), 'polite');
  mounted.dispose();
  window.close();
});

test('unsupported, needs_credential and error reports show their reason text', async () => {
  for (const [status, message] of [
    ['unsupported', '匿名搜索没有配额查询接口。'],
    ['needs_credential', '未配置凭据：exa_admin。'],
    ['error', '查询超时（总时限 15 秒）'],
  ]) {
    const { window, root } = setup();
    const mounted = await mount(root, {
      balanceView: async () => view([report({ status, message, remaining: null, limit: null, resets_at: null })]),
    });
    assert.match(root.textContent, new RegExp(message.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    assert.match(root.querySelector('.balance-status').textContent, /不支持|需要凭据|查询失败/);
    mounted.dispose();
    window.close();
  }
});

test('a null amount renders as a dash, never as zero', async () => {
  const { window, root } = setup();
  const mounted = await mount(root, {
    balanceView: async () => view([report({ remaining: null, limit: null })]),
  });
  const values = [...root.querySelectorAll('.balance-values dd')].map(node => node.textContent);
  assert.equal(values[0], '—', 'remaining null is not 0');
  assert.equal(values[1], '—', 'limit null is not 0');
  assert.equal(formatAmount(null), '—');
  assert.equal(formatAmount(0), '0');
  mounted.dispose();
  window.close();
});

test('refresh calls balanceView with refresh=true and the plugin id', async () => {
  const { window, root } = setup();
  const calls = [];
  const mounted = await mount(root, {
    balanceView: async (provider, refresh) => {
      calls.push([provider, refresh]);
      return view([report()]);
    },
  });
  assert.deepEqual(calls, [['tavily', false]]);
  root.querySelector('[data-action="refresh-balance"]').click();
  await flush();
  assert.deepEqual(calls, [['tavily', false], ['tavily', true]]);
  mounted.dispose();
  window.close();
});

test('a rejected balance read shows the normalized Chinese error', async () => {
  const { window, root } = setup();
  const mounted = await mount(root, {
    balanceView: async () => { throw JSON.stringify({ code: 'balance_view_failed', message: 'worker failed' }); },
  });
  const error = root.querySelector('[data-info="balance-error"]');
  assert.equal(error.textContent, '余额读取失败，请重试。');
  assert.equal(error.getAttribute('role'), 'alert');
  mounted.dispose();
  window.close();
});

test('source names resolve to plugin ids for the balance CLI', () => {
  assert.equal(providerForSource('github_repos'), 'github');
  assert.equal(providerForSource('github_code'), 'github');
  assert.equal(providerForSource('stackoverflow'), 'stackexchange');
  assert.equal(providerForSource('jina'), 'jina');
  assert.equal(formatTimestamp(null), '—');
  assert.equal(formatTimestamp('not-a-date'), 'not-a-date');
});

test('Exa detail renders a balance-only admin editor and saves through exa_admin', async () => {  const { window, root } = setup();
  const calls = [];
  const status = saved => ({
    source: '',
    store: { state: saved ? 'present' : 'absent', saved_at: saved ? 1 : null, error: '' },
    effective_source: saved ? 'file' : 'none',
    key_application_available: false,
    key_application_open_supported: true,
  });
  const api = {
    credentialStatus: async source => status(source === 'exa_admin' && calls.length > 0),
    credentialRead: async () => ({ value: '', snapshot: '' }),
    credentialAppend: async (source, keys) => { calls.push([source, keys]); return status(true); },
    balanceView: async () => view([report({ status: 'needs_credential', message: '未配置凭据：exa_admin。', remaining: null, limit: null, resets_at: null })], { id: 'exa', label: 'Exa' }),
  };
  const mounted = await mountCredentialBody(root, api, { source: 'exa' });
  const admin = root.querySelector('.exa-admin-key');
  assert.ok(admin, 'Exa detail exposes the admin key section');
  assert.match(admin.textContent, /管理 Key（仅用于查余额）/);
  assert.equal(root.querySelector('.balance-block') !== null, true, 'Exa detail also shows the balance block');

  admin.querySelector('[data-action="add"]').click();
  const input = admin.querySelector('[data-draft-list] input');
  input.value = 'synthetic-exa-admin';
  admin.querySelector('form').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  await flush();
  assert.deepEqual(calls, [['exa_admin', ['synthetic-exa-admin']]]);
  assert.equal(admin.querySelector('[data-action="test"]').hidden, true, 'balance-only editor has no search test');
  mounted.dispose();
  window.close();
});

test('search source details show a balance block for keyed and keyless providers', async () => {
  const { window, root } = setup();
  const overview = {
    source: '',
    store: { state: 'absent', saved_at: null, error: '' },
    effective_source: 'none',
    key_application_available: false,
    key_application_open_supported: true,
  };
  const api = {
    settingsView: async () => ({ route: 'default', timeout: 60, disabled_sources: [], twitter_cookies_path: null }),
    credentialStatus: async () => overview,
    credentialRead: async () => ({ value: '', snapshot: '' }),
    credentialTest: async () => ({ result: 'success', message: '' }),
    balanceView: async provider => view([
      report({ provider, status: 'unsupported', message: '该服务商不支持余额查询。', remaining: null, limit: null, resets_at: null }),
    ], { id: provider, label: provider }),
  };
  const mount = async name => {
    const button = root.querySelector(`[data-pick="${name}"]`);
    if (button.getAttribute('aria-expanded') !== 'true') button.click();
    await flush();
    await flush();
  };
  const mounted = await mountSources(root, api);
  for (const name of ['tavily', 'hackernews']) {
    await mount(name);
    const detail = root.querySelector('[data-source-row][data-expanded="true"] [data-source-detail]');
    assert.match(detail.textContent, /该服务商不支持余额查询/);
    assert.ok(detail.querySelector('[data-action="refresh-balance"]'), `${name} exposes the refresh control`);
  }
  mounted.dispose();
  window.close();
});
