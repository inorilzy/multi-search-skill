import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountDiagnostics } from '../ui/diagnostics.js';

const routes = {
  default: { label: '默认（网页综合）', sources: ['tavily'], timeout: null },
  dev: { label: '开发者', sources: ['hackernews'], timeout: 18 },
};
const settings = (overrides = {}) => ({ route: 'default', timeout: 60, timeout_configured: true, effective_timeout: 60, effective_timeouts: { default: 60, dev: 18 }, routes, status: 'ok', message: '', ...overrides });
const withSettings = api => ({ settingsView: async () => settings(), ...api });
const setup = () => { const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root); return { window, root }; };
const flush = (ms = 0) => new Promise(resolve => setTimeout(resolve, ms));

test('overview distinguishes app invocation from user command discovery', async () => {
  const { window, root } = setup();
  await mountDiagnostics(root, withSettings({ detect: async () => ({ app: { status: 'ready', path: 'C:\\fixture\\multi-search.exe', version: '0.4.0', reason: '' }, user: { status: 'missing', path: null, version: null, reason: 'not on user PATH' }, restart_required: false }) }));
  assert.match(root.textContent, /0\.4\.0/);
  assert.match(root.textContent, /C:\\fixture\\multi-search.exe/);
  assert.equal(root.querySelector('[data-status="app"]').textContent, '可调用');
  assert.equal(root.querySelector('[data-status="user"]').textContent, '未发现');
  assert.match(root.textContent, /not on user PATH/);
  window.close();
});

test('new user PATH enables immediate search while old app environment stays visibly missing', async () => {
  const { window, root } = setup();
  await mountDiagnostics(root, withSettings({ detect: async () => ({ app: { status: 'missing' }, user: { status: 'ready' }, restart_required: true }) }));
  assert.equal(root.querySelector('[data-status="app"]').textContent, '未发现');
  assert.equal(root.querySelector('[data-action="search"]').disabled, false);
  window.close();
});

test('a discovered outdated CLI suggests an update and refresh restores search', async () => {
  const { window, root } = setup();
  let ready = false;
  const api = withSettings({ detect: async () => { const row = { status: ready ? 'ready' : 'version_failed', path: 'C:\\fixture\\multi-search.exe', reason: ready ? '' : '退出码 2；请更新 CLI' }; return { app: row, user: row, restart_required: false }; } });
  const page = await mountDiagnostics(root, api);
  assert.equal(root.querySelector('[data-action="search"]').disabled, true);
  assert.match(root.querySelector('[data-info="restart"]').textContent, /更新 CLI/);
  ready = true; root.querySelector('[data-action="refresh"]').click(); await flush();
  assert.equal(root.querySelector('[data-action="search"]').disabled, false);
  page.dispose(); window.close();
});

test('test search reflects partial execution and renders provider text without HTML', async () => {
  const { window, root } = setup();
  const api = withSettings({
    detect: async () => ({ app: { status: 'ready', version: '0.4.0', path: 'C:\\multi-search.exe' }, user: { status: 'ready' }, restart_required: false }),
    start: async () => 1,
    poll: async () => ({ id: 1, status: 'partial', exit_code: 0, payload: { results: [{ title: '<img src=x onerror=attack()>' }], errors: [{ source: 'brave', error: 'unavailable [REDACTED]' }] }, error: '' }),
  });
  await mountDiagnostics(root, api, { pollInterval: 1 });
  root.querySelector('[data-field="query"]').value = 'fixture';
  root.querySelector('[data-action="search"]').click(); await flush(25);
  assert.equal(root.querySelector('[data-status="execution"]').textContent, '部分来源失败');
  assert.match(root.querySelector('[data-results]').textContent, /<img src=x onerror=attack\(\)>/);
  assert.equal(root.querySelector('[data-results] img'), null);
  assert.equal(root.querySelector('[data-action="search"]').disabled, false);
  window.close();
});

