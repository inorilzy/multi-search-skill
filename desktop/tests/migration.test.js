import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountMigration } from '../ui/migration.js';
const TOKEN = 'a'.repeat(64), KEY = 'synthetic-full-key-0001';
const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const plan = () => ({ plan_token: TOKEN, items: [
  { provider: 'tavily', action: 'migrate', preview: 'masked…0001' },
  { provider: 'brave', action: 'conflict', target_conflict: true, preview: 'masked…0002' },
  { provider: 'jina', action: 'migrate', preview: 'structured key' },
  { provider: 'settings', action: 'migrate', preview: 'non-secret settings' },
], migratable: ['tavily','brave','jina','settings'], skipped: [] });
const complete = () => ({ written: [], kept: [], unchanged: [], failed: [], not_done: [], complete: true });
async function setup(api) { const window = new Window(), root = window.document.createElement('main'); window.document.body.append(root); const mounted = await mountMigration(root, api); return { window, root, mounted }; }
function select(root, names = ['keys_file']) { for (const name of names) root.querySelector(`[data-import="${name}"]`).checked = true; }
async function preview(root) { root.querySelector('[data-action="preview"]').click(); await flush(); }
test('no source is selected implicitly and all four explicit legacy inputs are available', async () => {
  let calls = 0; const ctx = await setup({ migrationPlan: async () => { calls++; return plan(); } });
  assert.equal(ctx.root.querySelectorAll('[data-import]').length, 4); assert.ok([...ctx.root.querySelectorAll('[data-import]')].every(b => !b.checked));
  await preview(ctx.root); assert.equal(calls, 0); assert.match(ctx.root.querySelector('[data-info="error"]').textContent, /至少一个/);
  assert.match(ctx.root.textContent, /尚未导入.*不会自动生效/); ctx.window.close();
});
test('masked preview supports multi key, jina and settings and preserves selected inputs', async () => {
  let selected; const ctx = await setup({ migrationPlan: async input => { selected = input; return plan(); } });
  select(ctx.root, ['keys_file','credentials','environment','settings']); await preview(ctx.root);
  assert.deepEqual(selected, { keys_file:true, credentials:true, environment:true, settings:true });
  assert.ok(ctx.root.querySelector('[data-approve="jina"]')); assert.ok(ctx.root.querySelector('[data-approve="settings"]'));
  assert.ok(!ctx.root.innerHTML.includes(KEY)); assert.match(ctx.root.textContent, /不修改、不删除/); ctx.window.close();
});
test('masked structured previews show multi keys and jina exhaustion without object coercion', async () => {
  const p=plan();p.items[0].preview=['masked…0001','masked…0002'];p.items[2].preview=[{key:'jina…0001',exhausted:true},{key:'jina…0002',exhausted:false}];p.items[2].source_conflict=true;p.items[2].sources=[{source:'file',preview:p.items[2].preview},{source:'credentials',preview:{key:'other…0001',exhausted:false}}];
  const ctx=await setup({migrationPlan:async()=>p});select(ctx.root);await preview(ctx.root);
  assert.match(ctx.root.querySelector('[data-item="tavily"] code').textContent,/masked…0001.*masked…0002/);
  assert.match(ctx.root.querySelector('[data-item="jina"] code').textContent,/"key":"jina…0001","exhausted":true/);
  assert.match(ctx.root.querySelector('[data-source-choice="jina"]').textContent,/other…0001/);assert.doesNotMatch(ctx.root.textContent,/\[object Object\]/);assert.ok(!ctx.root.innerHTML.includes(KEY));ctx.window.close();
});
test('apply demands target conflict decision and passes approved provider selection and same flags', async () => {
  const calls = [], ctx = await setup({ migrationPlan: async () => plan(), migrationApply: async (...args) => { calls.push(args); return complete(); } });
  select(ctx.root); await preview(ctx.root);
  ctx.root.querySelector('[data-approve="tavily"]').checked = true; ctx.root.querySelector('[data-approve="brave"]').checked = true;
  ctx.root.querySelector('[data-action="apply"]').click(); await flush(); assert.equal(calls.length, 0);
  ctx.root.querySelector('[data-choice="brave"]').value = 'keep'; ctx.root.querySelector('[data-action="apply"]').click(); await flush();
  assert.deepEqual(calls[0], [TOKEN,['tavily','brave'],{brave:'keep'},{},{keys_file:true,credentials:false,environment:false,settings:false}]); ctx.window.close();
});
test('multiple old sources require a source selection independently of target keep/replace', async () => {
  const calls = [], p = plan(); p.items[0] = { provider:'tavily',action:'conflict',source_conflict:true,target_conflict:true,sources:[{source:'file',preview:'masked'},{source:'environment:TAVILY_API_KEY',preview:'masked-env'}] };
  const ctx = await setup({ migrationPlan: async () => p, migrationApply: async (...args) => { calls.push(args); return complete(); } }); select(ctx.root,['keys_file','environment']); await preview(ctx.root);
  ctx.root.querySelector('[data-approve="tavily"]').checked = true; ctx.root.querySelector('[data-choice="tavily"]').value = 'replace'; ctx.root.querySelector('[data-action="apply"]').click(); await flush(); assert.equal(calls.length, 0);
  ctx.root.querySelector('[data-source-choice="tavily"]').value = 'environment:TAVILY_API_KEY'; ctx.root.querySelector('[data-action="apply"]').click(); await flush(); assert.deepEqual(calls[0][3],{tavily:'environment:TAVILY_API_KEY'}); ctx.window.close();
});
test('changing input sources invalidates prior preview', async () => {
  const ctx = await setup({ migrationPlan: async () => plan() }); select(ctx.root); await preview(ctx.root); assert.ok(ctx.root.querySelector('[data-action="apply"]'));
  const box = ctx.root.querySelector('[data-import="environment"]'); box.checked = true; box.dispatchEvent(new ctx.window.Event('change')); assert.equal(ctx.root.querySelector('[data-action="apply"]'),null); ctx.window.close();
});
test('late preview cannot restore apply after source selection changes', async () => {
  let resolve; const ctx = await setup({ migrationPlan: () => new Promise(done => { resolve = done; }) }); select(ctx.root); ctx.root.querySelector('[data-action="preview"]').click();
  const box=ctx.root.querySelector('[data-import="environment"]');box.checked=true;box.dispatchEvent(new ctx.window.Event('change'));resolve(plan());await flush();assert.equal(ctx.root.querySelector('[data-action="apply"]'),null);ctx.window.close();
});
test('old CLI failure cannot claim import success', async () => {
  for (const phase of ['preview','apply']) {
    const ctx = await setup({ migrationPlan: phase === 'preview' ? async () => { throw 'CLI 不支持 SQLite 协议'; } : async () => plan(), migrationApply: async () => { throw 'CLI 不支持 SQLite 协议'; } }); select(ctx.root); await preview(ctx.root);
    if (phase === 'preview') assert.match(ctx.root.querySelector('[data-info="error"]').textContent,/不支持 SQLite/);
    else { ctx.root.querySelector('[data-approve="tavily"]').checked = true; ctx.root.querySelector('[data-action="apply"]').click(); await flush(); assert.match(ctx.root.querySelector('[data-info="result"]').textContent,/不支持 SQLite/); }
    assert.doesNotMatch(ctx.root.textContent,/导入完成。|已写入：/); ctx.window.close();
  }
});
test('partial import exposes failure and pending items', async () => {
  const ctx = await setup({ migrationPlan: async () => plan(), migrationApply: async () => ({...complete(),written:['tavily'],failed:['brave'],not_done:['jina'],complete:false}) }); select(ctx.root); await preview(ctx.root); ctx.root.querySelector('[data-approve="tavily"]').checked=true; ctx.root.querySelector('[data-action="apply"]').click(); await flush();
  assert.match(ctx.root.querySelector('[data-info="result"]').textContent,/导入未全部完成.*已写入：tavily.*失败：brave.*未完成：jina/); ctx.window.close();
});
