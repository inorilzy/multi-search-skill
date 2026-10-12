import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountDiagnostics } from '../ui/diagnostics.js';

test('overview distinguishes app invocation from user command discovery', async () => {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  const api = { detect: async () => ({ app: { status: 'ready', path: 'C:\\fixture\\multi-search.exe', version: '0.4.0', reason: '' }, user: { status: 'missing', path: null, version: null, reason: 'not on user PATH' }, restart_required: false }) };
  await mountDiagnostics(root, api);
  assert.match(root.textContent, /0\.4\.0/);
  assert.match(root.textContent, /C:\\fixture\\multi-search.exe/);
  assert.equal(root.querySelector('[data-status="app"]').textContent, '可调用');
  assert.equal(root.querySelector('[data-status="user"]').textContent, '未发现');
  assert.match(root.textContent, /not on user PATH/);
  assert.match(root.textContent, /终端/);
  window.close();
});

test('test search reflects partial execution and renders provider text without HTML', async () => {
  const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root);
  const api = {
    detect: async () => ({ app: { status: 'ready', version: '0.4.0', path: 'C:\\multi-search.exe' }, user: { status: 'ready' }, restart_required: false }),
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
  const api = { detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' } }), start: async () => 1, poll: async () => ({ status: 'failed', error: 'provider unavailable [REDACTED]', payload: { errors: [{ source: 'brave' }] } }) };
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
  const api = { detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' } }), start: async () => 7, poll: () => new Promise(resolve => { finishPoll = resolve; }), cancel: async () => ({ status: 'cancelled' }) };
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
  const api = { detect: async () => ({ app: { status: 'ready' }, user: { status: 'missing' } }), start: async () => 42, poll: async () => ({ status: 'running' }), cancel: async id => { cancelled = id; return { status: 'cancelled' }; } };
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
