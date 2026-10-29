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

test('a cancel click while start is pending gives feedback and cancels the returned execution first', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  let resolveStart;
  const calls = [];
  const api = {
    detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' }, execution: { status: 'ready' } }),
    start: () => new Promise(resolve => { resolveStart = resolve; }),
    poll: async id => { calls.push(['poll', id]); return { status: 'running' }; },
    cancel: async id => { calls.push(['cancel', id]); return { status: 'cancelled' }; },
  };
  const page = await mountDiagnostics(root, api, { pollInterval: 10000 });
  root.querySelector('[data-field="query"]').value = 'deferred start';
  root.querySelector('[data-action="search"]').click();
  const cancel = root.querySelector('[data-action="cancel"]');
  assert.equal(cancel.disabled, false);
  cancel.click(); cancel.click();
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(root.querySelector('[data-status="execution"]').textContent, '等待启动完成后取消');
  assert.equal(cancel.disabled, true);
  assert.equal(root.querySelector('[data-action="search"]').disabled, true);
  assert.deepEqual(calls, [], 'no cancel is sent before an execution id exists');
  resolveStart(77);
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.deepEqual(calls, [['cancel', 77]], 'the single pending click cancels only the returned id, with no poll before it');
  assert.equal(root.querySelector('[data-status="execution"]').textContent, '已取消');
  assert.equal(root.querySelector('[data-action="search"]').disabled, false);
  assert.equal(cancel.disabled, true);
  page.dispose(); window.close();
});

test('a start failure after a cancel click shows the real start error and sends no cancel', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  let rejectStart;
  const cancelled = [];
  const api = {
    detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' }, execution: { status: 'ready' } }),
    start: () => new Promise((_, reject) => { rejectStart = reject; }),
    cancel: async id => { cancelled.push(id); return { status: 'cancelled' }; },
  };
  const page = await mountDiagnostics(root, api);
  root.querySelector('[data-field="query"]').value = 'fails to start';
  root.querySelector('[data-action="search"]').click();
  await new Promise(resolve => setTimeout(resolve, 5));
  root.querySelector('[data-action="cancel"]').click();
  rejectStart('spawn failed');
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.deepEqual(cancelled, [], 'no cancel without an execution id');
  assert.equal(root.querySelector('[data-status="execution"]').textContent, '执行失败');
  assert.notEqual(root.querySelector('[data-status="execution"]').textContent, '已取消');
  assert.match(root.querySelector('[data-execution-error]').textContent, /启动失败/);
  assert.equal(root.querySelector('[data-action="search"]').disabled, false, 'retry is possible');
  page.dispose(); window.close();
});

test('a pending cancel that fails after the id arrives resets the run and allows a new search', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  let resolveStart; let starts = 0;
  const api = {
    detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' }, execution: { status: 'ready' } }),
    start: () => { starts += 1; return new Promise(resolve => { resolveStart = resolve; }); },
    cancel: async () => { throw 'IPC unavailable'; },
  };
  const page = await mountDiagnostics(root, api);
  root.querySelector('[data-field="query"]').value = 'cancel fails';
  root.querySelector('[data-action="search"]').click();
  await new Promise(resolve => setTimeout(resolve, 5));
  root.querySelector('[data-action="cancel"]').click();
  resolveStart(5);
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.match(root.querySelector('[data-execution-error]').textContent, /取消失败，无法取消本次执行。 状态已复位/);
  assert.equal(root.querySelector('[data-action="search"]').disabled, false);
  root.querySelector('[data-action="search"]').click();
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(starts, 2, 'a new test search starts after the failed pending cancel');
  page.dispose(); window.close();
});

const tick = (ms = 5) => new Promise(resolve => setTimeout(resolve, ms));

test('repeated clicks and direct form submits while start is pending issue exactly one start', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  const starts = []; let resolveStart;
  const api = {
    detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' }, execution: { status: 'ready' } }),
    start: options => { starts.push(options); return new Promise(resolve => { resolveStart = resolve; }); },
    poll: async () => ({ status: 'running' }),
    cancel: async () => ({ status: 'cancelled' }),
  };
  const page = await mountDiagnostics(root, api, { pollInterval: 10000 });
  root.querySelector('[data-field="query"]').value = 'double';
  const form = root.querySelector('[data-search-form]');
  const search = root.querySelector('[data-action="search"]');
  const query = root.querySelector('[data-field="query"]');
  search.click(); search.click();
  assert.equal(search.disabled, true, 'the button is visibly disabled while the start is pending');
  for (let i = 0; i < 3; i += 1) {
    query.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    query.dispatchEvent(new window.KeyboardEvent('keyup', { key: 'Enter', bubbles: true, cancelable: true }));
    form.dispatchEvent(new window.Event('submit', { cancelable: true }));
  }
  await tick();
  assert.equal(starts.length, 1, 'only one start request leaves the page');
  resolveStart(101);
  await tick();
  assert.equal(starts.length, 1);
  page.dispose(); window.close();
});

