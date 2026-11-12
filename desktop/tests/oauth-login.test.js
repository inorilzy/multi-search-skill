// OAuth login panel: button visibility, phase rendering (device code + cancel), completion
// refresh and lifecycle cleanup. The CLI itself is stubbed; no provider or browser is involved.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountCredentialBody } from '../ui/credentials.js';
import { oauthMethodForSource } from '../ui/oauth-login.js';

const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const until = async (predicate, message = 'condition not reached') => {
  const started = Date.now();
  while (!predicate()) {
    if (Date.now() - started > 3000) assert.fail(message);
    await delay(2);
  }
};

const overview = (extra = {}) => ({
  source: 'firecrawl',
  store: { state: 'absent', saved_at: null, error: '' },
  effective_source: 'none',
  key_application_available: false,
  key_application_open_supported: true,
  ...extra,
});

const login = (phase, extra = {}) => ({ id: 1, provider: 'firecrawl', phase, ...extra });

const balanceView = provider => ({
  schema_version: 1,
  providers: [{
    id: provider,
    label: provider,
    auth_methods: [],
    balance_supported: true,
    balance_note: '',
    reports: [],
  }],
});

async function mountDetail(source, overrides = {}, options = {}) {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  const api = {
    credentialStatus: async () => overview(),
    credentialRead: async () => ({ value: '', snapshot: 'snapshot' }),
    ...overrides,
  };
  const mounted = await mountCredentialBody(root, api, { source, ...options });
  return { window, root, api, mounted };
}

test('oauth providers expose the browser login button and Parallel says it is balance-only', async () => {
  const oauthApi = {
    oauthLoginStart: async () => 1,
    oauthLoginPoll: async () => login('starting'),
    oauthLoginCancel: async () => login('cancelled'),
  };
  const firecrawl = await mountDetail('firecrawl', oauthApi);
  const button = firecrawl.root.querySelector('[data-action="oauth-start"]');
  assert.equal(button?.textContent.trim(), '浏览器登录');
  assert.match(firecrawl.root.querySelector('.oauth-login-sub').textContent, /自动保存凭据/);
  firecrawl.mounted.dispose();
  firecrawl.window.close();

  const parallel = await mountDetail('parallel', oauthApi);
  assert.equal(parallel.root.querySelector('[data-action="oauth-start"]')?.textContent.trim(), '浏览器登录');
  assert.match(parallel.root.querySelector('.oauth-login-sub').textContent, /仅用于查看余额/);
  parallel.mounted.dispose();
  parallel.window.close();

  const tavily = await mountDetail('tavily', oauthApi);
  assert.equal(tavily.root.querySelector('[data-action="oauth-start"]'), null);
  assert.equal(tavily.root.querySelector('[data-oauth-login]'), null);
  tavily.mounted.dispose();
  tavily.window.close();

  assert.equal(oauthMethodForSource('firecrawl')?.purpose, 'search_key');
  assert.equal(oauthMethodForSource('parallel')?.purpose, 'balance_only');
  assert.equal(oauthMethodForSource('tavily'), null);
});

test('starting, waiting and complete phases render the device code and refresh credentials and balance', async () => {
  const polls = [
    login('starting', { id: 7 }),
    login('waiting', { id: 7, user_code: 'ABCD-EFGH', url: 'https://platform.parallel.ai/device' }),
    login('complete', { id: 7 }),
  ];
  const pollIds = [];
  const balanceCalls = [];
  let statusCalls = 0;
  let startedProvider = '';
  const ctx = await mountDetail('parallel', {
    credentialStatus: async () => { statusCalls += 1; return overview(); },
    oauthLoginStart: async provider => { startedProvider = provider; return 7; },
    oauthLoginPoll: async id => { pollIds.push(id); return polls.shift() || login('complete', { id: 7 }); },
    oauthLoginCancel: async () => { throw new Error('must not cancel a completed login'); },
    balanceView: async (provider, refresh) => { balanceCalls.push([provider, refresh]); return balanceView(provider); },
  }, { oauthPollInterval: 1 });
  const copied = [];
  Object.defineProperty(ctx.window.navigator, 'clipboard', {
    value: { writeText: async value => copied.push(value) },
    configurable: true,
  });
  const button = ctx.root.querySelector('[data-action="oauth-start"]');
  button.click();
  assert.equal(ctx.root.querySelector('[data-oauth-status]').textContent, '正在启动浏览器登录…');
  await until(() => /等待浏览器授权/.test(ctx.root.querySelector('[data-oauth-status]').textContent), 'waiting phase not rendered');
  assert.equal(startedProvider, 'parallel');
  assert.equal(ctx.root.querySelector('[data-oauth-user-code]').textContent, 'ABCD-EFGH');
  assert.equal(ctx.root.querySelector('[data-oauth-code]').hidden, false);
  assert.equal(ctx.root.querySelector('[data-action="oauth-cancel"]').hidden, false);
  assert.equal(ctx.root.querySelector('[data-action="oauth-start"]').hidden, true);
  ctx.root.querySelector('[data-action="copy-code"]').click();
  await flush();
  assert.deepEqual(copied, ['ABCD-EFGH']);
  assert.match(ctx.root.querySelector('[data-oauth-copy-status]').textContent, /已复制/);

  await until(() => /登录完成/.test(ctx.root.querySelector('[data-oauth-status]').textContent), 'complete phase not rendered');
  await until(() => balanceCalls.some(([, refresh]) => refresh === true), 'balance was not refreshed after login');
  assert.deepEqual(pollIds, [7, 7, 7]);
  assert.ok(statusCalls >= 2, 'credential list was refreshed after login');
  assert.equal(ctx.root.querySelector('[data-oauth-code]').hidden, true);
  assert.equal(ctx.root.querySelector('[data-action="oauth-start"]').hidden, false);
  ctx.mounted.dispose();
  ctx.window.close();
});

