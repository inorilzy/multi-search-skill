import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountDiagnostics } from '../ui/diagnostics.js';

test('overview distinguishes app invocation from user command discovery', async () => {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  const api = { detect: async () => ({ app: { status: 'ready', path: 'C:\\fixture\\multi-search.exe', version: '0.4.0', reason: '' }, user: { status: 'missing', path: null, version: null, reason: 'not on user PATH' }, restart_required: false, execution: { status: 'ready', path: 'C:\\fixture\\multi-search.exe' }, managed: false }) };
  await mountDiagnostics(root, api);
  assert.match(root.textContent, /0\.4\.0/);
  assert.match(root.textContent, /C:\\fixture\\multi-search.exe/);
  assert.equal(root.querySelector('[data-status="app"]').textContent, '可调用');
  assert.equal(root.querySelector('[data-status="user"]').textContent, '未发现');
  assert.match(root.textContent, /not on user PATH/);
  assert.match(root.textContent, /终端/);
  window.close();
});

test('new user PATH enables immediate search while old app environment stays visibly missing', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  await mountDiagnostics(root, { detect: async () => ({ app: { status: 'missing' }, user: { status: 'ready' }, restart_required: true, execution: { status: 'ready' }, managed: false }) });
  assert.equal(root.querySelector('[data-status="app"]').textContent, '未发现');
  assert.equal(root.querySelector('[data-action="search"]').disabled, false);
  window.close();
});

test('a discovered outdated CLI suggests an update, not PATH changes, and refresh restores search', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  let ready = false;
  const api = { detect: async () => {
    const row = { status: ready ? 'ready' : 'version_failed', path: 'C:\\fixture\\multi-search.exe', reason: ready ? '' : '退出码 2；请更新 CLI' };
    return { app: row, user: row, restart_required: false, execution: row, managed: false };
  } };
  const page = await mountDiagnostics(root, api);
  assert.equal(root.querySelector('[data-action="search"]').disabled, true);
  assert.match(root.querySelector('[data-info="restart"]').textContent, /更新 CLI/);
  assert.doesNotMatch(root.querySelector('[data-info="restart"]').textContent, /检查用户 PATH/);
  ready = true;
  root.querySelector('[data-action="refresh"]').click();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(root.querySelector('[data-action="search"]').disabled, false);
  page.dispose(); window.close();
});

test('test search reflects partial execution and renders provider text without HTML', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  const api = {
    detect: async () => ({ app: { status: 'ready', version: '0.4.0', path: 'C:\\multi-search.exe' }, user: { status: 'ready' }, restart_required: false, execution: { status: 'ready' } }),
    start: async () => 1,
    poll: async () => ({ id: 1, status: 'partial', exit_code: 0, payload: { results: [{ title: '<img src=x onerror=attack()>' }], errors: [{ source: 'brave', error: 'unavailable [REDACTED]' }] }, error: '' }),
  };
  await mountDiagnostics(root, api, { pollInterval: 1 });
  root.querySelector('[data-field="query"]').value = 'fixture';
  root.querySelector('[data-action="search"]').click();
  await new Promise(resolve => setTimeout(resolve, 25));
  assert.equal(root.querySelector('[data-status="execution"]').textContent, '部分来源失败');
  assert.match(root.querySelector('[data-results]').textContent, /<img src=x onerror=attack\(\)>/);
  assert.equal(root.querySelector('[data-results] img'), null);
  assert.match(root.textContent, /unavailable \[REDACTED\]/);
  assert.equal(root.querySelector('[data-action="search"]').disabled, false);
  assert.equal(root.querySelector('[data-action="cancel"]').disabled, true);
  window.close();
});

test('failed execution retains a visible error and permits retry', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  const api = { detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' }, execution: { status: 'ready' } }), start: async () => 1, poll: async () => ({ status: 'failed', error: 'provider unavailable [REDACTED]', payload: { errors: [{ source: 'brave' }] } }) };
  const page = await mountDiagnostics(root, api); root.querySelector('[data-field="query"]').value = 'failure'; root.querySelector('[data-action="search"]').click();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(root.querySelector('[data-status="execution"]').textContent, '执行失败');
  assert.match(root.querySelector('[data-execution-error]').textContent, /provider unavailable/);
  assert.equal(root.querySelector('[data-action="search"]').disabled, false);
  page.dispose(); window.close();
});

