import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { createUsageAutoRefresh, USAGE_REFRESH_INTERVAL } from '../ui/usage-auto-refresh.js';
import { createNavigation } from '../ui/app.js';
import { mountUsage } from '../ui/usage.js';
import { managementApi } from '../ui/api.js';

function clock() {
  let time = Date.parse('2026-11-13T00:00:00Z');
  let next = 0;
  const timers = new Map();
  return {
    now: () => time,
    schedule(callback, delay) { const id = ++next; timers.set(id, { callback, delay }); return id; },
    cancel: id => timers.delete(id),
    advance: ms => { time += ms; },
    get timers() { return [...timers.values()]; },
    async tick(ms = USAGE_REFRESH_INTERVAL) {
      time += ms;
      const [id, timer] = timers.entries().next().value;
      timers.delete(id);
      await timer.callback();
    },
  };
}
const provider = (id = 'tavily', overrides = {}) => ({
  id, label: id, balance_supported: true, balance_note: '', current: [], totals: [], history: [], pace: [],
  accounts: [{ id: 'default', name: '默认账号', source: 'manual', keys: [{ key_fingerprint: 'fp', report: null }],
    total: { remaining: null, limit: null, percent: null, unit: null, relative: false } }],
  total: { remaining: null, limit: null, percent: null, unit: null, relative: false }, alert: null,
  calls: { today: {}, last_7_days: {}, daily: [] }, ...overrides,
});
const view = providers => ({ status: 'ready', message: '', schema_version: 1, retention_days: 30, providers });
const accounts = values => ({ status: 'ready', message: '', accounts: values });
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

test('startup and every ten minutes refresh only configured balance providers, including account-only credentials', async () => {
  const time = clock();
  const calls = [];
  let saved = false;
  const rows = [provider(), provider('exa', { accounts: [] }), provider('empty', { accounts: [] }),
    provider('baidu', { balance_supported: false }), provider('later', { accounts: [] })];
  const api = {
    usageView: async (id, refresh) => {
      calls.push([id, refresh]);
      return view(id ? rows.filter(row => row.id === id) : rows);
    },
    accountsView: async () => accounts({ exa: [{ keys: [], balance_credentials: { exa_admin: 'fingerprint' } }],
      later: saved ? [{ keys: ['fp-new'], balance_credentials: {} }] : [] }),
    oauthLoginStart() { assert.fail('automatic refresh must never log in'); },
    dashboardLogin() { assert.fail('automatic refresh must never open Chrome'); },
    credentialTest() { assert.fail('automatic refresh must never search'); },
  };
  const refresh = createUsageAutoRefresh(api, time);
  await refresh.start();
  assert.equal(USAGE_REFRESH_INTERVAL, 600_000);
  assert.deepEqual(calls, [[null, false], ['tavily', true], ['exa', true]]);
  assert.equal(time.timers.length, 1);
  assert.equal(time.timers[0].delay, 600_000);
  await refresh.start();
  assert.equal(calls.length, 3, 'starting twice neither refreshes early nor creates a second timer');
  saved = true;
  await time.tick();
  assert.deepEqual(calls.slice(3), [[null, false], ['tavily', true], ['exa', true], ['later', true]]);
  refresh.dispose();
  assert.equal(time.timers.length, 0);
});

test('a failed provider waits a full cycle while other configured providers still refresh', async () => {
  const time = clock();
  const calls = [];
  const refresh = createUsageAutoRefresh({
    usageView: async (id, force) => {
      calls.push([id, force]);
      if (id === 'tavily') throw new Error('rate limited');
      return view(id ? [provider(id)] : [provider(), provider('exa')]);
    },
  }, time);
  await refresh.start();
  assert.deepEqual(calls, [[null, false], ['tavily', true], ['exa', true]]);
  time.advance(599_999);
  await refresh.start();
  assert.equal(calls.length, 3);
  assert.equal(time.timers.length, 1);
  await time.tick(1);
  assert.deepEqual(calls.slice(3), [[null, false], ['tavily', true], ['exa', true]]);
  refresh.dispose();
});

