import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { withProviders } from './providers.js';
import { mountCredentials, SOURCES } from '../ui/credentials.js';
import { managementApi } from '../ui/api.js';
const KEY = 'synthetic-ui-key-0001';
const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const status = (saved = false, extra = {}) => ({ store: { state: saved ? 'present' : 'absent', saved_at: saved ? 1 : null, error: '' }, effective_source: saved ? 'sqlite' : 'none', key_application_available: false, ...extra });
function setup() { const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root); return { window, root }; }
const submit = ({ window, root }) => root.querySelector('form').dispatchEvent(new window.Event('submit', { cancelable: true }));
function api(overrides = {}) { return withProviders({ credentialStatus: async () => status(), credentialRead: async () => ({ value: '' }), ...overrides }); }

test('expanded editor fetches saved values through single-source command and is visible without reveal', async () => {
  const ctx = setup(); const seen = [];
  await mountCredentials(ctx.root, api({ credentialStatus: async () => status(true), credentialRead: async source => { seen.push(source); return { value: KEY + '\nsecond-key' }; } }));
  const field = ctx.root.querySelector('[data-field="key"]');
  assert.equal(field.tagName, 'TEXTAREA'); assert.equal(field.value, KEY + '\nsecond-key'); assert.deepEqual(seen, ['tavily']);
  assert.equal(ctx.root.querySelector('[type="password"]'), null); assert.equal(ctx.root.querySelector('[data-action="reveal"]'), null);
  assert.ok(!ctx.root.innerHTML.includes(KEY), 'readback goes through .value, not HTML interpolation'); ctx.window.close();
});
test('all keyed sources query their own overview and read command', async () => {
  assert.equal(SOURCES.filter(s => s.keyed).length, 8);
  for (const entry of SOURCES.filter(s => s.keyed)) {
    const ctx = setup(), calls = [];
    await mountCredentials(ctx.root, api({ credentialStatus: async s => { calls.push(['status', s]); return status(); }, credentialRead: async s => { calls.push(['read', s]); return { value: '' }; } }), { source: entry.source });
    assert.deepEqual(calls, [['status', entry.source], ['read', entry.source]]); assert.ok(ctx.root.textContent.includes(entry.label)); ctx.window.close();
  }
});
test('save preserves normalized multi-key value, reads persisted value and never tests automatically', async () => {
  const ctx = setup(); let value = '', saved = null, tests = 0;
  await mountCredentials(ctx.root, api({ credentialRead: async () => ({ value }), credentialSave: async (source, key) => { saved = { source, key }; value = key.trim(); return status(true); }, credentialTest: async () => { tests++; } }));
  ctx.root.querySelector('textarea').value = '  ' + KEY + '\nsecond-key  '; submit(ctx); await flush();
  assert.deepEqual(saved, { source: 'tavily', key: '  ' + KEY + '\nsecond-key  ' }); assert.equal(ctx.root.querySelector('textarea').value, KEY + '\nsecond-key'); assert.equal(tests, 0);
  assert.equal(ctx.root.querySelector('[data-status="source"]').textContent, 'SQLite / DPAPI'); assert.match(ctx.root.querySelector('[data-info="test"]').textContent, /已保存.*尚未测试/); ctx.window.close();
});
test('save failure retains edited value and does not show saved success', async () => {
  const ctx = setup(); await mountCredentials(ctx.root, api({ credentialSave: async () => { throw '数据库拒绝，未保存'; } }));
  ctx.root.querySelector('textarea').value = KEY; submit(ctx); await flush();
  assert.equal(ctx.root.querySelector('textarea').value, KEY); assert.match(ctx.root.querySelector('[data-info="error"]').textContent, /未保存/); assert.equal(ctx.root.querySelector('[data-status="store"]').textContent, '未保存'); ctx.window.close();
});
test('save followed by remount returns persisted value', async () => {
  const ctx = setup(); let value = '';
  const backend = api({ credentialRead: async () => ({ value }), credentialSave: async (_, key) => { value = key; return status(true); } });
  const mounted = await mountCredentials(ctx.root, backend); ctx.root.querySelector('textarea').value = KEY; submit(ctx); await flush(); mounted.dispose();
  await mountCredentials(ctx.root, backend); assert.equal(ctx.root.querySelector('textarea').value, KEY); ctx.window.close();
});
test('delete requires confirmation, cancel writes nothing, confirmed delete clears without reviving old sources', async () => {
  const ctx = setup(); let deletes = 0;
  await mountCredentials(ctx.root, api({ credentialStatus: async () => status(true), credentialRead: async () => ({ value: KEY }), credentialDelete: async () => { deletes++; return status(); } }));
  ctx.root.querySelector('[data-action="delete"]').click(); assert.equal(deletes, 0); assert.match(ctx.root.querySelector('[data-confirm]').textContent, /不会自动恢复/);
  ctx.root.querySelector('[data-action="cancel-delete"]').click(); assert.equal(deletes, 0); assert.equal(ctx.root.querySelector('textarea').value, KEY);
  ctx.root.querySelector('[data-action="delete"]').click(); ctx.root.querySelector('[data-action="confirm-delete"]').click(); await flush();
  assert.equal(deletes, 1); assert.equal(ctx.root.querySelector('textarea').value, ''); assert.equal(ctx.root.querySelector('[data-status="source"]').textContent, '未配置'); assert.match(ctx.root.querySelector('[data-info="test"]').textContent, /没有可用/); ctx.window.close();
});
test('failed delete keeps value and visible failure', async () => {
  const ctx = setup(); await mountCredentials(ctx.root, api({ credentialRead: async () => ({ value: KEY }), credentialDelete: async () => { throw '未删除'; } }));
  ctx.root.querySelector('[data-action="delete"]').click(); ctx.root.querySelector('[data-action="confirm-delete"]').click(); await flush();
  assert.equal(ctx.root.querySelector('textarea').value, KEY); assert.match(ctx.root.querySelector('[data-info="error"]').textContent, /未删除/); ctx.window.close();
});
test('editing, saving, deleting and refreshed changes invalidate successful result', async () => {
  const ctx = setup(); let view = status(true), value = KEY;
  await mountCredentials(ctx.root, api({ credentialStatus: async () => view, credentialRead: async () => ({ value }), credentialTest: async () => ({ result: 'success', message: 'success' }), credentialSave: async () => view, credentialDelete: async () => status() }));
  for (const action of ['edit', 'save', 'delete', 'refresh']) {
    ctx.root.querySelector('[data-action="test"]').click(); await flush(); assert.equal(ctx.root.querySelector('[data-test-result]').dataset.kind, 'success');
    if (action === 'edit') ctx.root.querySelector('textarea').dispatchEvent(new ctx.window.Event('input'));
    if (action === 'save') submit(ctx);
    if (action === 'delete') { ctx.root.querySelector('[data-action="delete"]').click(); ctx.root.querySelector('[data-action="confirm-delete"]').click(); }
    if (action === 'refresh') { view = status(true, { store: { state: 'present', saved_at: 2 } }); ctx.root.querySelector('[data-action="refresh"]').click(); }
    await flush(); assert.equal(ctx.root.querySelector('[data-test-result]').dataset.kind, 'idle', action);
  } ctx.window.close();
});
test('late test response cannot overwrite a changed or disposed editor', async () => {
  const ctx = setup(); let resolveTest;
  const mounted = await mountCredentials(ctx.root, api({ credentialTest: () => new Promise(resolve => { resolveTest = resolve; }) }));
  ctx.root.querySelector('[data-action="test"]').click(); ctx.root.querySelector('textarea').dispatchEvent(new ctx.window.Event('input'));
  resolveTest({ result: 'success', message: 'stale response' }); await flush(); assert.doesNotMatch(ctx.root.textContent, /stale response/);
  ctx.root.querySelector('[data-action="test"]').click(); mounted.dispose(); resolveTest({ result: 'success', message: 'disposed response' }); await flush(); assert.doesNotMatch(ctx.root.textContent, /disposed response/); ctx.window.close();
});
test('test outcomes retain provider error messages and external request warning', async () => {
  for (const result of ['success', 'auth_failed', 'quota', 'network']) {
    const ctx = setup(); await mountCredentials(ctx.root, api({ credentialTest: async () => ({ result, message: 'provider:' + result }) }));
    assert.match(ctx.root.textContent, /外部搜索请求.*额度/); ctx.root.querySelector('[data-action="test"]').click(); await flush();
    assert.equal(ctx.root.querySelector('[data-test-result]').dataset.kind, result === 'success' ? 'success' : 'error'); assert.equal(ctx.root.querySelector('[data-info="test"]').textContent, 'provider:' + result); ctx.window.close();
  }
});
test('application link stays disabled without mapping, configured entry passes source only', async () => {
  for (const available of [false, true]) {
    const ctx = setup(), opened = [];
    await mountCredentials(ctx.root, api({ credentialStatus: async () => status(false, { key_application_available: available }), credentialApplicationOpen: async source => { opened.push(source); } }), { source: 'github_repos' });
    const button = ctx.root.querySelector('[data-action="application"]'); assert.equal(button.disabled, !available); button.click(); await flush(); assert.deepEqual(opened, available ? ['github_repos'] : []);
    if (!available) assert.match(ctx.root.textContent, /申请链接待配置/); ctx.window.close();
  }
});
test('typed Tauri adapter reads source only and opens fixed application source', async () => {
  const calls = [], client = managementApi(async (cmd, args) => {
    calls.push([cmd, args]);
    if (cmd === 'credential_read') return { value: '' };
    return null;
  });
  await client.credentialRead('tavily'); await client.credentialApplicationOpen('brave');
  assert.deepEqual(calls, [['credential_read', { source: 'tavily' }], ['credential_application_open', { source: 'brave' }]]);
});
