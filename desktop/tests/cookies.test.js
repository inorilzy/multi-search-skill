import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountCookies } from '../ui/cookies.js';
import { managementApi } from '../ui/api.js';

const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const view = (overrides = {}) => ({ present: false, mode: 'file', supported: true, ...overrides });
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
    cookieImport: async (...args) => { calls.push(['import', ...args]); return view({ present: true, mode: 'managed' }); },
    cookieDelete: async (...args) => { calls.push(['delete', ...args]); return view({ mode: 'managed' }); },
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
  assert.match(ctx.q('[data-cookie-status]').textContent, /managed.*已有/);
  assert.equal(ctx.q('[data-cookie-path]').value, '');
});

test('Escape cancels the confirmation without mutating anything', async t => {
  const ctx = await setup(t, { cookieStatus: async () => view({ present: true, mode: 'managed' }) });
  const trigger = ctx.q('[data-cookie-delete]');
  trigger.focus();
  trigger.click();
  const panel = ctx.q('.inline-confirm');
  panel.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(ctx.q('.inline-confirm'), null);
  assert.equal(ctx.window.document.activeElement, trigger);
  assert.deepEqual(ctx.calls, []);
});

test('cookie delete cancellation and confirmed delete retain managed mode with no fallback', async t => {
  const ctx = await setup(t, { cookieStatus: async () => view({ present: true, mode: 'managed' }) });
  ctx.q('[data-cookie-delete]').click();
  ctx.q('[data-cookie-confirm-cancel]').click();
  assert.deepEqual(ctx.calls, []);
  ctx.q('[data-cookie-delete]').click();
  ctx.q('[data-cookie-confirm-yes]').click();
  await flush();
  assert.deepEqual(ctx.calls, [['delete', true]]);
  assert.match(ctx.q('[data-cookie-status]').textContent, /managed.*没有/);
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
  assert.match(ctx.q('[data-cookie-status]').textContent, /file/);
  assert.deepEqual(ctx.calls, ['status']);
});

test('a coded backend failure shows its mapped Chinese message', async t => {
  const ctx = await setup(t, { cookieImport: async () => { throw coded('cookie_import_failed', 'Cookie import worker failed'); } });
  ctx.q('[data-cookie-path]').value = 'cookies.json';
  ctx.q('[data-cookie-import]').click();
  ctx.q('[data-cookie-confirm-yes]').click();
  await flush();
  assert.match(ctx.q('[data-cookie-error]').textContent, /Cookie 导入失败，原文件与已有的托管 Cookie 都没有改动/);
});

test('unsupported platform disables encrypted mutations but explains explicit file compatibility', async t => {
  const ctx = await setup(t, { cookieStatus: async () => view({ supported: false }) });
  assert.equal(ctx.q('[data-cookie-import]').disabled, true);
  assert.equal(ctx.q('[data-cookie-delete]').disabled, true);
  const text = ctx.q('[data-cookie-status]').textContent;
  assert.match(text, /当前平台不支持加密托管/);
  assert.match(text, /仅支持 Windows 当前用户 DPAPI/);
  assert.match(text, /文件兼容模式（file）/);
  assert.doesNotMatch(text, /Linux/, 'non-Windows platforms are not described as Linux');
  assert.equal(ctx.q('[data-cookie-refresh]').disabled, false, 'status refresh stays usable');
});

test('unsupported platform keeps every managed/file mode combination without switching or reading content', async t => {
  for (const mode of ['managed', 'file']) {
    for (const present of [true, false]) {
      const ctx = await setup(t, { cookieStatus: async () => view({ supported: false, mode, present }) });
      const text = ctx.q('[data-cookie-status]').textContent;
      assert.match(text, new RegExp(`${mode === 'managed' ? '加密托管' : '文件兼容'}（${mode}）`));
      assert.match(text, /仅支持 Windows 当前用户 DPAPI/);
      assert.equal(ctx.q('[data-cookie-import]').disabled, true, `${mode}/${present}: import stays disabled`);
      assert.equal(ctx.q('[data-cookie-delete]').disabled, true, `${mode}/${present}: delete stays disabled`);
      assert.equal(ctx.q('[data-cookie-path]').disabled, true, `${mode}/${present}: path input stays disabled`);
      assert.deepEqual(ctx.calls, [], `${mode}/${present}: no import or delete was sent`);
    }
  }
});

test('status failure fails closed and refresh can recover', async t => {
  let count = 0;
  const ctx = await setup(t, { cookieStatus: async () => { if (!count++) throw new Error('unavailable'); return view(); } });
  assert.equal(ctx.q('[data-cookie-import]').disabled, true);
  assert.match(ctx.q('[data-cookie-error]').textContent, /无法读取 Cookie 托管状态/);
  assert.match(ctx.q('[data-cookie-status]').textContent, /不会自动切换模式/);
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
  finish(view({ mode: 'managed', present: true }));
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

test('failed managed deletion never switches mode or falls back to file', async t => {
  const ctx = await setup(t, {
    cookieStatus: async () => view({ present: true, mode: 'managed' }),
    cookieDelete: async () => { throw new Error('delete failed'); },
  });
  ctx.q('[data-cookie-delete]').click();
  ctx.q('[data-cookie-confirm-yes]').click();
  await flush();
  assert.match(ctx.q('[data-cookie-status]').textContent, /managed.*已有/);
  assert.match(ctx.q('[data-cookie-error]').textContent, /删除失败，仍保持托管模式/);
  assert.deepEqual(ctx.calls, []);
});