test('metadata failures do not make empty providers eligible or trigger immediate retries', async () => {
  const time = clock();
  const calls = [];
  const refresh = createUsageAutoRefresh({
    usageView: async (id, force) => {
      calls.push([id, force]);
      return view(id ? [provider(id)] : [provider(), provider('empty', { accounts: [] })]);
    },
    accountsView: async () => { throw new Error('unreadable metadata'); },
  }, time);
  await refresh.start();
  assert.deepEqual(calls, [[null, false], ['tavily', true]]);
  await refresh.start();
  assert.equal(calls.length, 2);
  assert.equal(time.timers.length, 1);
  refresh.dispose();
});

test('automatic and manual usage/balance requests share one queue, even across slow cycles', async () => {
  const time = clock();
  const started = deferred();
  const release = deferred();
  let active = 0;
  let maxActive = 0;
  const calls = [];
  const refresh = createUsageAutoRefresh({
    usageView: async (id, force) => {
      active += 1; maxActive = Math.max(maxActive, active); calls.push(['usage', id, force]);
      if (id === 'tavily') { started.resolve(); await release.promise; }
      active -= 1;
      return view([provider()]);
    },
    balanceView: async id => {
      active += 1; maxActive = Math.max(maxActive, active); calls.push(['balance', id]); active -= 1;
      return { providers: [] };
    },
  }, time);
  const initial = refresh.start();
  await started.promise;
  time.advance(USAGE_REFRESH_INTERVAL * 3);
  const duplicate = refresh.start();
  const manual = refresh.api.balanceView('exa', true);
  assert.equal(time.timers.length, 0, 'a new automatic timer starts after the slow cycle completes');
  assert.equal(calls.length, 2);
  release.resolve();
  await Promise.all([initial, duplicate, manual]);
  assert.equal(maxActive, 1);
  assert.deepEqual(calls, [['usage', null, false], ['usage', 'tavily', true], ['balance', 'exa']]);
  assert.equal(time.timers.length, 1);
  assert.equal(time.timers[0].delay, USAGE_REFRESH_INTERVAL);
  refresh.dispose();
});

test('background timers still run and visible/focus/pageshow events catch up only when overdue', async () => {
  const window = new Window();
  const time = clock();
  const calls = [];
  const refresh = createUsageAutoRefresh({ usageView: async (id, force) => {
    calls.push([id, force]); return view([provider()]);
  } }, { ...time, document: window.document, window });
  await refresh.start();
  Object.defineProperty(window.document, 'visibilityState', { configurable: true, value: 'hidden' });
  await time.tick();
  assert.equal(calls.filter(([, force]) => force).length, 2, 'hidden does not pause the application timer');
  time.advance(USAGE_REFRESH_INTERVAL * 2);
  Object.defineProperty(window.document, 'visibilityState', { configurable: true, value: 'visible' });
  window.document.dispatchEvent(new window.Event('visibilitychange'));
  window.dispatchEvent(new window.Event('focus'));
  window.dispatchEvent(new window.Event('pageshow'));
  await refresh.start();
  assert.equal(calls.filter(([, force]) => force).length, 3, 'resume events join the same catch-up');
  window.dispatchEvent(new window.Event('focus'));
  await refresh.start();
  assert.equal(calls.filter(([, force]) => force).length, 3, 'a recent refresh is not repeated');
  refresh.dispose();
  time.advance(USAGE_REFRESH_INTERVAL);
  window.dispatchEvent(new window.Event('pageshow'));
  await refresh.start();
  assert.equal(calls.filter(([, force]) => force).length, 3);
  window.close();
});

test('disposal during a request ignores late results and never schedules another cycle', async () => {
  const time = clock();
  const release = deferred();
  const started = deferred();
  let updates = 0;
  const refresh = createUsageAutoRefresh({ usageView: async (id) => {
    if (id) { started.resolve(); return release.promise; }
    return view([provider()]);
  } }, time);
  refresh.subscribe(() => { updates += 1; });
  const pending = refresh.start();
  await started.promise;
  refresh.dispose();
  release.resolve(view([provider()]));
  await pending;
  assert.equal(updates, 0);
  assert.equal(time.timers.length, 0);
});