test('failed execution retains a visible error and permits retry', async () => {
  const { window, root } = setup();
  const api = withSettings({ detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' } }), start: async () => 1, poll: async () => ({ status: 'failed', error: 'provider unavailable [REDACTED]', payload: { errors: [{ source: 'brave' }] } }) });
  const page = await mountDiagnostics(root, api); root.querySelector('[data-field="query"]').value = 'failure'; root.querySelector('[data-action="search"]').click(); await flush(10);
  assert.equal(root.querySelector('[data-status="execution"]').textContent, '执行失败');
  assert.match(root.querySelector('[data-execution-error]').textContent, /provider unavailable/);
  page.dispose(); window.close();
});

test('a late poll cannot overwrite a cancelled execution', async () => {
  const { window, root } = setup();
  let finishPoll;
  const api = withSettings({ detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' } }), start: async () => 7, poll: () => new Promise(resolve => { finishPoll = resolve; }), cancel: async () => ({ status: 'cancelled' }) });
  const page = await mountDiagnostics(root, api);
  root.querySelector('[data-field="query"]').value = 'hang'; root.querySelector('[data-action="search"]').click(); await flush(5); root.querySelector('[data-action="cancel"]').click(); await flush(5); finishPoll({ status: 'running' }); await flush(5);
  assert.equal(root.querySelector('[data-status="execution"]').textContent, '已取消');
  assert.equal(root.querySelector('[data-action="search"]').disabled, false);
  page.dispose(); window.close();
});

test('user can cancel current execution and missing CLI disables start', async () => {
  const { window, root } = setup();
  let cancelled = null;
  const api = withSettings({ detect: async () => ({ app: { status: 'ready' }, user: { status: 'missing' } }), start: async () => 42, poll: async () => ({ status: 'running' }), cancel: async id => { cancelled = id; return { status: 'cancelled' }; } });
  const page = await mountDiagnostics(root, api, { pollInterval: 1000 });
  root.querySelector('[data-field="query"]').value = 'hang'; root.querySelector('[data-action="search"]').click(); await flush(5); root.querySelector('[data-action="cancel"]').click(); await flush(5);
  assert.equal(cancelled, 42);
  assert.equal(root.querySelector('[data-status="execution"]').textContent, '已取消');
  page.dispose(); window.close();
});

test('route options come from SettingsView and selected effective timeout is submitted', async () => {
  const { window, root } = setup();
  let sent;
  const dynamicRoutes = Object.fromEntries([
    ['research', { label: '研究 <unsafe>', sources: ['hackernews'], timeout: 9 }],
    ['__proto__', { label: '原型键', sources: ['tavily'], timeout: null }],
  ]);
  await mountDiagnostics(root, {
    settingsView: async () => settings({ route: 'research', routes: dynamicRoutes, effective_timeout: 9 }),
    detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' } }),
    start: async (_path, options) => { sent = options; return 1; },
    poll: async () => ({ status: 'success', payload: { results: [] }, error: '' }),
  });
  assert.deepEqual([...root.querySelectorAll('[data-field="route"] option')].map(option => option.value), ['research', '__proto__']);
  assert.equal(root.querySelector('[data-field="route"] img'), null);
  assert.equal(root.querySelector('[data-field="timeout"]').value, '9');
  root.querySelector('[data-field="query"]').value = 'dynamic';
  root.querySelector('[data-action="search"]').click(); await flush();
  assert.equal(sent.route, 'research');
  assert.equal(sent.timeout, 9);
  window.close();
});

test('switching route updates explicit test timeout from group override or global value', async () => {
  const { window, root } = setup();
  await mountDiagnostics(root, withSettings({ detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' } }) }));
  const select = root.querySelector('[data-field="route"]');
  select.value = 'dev'; select.dispatchEvent(new window.Event('change'));
  assert.equal(root.querySelector('[data-field="timeout"]').value, '18');
  select.value = 'default'; select.dispatchEvent(new window.Event('change'));
  assert.equal(root.querySelector('[data-field="timeout"]').value, '60');
  window.close();
});

test('switching routes without a global timeout uses backend previews for every group', async () => {
  const { window, root } = setup();
  const metaRoutes = {
    default: { label: '默认', sources: ['tavily'], timeout: null },
    fast: { label: '快速', sources: ['tavily'], timeout: null },
    all: { label: '全部', sources: ['hackernews'], timeout: null },
  };
  await mountDiagnostics(root, {
    settingsView: async () => settings({ routes: metaRoutes, timeout_configured: false, effective_timeouts: { default: 60, fast: 45, all: 90 } }),
    detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' } }),
  });
  const select = root.querySelector('[data-field="route"]');
  const timeout = root.querySelector('[data-field="timeout"]');
  select.value = 'fast'; select.dispatchEvent(new window.Event('change'));
  assert.equal(timeout.value, '45');
  select.value = 'all'; select.dispatchEvent(new window.Event('change'));
  assert.equal(timeout.value, '90');
  select.value = 'default'; select.dispatchEvent(new window.Event('change'));
  assert.equal(timeout.value, '60');
  window.close();
});

test('legacy all route preview allows only its actual 90 second exception above sixty', async () => {
  const { window, root } = setup();
  let sent;
  const allRoutes = { all: { label: '全部', sources: ['hackernews'], timeout: null } };
  await mountDiagnostics(root, {
    settingsView: async () => settings({ route: 'all', routes: allRoutes, timeout: 60, timeout_configured: false, effective_timeout: 90, effective_timeouts: { all: 90 } }),
    detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' } }),
    start: async (_path, options) => { sent = options; return 1; },
    poll: async () => ({ status: 'success', payload: {}, error: '' }),
  });
  const timeout = root.querySelector('[data-field="timeout"]');
  assert.equal(timeout.value, '90');
  assert.equal(timeout.max, '90');
  root.querySelector('[data-field="query"]').value = 'all';
  timeout.value = '89';
  root.querySelector('[data-action="search"]').click(); await flush();
  assert.equal(sent, undefined);
  assert.match(root.querySelector('[data-execution-error]').textContent, /实际默认值 90/);
  timeout.value = '90';
  root.querySelector('[data-action="search"]').click(); await flush();
  assert.equal(sent.timeout, 90);
  window.close();
});

test('settings read failure never supplies hardcoded default and disables test', async () => {
  const { window, root } = setup();
  await mountDiagnostics(root, {
    settingsView: async () => { throw Error('offline'); },
    detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' } }),
  });
  assert.equal(root.querySelectorAll('[data-field="route"] option').length, 0);
  assert.equal(root.querySelector('[data-action="search"]').disabled, true);
  assert.match(root.querySelector('[data-info="settings-error"]').textContent, /不会使用硬编码路由/);
  window.close();
});
