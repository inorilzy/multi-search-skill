import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountCookies } from '../ui/cookies.js';
import { managementApi } from '../ui/api.js';

const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const MANAGED = '/home/u/.multi-search/twitter-cookies.json';
const view = (overrides = {}) => ({ present: false, mode: 'file', path: MANAGED, configured_path: null, ...overrides });
const coded = (code, message = '') => JSON.stringify({ code, message });

// Every test closes its window even when an assertion fails, so a failure reports instead of hanging.
async function setup(t, overrides = {}) {
  const window = new Window();
  t.after(() => window.close());
  const root = window.document.createElement('div');
  window.document.body.append(root);
  const calls = [];
  const mounted = await mountCookies(root, {
    cookieStatus: async () => { calls.push('status'); return view(); },
    cookieImport: async (...args) => { calls.push(['import', ...args]); return view({ present: true, configured_path: MANAGED }); },
    cookieDelete: async (...args) => { calls.push(['delete', ...args]); return view(); },
    ...overrides,
  });
  return { window, root, calls, mounted, q: selector => root.querySelector(selector) };
}

test('cookie page loads status only and requires confirmation before import', async t => {
  const ctx = await setup(t);
  assert.deepEqual(ctx.calls, ['status']);
  assert.match(ctx.root.textContent, /明文/);
  assert.match(ctx.q('.eyebrow').textContent, /^07 \/ /);
  assert.equal(ctx.q('h1').getAttribute('tabindex'), '-1');
  ctx.q('[data-cookie-path]').value = '<img src=x>.json';
  const trigger = ctx.q('[data-cookie-import]');
  trigger.focus();
  trigger.click();
  assert.equal(ctx.root.querySelector('img'), null);
  assert.match(ctx.q('[data-cookie-confirm]').textContent, /<img src=x>/);
  assert.equal(ctx.q('.inline-confirm').getAttribute('role'), 'group');
  assert.equal(ctx.window.document.activeElement, ctx.q('[data-cookie-confirm-cancel]'), 'the safe choice has focus');
  ctx.q('[data-cookie-confirm-cancel]').click();
  assert.deepEqual(ctx.calls, ['status']);
  assert.equal(ctx.window.document.activeElement, trigger, 'focus returns to the trigger');
  ctx.q('[data-cookie-import]').click();
  ctx.q('[data-cookie-confirm-yes]').click();
  await flush();
  assert.deepEqual(ctx.calls, ['status', ['import', '<img src=x>.json', true]]);
  assert.match(ctx.q('[data-cookie-status]').textContent, /已导入：\/home\/u\/\.multi-search\/twitter-cookies\.json/);
  assert.match(ctx.q('[data-cookie-configured]').textContent, /设置中的 Cookie 文件：\/home\/u\/\.multi-search\/twitter-cookies\.json/);
  assert.equal(ctx.q('[data-cookie-path]').value, '');
});

test('Escape cancels the confirmation without mutating anything', async t => {
  const ctx = await setup(t, { cookieStatus: async () => view({ present: true }) });
  const trigger = ctx.q('[data-cookie-delete]');
  trigger.focus();
  trigger.click();
  const panel = ctx.q('.inline-confirm');
  panel.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(ctx.q('.inline-confirm'), null);
  assert.equal(ctx.window.document.activeElement, trigger);
  assert.deepEqual(ctx.calls, []);
});

test('cookie delete needs confirmation and then reports the copy as gone', async t => {
  const ctx = await setup(t, { cookieStatus: async () => view({ present: true, configured_path: MANAGED }) });
  ctx.q('[data-cookie-delete]').click();
  ctx.q('[data-cookie-confirm-cancel]').click();
  assert.deepEqual(ctx.calls, []);
  ctx.q('[data-cookie-delete]').click();
  ctx.q('[data-cookie-confirm-yes]').click();
  await flush();
  assert.deepEqual(ctx.calls, [['delete', true]]);
  assert.match(ctx.q('[data-cookie-status]').textContent, /尚未导入 Cookie/);
  assert.match(ctx.q('[data-cookie-configured]').textContent, /设置中没有 Cookie 文件路径/);
  assert.equal(ctx.q('[data-cookie-delete]').disabled, true);
});

test('failed import preserves path/status and shows normalized text, never markup or English', async t => {
  const ctx = await setup(t, { cookieImport: async () => { throw '<img src=x> import failed'; } });
  ctx.q('[data-cookie-path]').value = 'cookies.json';
  ctx.q('[data-cookie-import]').click();
  ctx.q('[data-cookie-confirm-yes]').click();
  await flush();
  const error = ctx.q('[data-cookie-error]');
  assert.equal(ctx.q('img'), null);
  assert.match(error.textContent, /导入失败/);
  assert.doesNotMatch(error.textContent, /import failed/, 'an English backend reason is not shown');
  assert.match(error.title, /<img src=x> import failed/, 'the raw reason stays available for support');
  assert.equal(ctx.q('[data-cookie-path]').value, 'cookies.json');
  assert.match(ctx.q('[data-cookie-status]').textContent, /尚未导入 Cookie/);
  assert.deepEqual(ctx.calls, ['status']);
});