test('a late poll cannot overwrite a cancelled execution', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  let finishPoll;
  const api = { detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' }, execution: { status: 'ready' } }), start: async () => 7, poll: () => new Promise(resolve => { finishPoll = resolve; }), cancel: async () => ({ status: 'cancelled' }) };
  const page = await mountDiagnostics(root, api);
  root.querySelector('[data-field="query"]').value = 'hang'; root.querySelector('[data-action="search"]').click();
  await new Promise(resolve => setTimeout(resolve, 5)); root.querySelector('[data-action="cancel"]').click();
  await new Promise(resolve => setTimeout(resolve, 5)); finishPoll({ status: 'running' });
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(root.querySelector('[data-status="execution"]').textContent, '已取消');
  assert.equal(root.querySelector('[data-action="search"]').disabled, false);
  page.dispose(); window.close();
});

test('user can cancel the current execution and missing CLI disables start', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  let cancelled = null;
  const api = { detect: async () => ({ app: { status: 'ready' }, user: { status: 'missing' }, execution: { status: 'ready' } }), start: async () => 42, poll: async () => ({ status: 'running' }), cancel: async id => { cancelled = id; return { status: 'cancelled' }; } };
  const page = await mountDiagnostics(root, api, { pollInterval: 1000 });
  root.querySelector('[data-field="query"]').value = 'hang'; root.querySelector('[data-action="search"]').click();
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(root.querySelector('[data-action="search"]').disabled, true);
  root.querySelector('[data-action="cancel"]').click(); await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(cancelled, 42);
  assert.equal(root.querySelector('[data-status="execution"]').textContent, '已取消');
  assert.equal(root.querySelector('[data-action="search"]').disabled, false);
  page.dispose();
  await mountDiagnostics(root, { detect: async () => ({ app: { status: 'missing' }, user: { status: 'missing' } }) });
  assert.equal(root.querySelector('[data-action="search"]').disabled, true);
  window.close();
});

test('leaving the page cancels the running CLI so the next visit is not blocked', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  const cancelled = [];
  const api = {
    detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' }, execution: { status: 'ready' } }),
    start: async () => 9,
    poll: async () => ({ status: 'running' }),
    cancel: async id => { cancelled.push(id); return { status: 'cancelled' }; },
  };
  const page = await mountDiagnostics(root, api, { pollInterval: 1000 });
  root.querySelector('[data-field="query"]').value = 'still running';
  root.querySelector('[data-action="search"]').click();
  await new Promise(resolve => setTimeout(resolve, 5));
  page.dispose();
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.deepEqual(cancelled, [9]);
  window.close();
});

test('a CLI started while unmounting is cancelled instead of leaking', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  let finishStart;
  const cancelled = [];
  const api = {
    detect: async () => ({ app: { status: 'ready' }, execution: { status: 'ready' } }),
    start: () => new Promise(resolve => { finishStart = resolve; }),
    cancel: async id => { cancelled.push(id); return { status: 'cancelled' }; },
  };
  const page = await mountDiagnostics(root, api);
  root.querySelector('[data-field="query"]').value = 'slow start';
  root.querySelector('[data-action="search"]').click();
  await new Promise(resolve => setTimeout(resolve, 5));
  page.dispose();
  finishStart(13);
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.deepEqual(cancelled, [13]);
  window.close();
});

test('a failed cancel resets the run and allows a new test search', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  let starts = 0;
  const api = {
    detect: async () => ({ app: { status: 'ready' }, execution: { status: 'ready' } }),
    start: async () => { starts += 1; return starts; },
    poll: async () => ({ status: 'running' }),
    cancel: async () => { throw 'IPC unavailable'; },
  };
  const page = await mountDiagnostics(root, api, { pollInterval: 1000 });
  root.querySelector('[data-field="query"]').value = 'retryable';
  root.querySelector('[data-action="search"]').click();
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(root.querySelector('[data-action="search"]').disabled, true);
  assert.equal(root.querySelector('[data-action="cancel"]').disabled, false);

  root.querySelector('[data-action="cancel"]').click();
  await new Promise(resolve => setTimeout(resolve, 5));
  const cancelError = root.querySelector('[data-execution-error]');
  assert.match(cancelError.textContent, /取消失败，无法取消本次执行。 状态已复位/);
  assert.equal(cancelError.title, 'IPC unavailable', 'raw reason is kept as a tooltip, not shown as UI text');
  assert.equal(root.querySelector('[data-status="execution"]').textContent, '等待测试');
  assert.equal(root.querySelector('[data-action="search"]').disabled, false, 'state is reset after a failed cancel');
  assert.equal(root.querySelector('[data-action="cancel"]').disabled, true);

  root.querySelector('[data-action="search"]').click();
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(starts, 2, 'a new test search can be started');
  page.dispose();
  window.close();
});