test('one application scheduler survives route changes and updates the current usage page from cache', async () => {
  const window = new Window();
  const doc = window.document;
  const nav = doc.createElement('nav');
  const root = doc.createElement('main');
  doc.body.append(nav, root);
  const time = clock();
  const calls = [];
  let value = 600;
  const row = () => provider('tavily', { total: { remaining: value, limit: 1000, percent: value / 10,
    unit: 'credits', relative: false }, current: [{ provider: 'tavily', status: 'ok', scope: 'key', unit: 'credits',
    remaining: value, limit: 1000, used: 1000 - value, resets_at: null, period: 'month', key_fingerprint: 'fp',
    error_kind: null, message: '', fetched_at: new Date(time.now()).toISOString() }] });
  let scheduler;
  const other = { id: 'other', label: '其他', number: '01', mount: async (node, api, options) => {
    scheduler = options.usageRefresh;
    node.innerHTML = '<h1>其他</h1>';
  } };
  const usage = { id: 'usage', label: '用量', number: '05', mount: mountUsage };
  const invoke = async (command, args) => {
    calls.push([command, args]);
    if (command === 'accounts_view') return accounts({});
    assert.equal(command, 'usage_view');
    return view([row()]);
  };
  const refresh = createUsageAutoRefresh(managementApi(invoke), { ...time, document: doc, window });
  const app = createNavigation(root, nav, invoke, [other, usage], refresh);
  await app.select(other);
  // A page mount joins the same request queue; no sleeps or real backend calls are needed.
  await app.select(usage);
  await scheduler.start();
  assert.match(root.querySelector('[data-updated]').textContent, /每10分钟自动刷新 · 最近更新：2026-11-13 00:00 UTC/);
  assert.equal(root.querySelector('.provider-meter .meter-value').textContent, '60%');
  assert.equal(time.timers.length, 1);
  value = 300;
  root.querySelector('summary').click();
  const refreshButton = root.querySelector('[data-action="refresh-provider"]');
  refreshButton.focus();
  await time.tick();
  assert.equal(root.querySelector('.provider-meter .meter-value').textContent, '30%');
  assert.match(root.querySelector('[data-updated]').textContent, /最近更新：2026-11-13 00:10 UTC/);
  assert.equal(root.querySelector('details').open, true);
  assert.equal(doc.activeElement, refreshButton);
  await app.select(other);
  value = 100;
  await time.tick();
  assert.equal(root.querySelector('h1').textContent, '其他');
  await app.select(usage);
  assert.equal(root.querySelector('.provider-meter .meter-value').textContent, '10%');
  assert.equal(time.timers.length, 1);
  assert.ok(calls.filter(([command, args]) => command === 'usage_view' && args.refresh)
    .every(([, args]) => args.provider === 'tavily'), 'route changes never cause all-provider network refreshes');
  value = 200;
  root.querySelector('[data-action="refresh-provider"]').click();
  await refresh.api.usageView(null, false);
  assert.deepEqual(calls.filter(([command, args]) => command === 'usage_view' && args.refresh).at(-1),
    ['usage_view', { provider: 'tavily', refresh: true }]);
  assert.equal(root.querySelector('.provider-meter .meter-value').textContent, '20%');
  root.querySelector('[data-action="refresh-all"]').click();
  await refresh.api.usageView(null, false);
  assert.deepEqual(calls.filter(([command, args]) => command === 'usage_view' && args.refresh).at(-1),
    ['usage_view', { provider: null, refresh: true }], 'manual refresh-all keeps its existing meaning');
  app.dispose();
  assert.equal(time.timers.length, 0);
  window.close();
});

test('a successful automatic update clears an old page error and disposes its subscription', async () => {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  let listener;
  let unsubscribed = 0;
  const mounted = await mountUsage(root, {
    usageView: async (id, refresh) => {
      assert.deepEqual([id, refresh], [null, false]);
      throw { code: 'usage_view_failed', message: 'worker failed' };
    },
  }, { usageRefresh: { subscribe(callback) { listener = callback; return () => { unsubscribed += 1; }; } } });
  assert.equal(root.querySelector('[data-error]').textContent, '用量读取失败，请重试。');
  listener(view([provider()]), 'tavily');
  assert.equal(root.querySelector('[data-error]').textContent, '');
  assert.equal(root.querySelector('[data-error]').hasAttribute('title'), false);
  assert.ok(root.querySelector('[data-provider="tavily"]'));
  mounted.dispose();
  assert.equal(unsubscribed, 1);
  const markup = root.innerHTML;
  listener(view([provider('exa')]), 'exa');
  assert.equal(root.innerHTML, markup);
  window.close();
});