test('a coded backend failure shows its mapped Chinese message', async t => {
  const ctx = await setup(t, { cookieImport: async () => { throw coded('cookie_import_failed', 'Cookie import worker failed'); } });
  ctx.q('[data-cookie-path]').value = 'cookies.json';
  ctx.q('[data-cookie-import]').click();
  ctx.q('[data-cookie-confirm-yes]').click();
  await flush();
  assert.match(ctx.q('[data-cookie-error]').textContent, /Cookie 导入失败，原文件与已导入的 Cookie 都没有改动/);
});

test('every platform can import; a setting that points elsewhere is shown as is', async t => {
  const ctx = await setup(t, { cookieStatus: async () => view({ configured_path: 'D:/secure/cookies.json' }) });
  assert.equal(ctx.q('[data-cookie-import]').disabled, false);
  assert.equal(ctx.q('[data-cookie-path]').disabled, false);
  assert.equal(ctx.q('[data-cookie-delete]').disabled, true, 'nothing imported yet');
  assert.match(ctx.q('[data-cookie-configured]').textContent, /D:\/secure\/cookies\.json/);
  assert.match(ctx.root.textContent, /~\/\.multi-search\/twitter-cookies\.json（仅当前用户可读写）/);
  assert.doesNotMatch(ctx.root.textContent, /DPAPI|managed|托管/);
});

test('status failure fails closed and refresh can recover', async t => {
  let count = 0;
  const ctx = await setup(t, { cookieStatus: async () => { if (!count++) throw new Error('unavailable'); return view(); } });
  assert.equal(ctx.q('[data-cookie-import]').disabled, true);
  assert.match(ctx.q('[data-cookie-error]').textContent, /无法读取 Cookie 状态/);
  assert.match(ctx.q('[data-cookie-status]').textContent, /Cookie 状态未知/);
  ctx.q('[data-cookie-refresh]').click();
  await flush();
  assert.equal(ctx.q('[data-cookie-import]').disabled, false);
  assert.equal(ctx.q('[data-cookie-error]').textContent, '');
});

test('pending import marks the page busy, ignores duplicate confirmation and late responses after dispose', async t => {
  let finish;
  let count = 0;
  const ctx = await setup(t, { cookieImport: () => { count++; return new Promise(resolve => { finish = resolve; }); } });
  ctx.q('[data-cookie-path]').value = 'cookies.json';
  ctx.q('[data-cookie-import]').click();
  const yes = ctx.q('[data-cookie-confirm-yes]');
  yes.click();
  assert.equal(ctx.q('.page-content').getAttribute('aria-busy'), 'true', 'the page container announces busy');
  assert.equal(ctx.q('[data-cookie-refresh]').disabled, true);
  yes.click();
  assert.equal(count, 1);
  ctx.mounted.dispose();
  finish(view({ present: true }));
  await flush();
  assert.equal(ctx.root.textContent, '');
});

test('cookie adapters expose only status and confirmed mutation contracts', async () => {
  const calls = [];
  const api = managementApi(async (cmd, args) => { calls.push([cmd, args]); return view(); });
  await api.cookieStatus();
  await assert.rejects(api.cookieImport('cookies.json', false));
  await assert.rejects(api.cookieDelete(false));
  await assert.rejects(api.cookieImport('', true));
  await api.cookieImport('cookies.json', true);
  await api.cookieDelete(true);
  assert.deepEqual(calls, [['cookie_status', undefined], ['cookie_import', { path: 'cookies.json', confirmed: true }], ['cookie_delete', { confirmed: true }]]);
  assert.equal(api.cookieReveal, undefined);
  const bad = managementApi(async () => ({ value: 'do-not-display' }));
  await assert.rejects(bad.cookieStatus(), error => {
    assert.equal(error.code, 'INVALID_PAYLOAD');
    assert.doesNotMatch(error.message, /do-not-display/);
    assert.match(error.message, /[\u4e00-\u9fff]/, 'the visible message is Chinese');
    return true;
  });
});

test('failed deletion keeps the imported state and shows the failure', async t => {
  const ctx = await setup(t, {
    cookieStatus: async () => view({ present: true }),
    cookieDelete: async () => { throw new Error('delete failed'); },
  });
  ctx.q('[data-cookie-delete]').click();
  ctx.q('[data-cookie-confirm-yes]').click();
  await flush();
  assert.match(ctx.q('[data-cookie-status]').textContent, /已导入/);
  assert.match(ctx.q('[data-cookie-error]').textContent, /删除失败/);
  assert.deepEqual(ctx.calls, []);
});
