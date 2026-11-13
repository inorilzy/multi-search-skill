import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { managementApi } from '../ui/api.js';
import { mountDashboardLogin, dashboardMethodForSource } from '../ui/dashboard-login.js';
import { mountProviderAccounts } from '../ui/credentials.js';

const flush = async () => { for (let i = 0; i < 4; i++) await new Promise(resolve => setTimeout(resolve, 0)); };
function setup(source, api, onComplete) {
  const window = new Window();
  const root = window.document.createElement('div');
  window.document.body.append(root);
  return { window, root, mounted: mountDashboardLogin(root, api, { source, onComplete }) };
}

test('only declared providers expose dashboard login and the IPC sends no URL or secret', async () => {
  assert.equal(dashboardMethodForSource('brave').id, 'brave');
  assert.equal(dashboardMethodForSource('exa').id, 'exa');
  assert.equal(dashboardMethodForSource('tavily'), null);
  const calls = [];
  const api = managementApi(async (command, args) => { calls.push([command, args]); return true; });
  assert.equal(await api.dashboardLogin(' brave '), true);
  await api.dashboardLoginCancel('brave');
  assert.deepEqual(calls, [['dashboard_login', { provider: 'brave' }], ['dashboard_login_cancel', { provider: 'brave' }]]);
  await assert.rejects(api.dashboardLogin(''), { code: 'INVALID_ARGUMENT' });
  await assert.rejects(managementApi(async () => 'cookie=private').dashboardLogin('brave'), { code: 'INVALID_PAYLOAD' });
});

test('successful login reads a fresh balance before refreshing the page once', async () => {
  const calls = [];
  const ctx = setup('brave', {
    dashboardLogin: async provider => { calls.push(['login', provider]); return true; },
    dashboardLoginCancel: async () => { assert.fail('completed login is not cancelled'); },
    balanceView: async (...args) => { calls.push(['balance', ...args]); },
  }, async () => { calls.push(['page']); });
  const mounted = await ctx.mounted;
  ctx.root.querySelector('[data-dashboard-start]').click();
  await flush();
  assert.deepEqual(calls, [['login', 'brave'], ['balance', 'brave', true], ['page']]);
  assert.match(ctx.root.querySelector('[data-dashboard-status]').textContent, /用量已刷新/);
  mounted.dispose(); ctx.window.close();
});

test('cancelling a Chrome login does not query balance or show success', async () => {
  let resolveLogin;
  const calls = [];
  const ctx = setup('exa', {
    dashboardLogin: () => new Promise(resolve => { resolveLogin = resolve; }),
    dashboardLoginCancel: async provider => { calls.push(['cancel', provider]); resolveLogin(false); },
    balanceView: async () => assert.fail('no balance for cancelled login'),
  }, () => assert.fail('no page refresh for cancelled login'));
  const mounted = await ctx.mounted;
  const start = ctx.root.querySelector('[data-dashboard-start]');
  assert.equal(start.textContent, '用 Chrome 登录');
  assert.equal(ctx.root.querySelector('.oauth-login-sub').textContent, '复用 Chrome 现有登录，仅查询此服务商额度。');
  start.click(); start.click();
  assert.equal(start.hidden, true);
  assert.equal(ctx.root.querySelector('[data-dashboard-status]').textContent, '等待 Chrome 连接授权或页面登录…');
  ctx.root.querySelector('[data-dashboard-cancel]').click();
  await flush();
  assert.deepEqual(calls, [['cancel', 'exa']]);
  assert.match(ctx.root.querySelector('[data-dashboard-status]').textContent, /已取消/);
  assert.equal(start.hidden, false);
  mounted.dispose(); ctx.window.close();
});

test('disposing cancels the owned Chrome login session and ignores a late success', async () => {
  let resolveLogin, cancelled = 0;
  const ctx = setup('brave', {
    dashboardLogin: () => new Promise(resolve => { resolveLogin = resolve; }),
    dashboardLoginCancel: async () => { cancelled++; },
    balanceView: async () => assert.fail('late login must not refresh an unmounted page'),
  });
  const mounted = await ctx.mounted;
  ctx.root.querySelector('[data-dashboard-start]').click();
  mounted.dispose();
  resolveLogin(true); await flush();
  assert.equal(cancelled, 1);
  assert.equal(ctx.root.childElementCount, 0);
  ctx.window.close();
});

test('a saved login with a failed balance read stays saved and offers a refresh', async () => {
  const ctx = setup('exa', {
    dashboardLogin: async () => true,
    dashboardLoginCancel: async () => {},
    balanceView: async () => { throw new Error('network'); },
  });
  const mounted = await ctx.mounted;
  ctx.root.querySelector('[data-dashboard-start]').click(); await flush();
  assert.equal(ctx.root.querySelector('[data-dashboard-status]').textContent, '登录已保存。');
  assert.match(ctx.root.querySelector('[data-dashboard-error]').textContent, /用量读取失败/);
  mounted.dispose(); ctx.window.close();
});

test('quota rate limiting does not turn a saved Chrome login into a login failure', async () => {
  const ctx = setup('exa', {
    dashboardLogin: async () => true,
    dashboardLoginCancel: async () => {},
    balanceView: async () => ({ providers: [{ reports: [{ status: 'error', error_kind: 'rate_limit', message: 'limited' }] }] }),
  });
  const mounted = await ctx.mounted;
  ctx.root.querySelector('[data-dashboard-start]').click(); await flush();
  assert.equal(ctx.root.querySelector('[data-dashboard-status]').textContent, '登录已保存。');
  assert.equal(ctx.root.querySelector('[data-dashboard-error]').textContent, '额度接口暂时限流，请稍后刷新。');
  assert.equal(ctx.root.querySelector('[data-dashboard-start]').hidden, false);
  mounted.dispose(); ctx.window.close();
});

test('provider account dialogs mount exactly one dashboard login below the key editors', async () => {
  const window = new Window(), root = window.document.createElement('main');
  window.document.body.append(root);
  const mounted = await mountProviderAccounts(root, {
    accountsView: async () => ({ status: 'ready', accounts: { brave: [{ id: 'default', name: '默认账号', source: 'manual', keys: [], balance_credentials: {} }] } }),
    credentialStatus: async () => ({ store: { state: 'absent' }, effective_source: 'none' }),
    credentialRead: async () => ({ value: '', snapshot: 'fixture' }),
    dashboardLogin: async () => true,
    dashboardLoginCancel: async () => {},
  }, { source: 'brave' });
  assert.equal(root.querySelectorAll('[data-dashboard-login]').length, 1);
  assert.ok(root.querySelector('[data-provider-login] [data-dashboard-login]'));
  mounted.dispose(); window.close();
});