test('the backend reason for a rejected start stays visible and retry is possible', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  let attempts = 0;
  const api = {
    detect: async () => ({ app: { status: 'ready' }, execution: { status: 'ready' } }),
    start: async () => { attempts += 1; throw 'A test search is already running'; },
  };
  const page = await mountDiagnostics(root, api);
  root.querySelector('[data-field="query"]').value = 'busy';
  root.querySelector('[data-action="search"]').click();
  await new Promise(resolve => setTimeout(resolve, 5));
  const startError = root.querySelector('[data-execution-error]');
  assert.doesNotMatch(startError.textContent, /already running/, 'no raw English backend text is shown');
  assert.match(startError.textContent, /启动失败/);
  assert.equal(startError.title, 'A test search is already running');
  assert.equal(root.querySelector('[data-action="search"]').disabled, false);
  root.querySelector('[data-action="search"]').click();
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(attempts, 2);
  page.dispose();
  window.close();
});

test('a failed poll shows its backend reason and still allows cancelling', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  const api = {
    detect: async () => ({ app: { status: 'ready' }, execution: { status: 'ready' } }),
    start: async () => 31,
    poll: async () => { throw 'Execution state unavailable'; },
    cancel: async () => ({ status: 'cancelled' }),
  };
  const page = await mountDiagnostics(root, api);
  root.querySelector('[data-field="query"]').value = 'poll failure';
  root.querySelector('[data-action="search"]').click();
  await new Promise(resolve => setTimeout(resolve, 5));
  const pollError = root.querySelector('[data-execution-error]');
  assert.match(pollError.textContent, /无法读取执行状态/);
  assert.equal(pollError.title, 'Execution state unavailable');
  assert.equal(root.querySelector('[data-action="cancel"]').disabled, false);
  page.dispose();
  window.close();
});

test('no executable path can be typed or sent: detect and start take no path', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  const calls = [];
  const api = {
    detect: async (...args) => { calls.push(['detect', args]); return { app: { status: 'ready' }, user: { status: 'ready' }, execution: { status: 'ready', path: 'C:\\Users\\u\\AppData\\Local\\MultiSearch\\cli\\bin\\multi-search.exe' }, managed: true }; },
    start: async (...args) => { calls.push(['start', args]); return 1; },
    poll: async () => ({ status: 'success', payload: {} }),
  };
  const page = await mountDiagnostics(root, api, { pollInterval: 1 });
  assert.equal(root.querySelector('[data-field="path"]'), null, 'the free-form CLI path input is gone');
  assert.match(root.querySelector('[data-status="execution-cli"]').textContent, /受管安装/);
  root.querySelector('[data-field="query"]').value = 'fixture';
  root.querySelector('[data-action="search"]').click();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.deepEqual(calls[0], ['detect', []]);
  const start = calls.find(([name]) => name === 'start');
  assert.equal(start[1].length, 1, 'start receives only search options');
  assert.equal(typeof start[1][0], 'object');
  assert.equal('path' in start[1][0], false);
  page.dispose(); window.close();
});

test('appReady follows the backend execution row, not a stale app or user row', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  let execution = { status: 'ready' };
  const api = { detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' }, restart_required: false, execution, managed: false }) };
  await mountDiagnostics(root, api);
  assert.equal(root.querySelector('[data-action="search"]').disabled, false);
  // The managed install was removed or failed verification: app/user rows still look ready, but
  // the CLI the backend would run is not, so search must be disabled after a refresh.
  execution = { status: 'not_executable', reason: 'denied' };
  root.querySelector('[data-action="refresh"]').click();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(root.querySelector('[data-action="search"]').disabled, true);
  assert.match(root.querySelector('[data-status="execution-cli"]').textContent, /无可用 CLI/);
  execution = { status: 'ready' };
  root.querySelector('[data-action="refresh"]').click();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(root.querySelector('[data-action="search"]').disabled, false);
  window.close();
});

test('a detection payload without an execution row never enables search', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  await mountDiagnostics(root, { detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' } }) });
  assert.equal(root.querySelector('[data-action="search"]').disabled, true);
  window.close();
});