test('repeated cancel clicks while cancel is in flight send one cancel, and none after success', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  const cancels = []; const starts = []; let resolveCancel;
  const api = {
    detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' }, execution: { status: 'ready' } }),
    start: options => { starts.push(options); return 55; },
    poll: async () => ({ status: 'running' }),
    cancel: id => { cancels.push(id); return new Promise(resolve => { resolveCancel = resolve; }); },
  };
  const page = await mountDiagnostics(root, api, { pollInterval: 10000 });
  root.querySelector('[data-field="query"]').value = 'cancel-once';
  root.querySelector('[data-action="search"]').click();
  await tick();
  const cancel = root.querySelector('[data-action="cancel"]');
  const form = root.querySelector('[data-search-form]');
  cancel.click(); cancel.click();
  root.querySelector('[data-action="cancel"]').dispatchEvent(new window.Event('click'));
  form.dispatchEvent(new window.Event('submit', { cancelable: true }));
  await tick();
  assert.deepEqual(cancels, [55], 'in-flight cancel is not repeated');
  assert.equal(starts.length, 1, 'a pending cancel cannot be raced by a new start');
  resolveCancel({ status: 'cancelled' });
  await tick();
  assert.equal(root.querySelector('[data-status="execution"]').textContent, '已取消');
  cancel.click(); cancel.click();
  await tick();
  assert.deepEqual(cancels, [55], 'no cancel after a successful cancel');
  assert.equal(starts.length, 1, 'the cancelled round issued exactly one public start request');
  assert.deepEqual(Object.keys(starts[0]).sort(), ['query', 'route', 'sources', 'timeout'], 'start carries only the documented page fields');
  assert.equal(starts[0].query, 'cancel-once');
  assert.equal(typeof starts[0].timeout, 'number', 'timeout is sent as a number, not the raw field text');
  assert.ok(Array.isArray(starts[0].sources), 'sources are sent as the parsed list');
  assert.equal(root.querySelector('[data-action="search"]').disabled, false, 'a new search is allowed after cancel');
  root.querySelector('[data-action="search"]').click();
  await tick();
  assert.equal(starts.length, 2, 'a new round may start after the cancel succeeded');
  page.dispose(); window.close();
});

test('a pending start cancelled by repeated clicks sends one cancel for the returned id only', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  const cancels = []; let resolveStart; const starts = [];
  const api = {
    detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' }, execution: { status: 'ready' } }),
    start: () => { starts.push(1); return new Promise(resolve => { resolveStart = resolve; }); },
    poll: async () => ({ status: 'running' }),
    cancel: async id => { cancels.push(id); return { status: 'cancelled' }; },
  };
  const page = await mountDiagnostics(root, api, { pollInterval: 10000 });
  root.querySelector('[data-field="query"]').value = 'pending-repeat';
  root.querySelector('[data-action="search"]').click();
  const form = root.querySelector('[data-search-form]');
  form.dispatchEvent(new window.Event('submit', { cancelable: true }));
  const cancel = root.querySelector('[data-action="cancel"]');
  cancel.click(); cancel.click(); cancel.click();
  resolveStart(88);
  await tick();
  assert.equal(starts.length, 1);
  assert.deepEqual(cancels, [88]);
  page.dispose(); window.close();
});

test('a failed start is retryable and the retry is a separate, single request', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  const starts = [];
  const api = {
    detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' }, execution: { status: 'ready' } }),
    start: async options => { starts.push(options); if (starts.length === 1) throw 'boom'; return 66; },
    poll: async () => ({ status: 'running' }),
    cancel: async () => ({ status: 'cancelled' }),
  };
  const page = await mountDiagnostics(root, api, { pollInterval: 10000 });
  root.querySelector('[data-field="query"]').value = 'retry';
  const form = root.querySelector('[data-search-form]');
  root.querySelector('[data-action="search"]').click();
  await tick();
  assert.equal(starts.length, 1);
  assert.equal(root.querySelector('[data-action="search"]').disabled, false, 'failed start unlocks search');
  root.querySelector('[data-action="search"]').click(); form.dispatchEvent(new window.Event('submit', { cancelable: true }));
  await tick();
  assert.equal(starts.length, 2, 'explicit retry starts exactly once');
  assert.equal(root.querySelector('[data-status="execution"]').textContent, '正在执行');
  page.dispose(); window.close();
});

test('a run already polling cannot be re-started by submit or repeated clicks, and double dispose cancels once', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  const starts = []; const cancels = [];
  const api = {
    detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' }, execution: { status: 'ready' } }),
    start: options => { starts.push(options); return 777; },
    poll: async id => ({ status: 'running' }),
    cancel: async id => { cancels.push(id); return { status: 'cancelled' }; },
  };
  const page = await mountDiagnostics(root, api, { pollInterval: 10000 });
  root.querySelector('[data-field="query"]').value = 'once-only';
  root.querySelector('[data-action="search"]').click();
  await tick();
  const form = root.querySelector('[data-search-form]');
  assert.equal(starts.length, 1, 'the first click started the round');
  form.dispatchEvent(new window.Event('submit', { cancelable: true }));
  form.dispatchEvent(new window.Event('submit', { cancelable: true }));
  root.querySelector('[data-action="search"]').click();
  await tick();
  assert.equal(starts.length, 1, 'a live execution cannot be started again, even bypassing the disabled button');
  assert.deepEqual(cancels, [], 'no cancel from a blocked start');
  page.dispose();
  page.dispose();
  await tick();
  assert.deepEqual(cancels, [777], 'leaving the page cancels the current execution exactly once');
  assert.equal(starts.length, 1);
  window.close();
});