test('cancel stops polling and returns the panel to an idle state', async () => {
  let polls = 0;
  const cancels = [];
  const ctx = await mountDetail('firecrawl', {
    oauthLoginStart: async () => 3,
    oauthLoginPoll: async () => { polls += 1; return login('waiting', { id: 3, user_code: 'CODE-1234' }); },
    oauthLoginCancel: async id => { cancels.push(id); return login('cancelled', { id: 3 }); },
  }, { oauthPollInterval: 1 });
  ctx.root.querySelector('[data-action="oauth-start"]').click();
  await until(() => /等待浏览器授权/.test(ctx.root.querySelector('[data-oauth-status]').textContent));
  ctx.root.querySelector('[data-action="oauth-cancel"]').click();
  await until(() => /已取消登录/.test(ctx.root.querySelector('[data-oauth-status]').textContent), 'cancel phase not rendered');
  assert.deepEqual(cancels, [3]);
  assert.equal(ctx.root.querySelector('[data-action="oauth-start"]').hidden, false);
  assert.equal(ctx.root.querySelector('[data-action="oauth-cancel"]').hidden, true);
  await delay(20);
  const settled = polls;
  await delay(20);
  assert.equal(polls, settled, 'polling must stop after cancellation');
  ctx.mounted.dispose();
  ctx.window.close();
});

test('pagehide stops polling and cancels the managed login child', async () => {
  let polls = 0;
  const cancels = [];
  const ctx = await mountDetail('firecrawl', {
    oauthLoginStart: async () => 11,
    oauthLoginPoll: async () => { polls += 1; return login('waiting', { id: 11 }); },
    oauthLoginCancel: async id => { cancels.push(id); return login('cancelled', { id: 11 }); },
  }, { oauthPollInterval: 1 });
  ctx.root.querySelector('[data-action="oauth-start"]').click();
  await until(() => /等待浏览器授权/.test(ctx.root.querySelector('[data-oauth-status]').textContent));
  ctx.window.dispatchEvent(new ctx.window.Event('pagehide'));
  await flush();
  assert.deepEqual(cancels, [11]);
  assert.equal(ctx.root.querySelector('[data-oauth-login]'), null);
  await delay(20);
  const settled = polls;
  await delay(20);
  assert.equal(polls, settled, 'polling must stop after page unload');
  ctx.window.close();
});

test('a provider error the CLI reports in English is shown, not replaced by a generic line', async () => {
  // The login used to fail with only "登录失败，请重试。": the CLI's
  // "Parallel: HTTP 400: client_name or redirect_uris is required" was hidden.
  const message = 'Parallel: HTTP 400: client_name or redirect_uris is required to derive a client_id';
  const ctx = await mountDetail('firecrawl', {
    oauthLoginStart: async () => 6,
    oauthLoginPoll: async () => login('error', { id: 6, message }),
    oauthLoginCancel: async () => { throw new Error('terminal state must not cancel'); },
  }, { oauthPollInterval: 1 });
  ctx.root.querySelector('[data-action="oauth-start"]').click();
  await until(() => /登录失败/.test(ctx.root.querySelector('[data-oauth-status]').textContent), 'error phase not rendered');
  assert.match(ctx.root.querySelector('[data-info="oauth-error"]').textContent, /client_name or redirect_uris is required/);
  ctx.mounted.dispose();
  ctx.window.close();
});

test('error phase shows the CLI message and allows a retry', async () => {
  const ctx = await mountDetail('firecrawl', {
    oauthLoginStart: async () => 5,
    oauthLoginPoll: async () => login('error', { id: 5, message: 'Firecrawl 授权失败：session expired' }),
    oauthLoginCancel: async () => { throw new Error('terminal state must not cancel'); },
  }, { oauthPollInterval: 1 });
  ctx.root.querySelector('[data-action="oauth-start"]').click();
  await until(() => /登录失败/.test(ctx.root.querySelector('[data-oauth-status]').textContent), 'error phase not rendered');
  assert.match(ctx.root.querySelector('[data-info="oauth-error"]').textContent, /授权失败/);
  assert.equal(ctx.root.querySelector('[data-action="oauth-start"]').hidden, false);
  assert.equal(ctx.root.querySelector('[data-action="oauth-cancel"]').hidden, true);
  ctx.mounted.dispose();
  ctx.window.close();
});
