import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountCookies } from '../ui/cookies.js';
import { managementApi } from '../ui/api.js';
const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const view = (overrides = {}) => ({ present: false, mode: 'file', supported: true, ...overrides });
async function setup(overrides = {}) {
  const window = new Window(), root = window.document.createElement('div'); window.document.body.append(root);
  const calls = [];
  const mounted = await mountCookies(root, { cookieStatus: async () => { calls.push('status'); return view(); }, cookieImport: async (...args) => { calls.push(['import', ...args]); return view({ present: true, mode: 'managed' }); }, cookieDelete: async (...args) => { calls.push(['delete', ...args]); return view({ mode: 'managed' }); }, ...overrides });
  return { window, root, calls, mounted, q: selector => root.querySelector(selector) };
}
test('cookie page loads status only and requires confirmation before import', async () => {
  const ctx = await setup(); assert.deepEqual(ctx.calls, ['status']); assert.match(ctx.root.textContent, /明文/);
  ctx.q('[data-cookie-path]').value = '<img src=x>.json'; ctx.q('[data-cookie-import]').click();
  assert.equal(ctx.root.querySelector('img'), null); assert.match(ctx.q('[data-cookie-confirm]').textContent, /<img src=x>/);
  assert.equal(ctx.window.document.activeElement, ctx.q('[data-cookie-confirm-yes]'));
  ctx.q('[data-cookie-confirm-cancel]').click(); assert.deepEqual(ctx.calls, ['status']);
  ctx.q('[data-cookie-import]').click(); ctx.q('[data-cookie-confirm-yes]').click(); await flush();
  assert.deepEqual(ctx.calls, ['status', ['import', '<img src=x>.json', true]]);
  assert.match(ctx.q('[data-cookie-status]').textContent, /managed.*已有/); assert.equal(ctx.q('[data-cookie-path]').value, '');
  ctx.window.close();
});
test('cookie delete cancellation and confirmed delete retain managed mode with no fallback', async () => {
  const ctx = await setup({ cookieStatus: async () => view({ present: true, mode: 'managed' }) });
  ctx.q('[data-cookie-delete]').click(); ctx.q('[data-cookie-confirm-cancel]').click(); assert.deepEqual(ctx.calls, []);
  ctx.q('[data-cookie-delete]').click(); ctx.q('[data-cookie-confirm-yes]').click(); await flush();
  assert.deepEqual(ctx.calls, [['delete', true]]); assert.match(ctx.q('[data-cookie-status]').textContent, /managed.*没有/);
  assert.equal(ctx.q('[data-cookie-delete]').disabled, true); ctx.window.close();
});
test('failed import preserves path/status and displays text without file fallback', async () => {
  const ctx = await setup({ cookieImport: async () => { throw '<img src=x> import failed'; } });
  ctx.q('[data-cookie-path]').value = 'cookies.json'; ctx.q('[data-cookie-import]').click(); ctx.q('[data-cookie-confirm-yes]').click(); await flush();
  assert.equal(ctx.q('img'), null); assert.match(ctx.q('[data-cookie-error]').textContent, /<img src=x>/); assert.equal(ctx.q('[data-cookie-path]').value, 'cookies.json');
  assert.match(ctx.q('[data-cookie-status]').textContent, /file/); assert.deepEqual(ctx.calls, ['status']); ctx.window.close();
});
test('unsupported platform disables encrypted mutations but explains explicit file compatibility', async () => {
  const ctx = await setup({ cookieStatus: async () => view({ supported: false }) });
  assert.equal(ctx.q('[data-cookie-import]').disabled, true); assert.equal(ctx.q('[data-cookie-delete]').disabled, true);
  assert.match(ctx.q('[data-cookie-status]').textContent, /Linux.*文件兼容/); ctx.window.close();
});
test('status failure fails closed and refresh can recover', async () => {
  let count = 0;
  const ctx = await setup({ cookieStatus: async () => { if (!count++) throw new Error('unavailable'); return view(); } });
  assert.equal(ctx.q('[data-cookie-import]').disabled, true); assert.match(ctx.q('[data-cookie-error]').textContent, /unavailable/);
  ctx.q('[data-cookie-refresh]').click(); await flush(); assert.equal(ctx.q('[data-cookie-import]').disabled, false); ctx.window.close();
});
test('pending import ignores duplicate confirmation and late response after dispose', async () => {
  let finish, count = 0;
  const ctx = await setup({ cookieImport: () => { count++; return new Promise(resolve => { finish = resolve; }); } });
  ctx.q('[data-cookie-path]').value = 'cookies.json'; ctx.q('[data-cookie-import]').click(); const yes = ctx.q('[data-cookie-confirm-yes]'); yes.click(); yes.click();
  assert.equal(count, 1); ctx.mounted.dispose(); finish(view({ mode: 'managed', present: true })); await flush(); assert.equal(ctx.root.textContent, ''); ctx.window.close();
});
test('cookie adapters expose only status and confirmed mutation contracts', async () => {
  const calls = [], api = managementApi(async (cmd, args) => { calls.push([cmd, args]); return view(); });
  await api.cookieStatus();
  await assert.rejects(api.cookieImport('cookies.json', false)); await assert.rejects(api.cookieDelete(false)); await assert.rejects(api.cookieImport('', true));
  await api.cookieImport('cookies.json', true); await api.cookieDelete(true);
  assert.deepEqual(calls, [['cookie_status', undefined], ['cookie_import', { path: 'cookies.json', confirmed: true }], ['cookie_delete', { confirmed: true }]]);
  assert.equal(api.cookieReveal, undefined);
  const bad = managementApi(async () => ({ value: 'do-not-display' })); await assert.rejects(bad.cookieStatus(), error => error.code === 'INVALID_PAYLOAD');
});


test('failed managed deletion never switches mode or falls back to file', async () => {
  const ctx = await setup({ cookieStatus: async () => view({ present: true, mode: 'managed' }), cookieDelete: async () => { throw new Error('delete failed'); } });
  ctx.q('[data-cookie-delete]').click(); ctx.q('[data-cookie-confirm-yes]').click(); await flush();
  assert.match(ctx.q('[data-cookie-status]').textContent, /managed.*已有/); assert.match(ctx.q('[data-cookie-error]').textContent, /delete failed/);
  assert.deepEqual(ctx.calls, []); ctx.window.close();
});
