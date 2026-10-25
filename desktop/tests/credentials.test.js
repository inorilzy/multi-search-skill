import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountCredentials, mountCredentialBody, SOURCES, scrapeCredentialProviders } from '../ui/credentials.js';
import { managementApi } from '../ui/api.js';
const KEY = 'synthetic-ui-key-0001';
const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const flush2 = async () => { await flush(); await flush(); };
const status = (saved = false, extra = {}) => ({ store: { state: saved ? 'present' : 'absent', saved_at: saved ? 1 : null, error: '' }, effective_source: saved ? 'sqlite' : 'none', key_application_available: false, ...extra });
function setup() { const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root); return { window, root }; }
const submit = ({ window, root }) => root.querySelector('form').dispatchEvent(new window.Event('submit', { cancelable: true }));
function api(overrides = {}) { return { credentialStatus: async () => status(), credentialRead: async () => ({ value: '' }), credentialAppend: async () => status(true), credentialRemove: async () => status(), ...overrides }; }
const coded = (code, message = '') => JSON.stringify({ code, message });
const savedInputs = root => [...root.querySelectorAll('[data-saved-list] input')].map(input => input.value);
const draftInputs = root => [...root.querySelectorAll('[data-draft-list] input')];

test('saved values render one readonly input per line, never through HTML', async () => {
  const ctx = setup(); const seen = [];
  await mountCredentials(ctx.root, api({ credentialStatus: async () => status(true), credentialRead: async source => { seen.push(source); return { value: KEY + '\nsecond-key' }; } }));
  assert.equal(ctx.root.querySelector('textarea'), null);
  assert.deepEqual(seen, ['tavily']);
  assert.deepEqual(savedInputs(ctx.root), [KEY, 'second-key']);
  assert.equal(ctx.root.querySelectorAll('[data-saved-list] input')[0].readOnly, true);
  assert.equal(ctx.root.querySelectorAll('[type="password"]').length, 2);
  assert.ok(!ctx.root.innerHTML.includes(KEY), 'saved values go through .value, not HTML interpolation');
  assert.equal(ctx.root.querySelectorAll('[data-draft-list] input').length, 1, 'one empty draft row initially');
  ctx.window.close();
});

test('all keyed sources query their own overview and read command', async () => {
  assert.equal(SOURCES.filter(s => s.keyed).length, 8);
  for (const entry of SOURCES.filter(s => s.keyed)) {
    const ctx = setup(), calls = [];
    await mountCredentials(ctx.root, api({ credentialStatus: async s => { calls.push(['status', s]); return status(); }, credentialRead: async s => { calls.push(['read', s]); return { value: '' }; } }), { source: entry.source });
    assert.deepEqual(calls, [['status', entry.source], ['read', entry.source]]); assert.ok(ctx.root.textContent.includes(entry.label)); ctx.window.close();
  }
});

test('append sends only non-empty draft rows, keeps old keys and clears submitted drafts', async () => {
  const ctx = setup(); let calls = [];
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(true),
    credentialRead: async () => ({ value: KEY + '\nsecond-key' }),
    credentialAppend: async (source, keys) => { calls.push(keys); return status(true); },
    credentialTest: async () => { assert.fail('must not test automatically'); },
  }));
  draftInputs(ctx.root)[0].value = '  new-key-1  ';
  ctx.root.querySelector('[data-action="add"]').click();
  draftInputs(ctx.root)[1].value = 'new-key-2';
  ctx.root.querySelector('[data-action="add"]').click(); // third draft left empty
  submit(ctx); await flush2();
  assert.deepEqual(calls, [['new-key-1', 'new-key-2']]);
  assert.deepEqual(savedInputs(ctx.root), [KEY, 'second-key'], 'readback value unchanged by stub');
  assert.deepEqual(draftInputs(ctx.root).map(i => i.value), [''], 'submitted drafts cleared');
  assert.equal(ctx.root.querySelector('[data-status="source"]').textContent, 'SQLite / DPAPI');
  assert.match(ctx.root.querySelector('[data-info="test"]').textContent, /已保存.*尚未测试/);
  ctx.window.close();
});

test('append failure retains drafts and shows the backend error', async () => {
  const ctx = setup();
  await mountCredentials(ctx.root, api({ credentialAppend: async () => { throw '数据库拒绝，未保存'; } }));
  draftInputs(ctx.root)[0].value = KEY;
  submit(ctx); await flush2();
  assert.equal(draftInputs(ctx.root)[0].value, KEY);
  assert.match(ctx.root.querySelector('[data-info="error"]').textContent, /未保存/);
  assert.equal(ctx.root.querySelector('[data-status="store"]').textContent, '未保存');
  ctx.window.close();
});

test('row delete confirms with row number, cancel writes nothing, confirm removes only that row', async () => {
  const ctx = setup(); const removed = [];
  let value = KEY + '\nsecond-key\nthird-key';
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(true),
    credentialRead: async () => ({ value, snapshot: 'opaque-revision' }),
    credentialRemove: async (source, index, expected) => { removed.push([index, expected]); value = value.split('\n').filter((_, i) => i !== index).join('\n'); return status(true); },
  }));
  const buttons = ctx.root.querySelectorAll('[data-action="remove"]');
  buttons[1].click();
  const confirm = ctx.root.querySelector('[data-confirm="remove"]');
  assert.match(confirm.textContent, /第 2 行/);
  assert.ok(!confirm.textContent.includes('second-key'), 'confirm names the row, never the key');
  assert.equal(removed.length, 0);
  confirm.querySelector('[data-action="cancel-remove"]').click();
  assert.equal(removed.length, 0);
  assert.deepEqual(savedInputs(ctx.root), [KEY, 'second-key', 'third-key']);
  ctx.root.querySelectorAll('[data-action="remove"]')[1].click();
  ctx.root.querySelector('[data-action="confirm-remove"]').click(); await flush2();
  assert.deepEqual(removed, [[1, 'opaque-revision']]);
  assert.deepEqual(savedInputs(ctx.root), [KEY, 'third-key']);
  ctx.window.close();
});

test('deleting the last saved row shows the empty state', async () => {
  const ctx = setup();
  let value = KEY;
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(true),
    credentialRead: async () => ({ value, snapshot: 'opaque-revision' }),
    credentialRemove: async () => { value = ''; return status(); },
  }));
  ctx.root.querySelector('[data-action="remove"]').click();
  ctx.root.querySelector('[data-action="confirm-remove"]').click(); await flush2();
  assert.deepEqual(savedInputs(ctx.root), []);
  assert.equal(ctx.root.querySelector('[data-saved-empty]').hidden, false);
  ctx.window.close();
});

test('failed row delete keeps saved values and reports the failure', async () => {
  const ctx = setup();
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(true),
    credentialRead: async () => ({ value: KEY }),
    credentialRemove: async () => { throw '未删除'; },
  }));
  ctx.root.querySelector('[data-action="remove"]').click();
  ctx.root.querySelector('[data-action="confirm-remove"]').click(); await flush2();
  assert.deepEqual(savedInputs(ctx.root), [KEY]);
  assert.match(ctx.root.querySelector('[data-info="error"]').textContent, /未删除/);
  ctx.window.close();
});

test('drafts survive refresh and a row delete', async () => {
  const ctx = setup(); let value = KEY;
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(true),
    credentialRead: async () => ({ value, snapshot: 'opaque-revision' }),
    credentialRemove: async () => { value = 'second-key'; return status(true); },
  }));
  draftInputs(ctx.root)[0].value = 'draft-key';
  ctx.root.querySelector('[data-action="refresh"]').click(); await flush2();
  assert.equal(draftInputs(ctx.root)[0].value, 'draft-key', 'refresh preserves drafts');
  ctx.root.querySelector('[data-action="remove"]').click();
  ctx.root.querySelector('[data-action="confirm-remove"]').click(); await flush2();
  assert.equal(draftInputs(ctx.root)[0].value, 'draft-key', 'delete preserves drafts');
  ctx.window.close();
});

test('read failure disables writes until a refresh succeeds', async () => {
  const ctx = setup(); let fail = true;
  const apiMock = api({
    credentialStatus: async () => status(true),
    credentialRead: async () => { if (fail) throw '读取失败'; return { value: KEY }; },
  });
  await mountCredentials(ctx.root, apiMock);
  assert.equal(ctx.root.querySelector('[data-action="save"]').disabled, true);
  assert.equal(draftInputs(ctx.root)[0].disabled, true);
  assert.equal(ctx.root.querySelectorAll('[data-action="remove"]').length, 0, 'no saved rows without a read');
  fail = false;
  ctx.root.querySelector('[data-action="refresh"]').click(); await flush2();
  assert.equal(ctx.root.querySelector('[data-action="save"]').disabled, false);
  assert.equal(draftInputs(ctx.root)[0].disabled, false);
  ctx.window.close();
});

test('write success followed by read failure does not duplicate the append on retry', async () => {
  const ctx = setup(); let appended = []; let readCalls = 0;
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(true),
    credentialRead: async () => { readCalls += 1; if (readCalls > 1) throw '刷新读取失败'; return { value: KEY }; },
    credentialAppend: async (source, keys) => { appended.push(keys); return status(true); },
  }));
  draftInputs(ctx.root)[0].value = 'new-key';
  submit(ctx); await flush2();
  assert.deepEqual(appended, [['new-key']]);
  assert.equal(draftInputs(ctx.root)[0].value, '', 'draft cleared so a retry cannot re-append');
  assert.match(ctx.root.querySelector('[data-info="error"]').textContent, /已保存.*刷新读取失败/);
  assert.equal(ctx.root.querySelector('[data-action="save"]').disabled, true, 'mutations disabled until refresh');
  ctx.window.close();
});

test('busy and dispose guards ignore late responses and rebuilt controls', async () => {
  const ctx = setup(); let resolveAppend, resolveTest;
  const mounted = await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(true),
    credentialRead: async () => ({ value: KEY }),
    credentialAppend: () => new Promise(resolve => { resolveAppend = resolve; }),
    credentialTest: () => new Promise(resolve => { resolveTest = resolve; }),
  }));
  draftInputs(ctx.root)[0].value = 'new-key';
  submit(ctx);
  assert.equal(ctx.root.querySelector('[data-action="save"]').disabled, true);
  mounted.dispose();
  resolveAppend(status(true));
  if (resolveTest) resolveTest({ result: 'success', message: 'late' });
  await flush();
  assert.doesNotMatch(ctx.root.textContent, /late/);
  ctx.window.close();
});

test('multiline paste into a draft row is refused instead of merged silently', async () => {
  const ctx = setup();
  await mountCredentials(ctx.root, api());
  const input = draftInputs(ctx.root)[0];
  input.value = KEY;
  const event = new ctx.window.Event('paste', { cancelable: true, bubbles: true });
  Object.defineProperty(event, 'clipboardData', { value: { getData: () => 'a\nb' } });
  input.dispatchEvent(event);
  assert.equal(event.defaultPrevented, true);
  assert.match(ctx.root.querySelector('[data-info="error"]').textContent, /逐行/);
  ctx.window.close();
});

test('draft editing invalidates a previous test result', async () => {
  const ctx = setup();
  await mountCredentials(ctx.root, api({ credentialStatus: async () => status(true), credentialRead: async () => ({ value: KEY }), credentialTest: async () => ({ result: 'success', message: 'ok' }) }));
  ctx.root.querySelector('[data-action="test"]').click(); await flush();
  assert.equal(ctx.root.querySelector('[data-test-result]').dataset.kind, 'success');
  const input = draftInputs(ctx.root)[0];
  input.value = 'changed';
  input.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
  assert.equal(ctx.root.querySelector('[data-test-result]').dataset.kind, 'idle');
  ctx.window.close();
});

test('application link stays disabled without mapping, configured entry passes source only', async () => {
  for (const available of [false, true]) {
    const ctx = setup(), opened = [];
    await mountCredentials(ctx.root, api({ credentialStatus: async () => status(false, { key_application_available: available }), credentialApplicationOpen: async source => { opened.push(source); } }), { source: 'github_repos' });
    const button = ctx.root.querySelector('[data-action="application"]'); assert.equal(button.disabled, !available); button.click(); await flush(); assert.deepEqual(opened, available ? ['github_repos'] : []);
    if (!available) assert.match(ctx.root.textContent, /申请链接待配置/); ctx.window.close();
  }
});

test('test outcomes retain provider error messages and external request warning', async () => {
  for (const result of ['success', 'auth_failed', 'quota', 'network']) {
    const ctx = setup(); await mountCredentials(ctx.root, api({ credentialTest: async () => ({ result, message: 'provider:' + result }) }));
    assert.match(ctx.root.textContent, /外部搜索请求.*额度/); ctx.root.querySelector('[data-action="test"]').click(); await flush();
    assert.equal(ctx.root.querySelector('[data-test-result]').dataset.kind, result === 'success' ? 'success' : 'error'); assert.equal(ctx.root.querySelector('[data-info="test"]').textContent, 'provider:' + result);
    const titles = { success: /^测试成功：Tavily 本次使用 未配置。$/, auth_failed: /^认证失败：Tavily 拒绝了该 Key。$/, quota: /^额度不足：Tavily 额度已用尽。$/, network: /^网络错误：无法连接 Tavily。$/ };
    assert.match(ctx.root.querySelector('[data-status="test"]').textContent, titles[result]); ctx.window.close();
  }
});

test('typed Tauri adapter sends append and remove contracts and keeps save/delete adapters', async () => {
  const calls = [], client = managementApi(async (cmd, args) => {
    calls.push([cmd, args]);
    if (cmd === 'credential_read' || cmd === 'credential_reveal') return { value: '', snapshot: 'opaque-revision' };
    if (cmd === 'credential_append' || cmd === 'credential_remove' || cmd === 'credential_save' || cmd === 'credential_delete') return { ...status(true), source: args.source };
    return null;
  });
  await client.credentialRead('tavily');
  await client.credentialReveal('tavily');
  await client.credentialAppend('tavily', ['a', 'b']);
  await client.credentialRemove('tavily', 1, 'opaque-revision');
  await client.credentialSave('tavily', 'k');
  await client.credentialDelete('tavily');
  await client.credentialApplicationOpen('brave');
  assert.deepEqual(calls, [
    ['credential_read', { source: 'tavily' }],
    ['credential_reveal', { source: 'tavily' }],
    ['credential_append', { source: 'tavily', keys: ['a', 'b'] }],
    ['credential_remove', { source: 'tavily', index: 1, expected: 'opaque-revision' }],
    ['credential_save', { source: 'tavily', key: 'k' }],
    ['credential_delete', { source: 'tavily' }],
    ['credential_application_open', { source: 'brave' }],
  ]);
});


test('programmatic double submit and Enter submit are guarded while busy', async () => {
  const ctx = setup(); let appended = []; let release;
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(true),
    credentialRead: async () => ({ value: KEY }),
    credentialAppend: (source, keys) => new Promise(resolve => { release = () => { appended.push(keys); resolve(status(true)); }; }),
  }));
  draftInputs(ctx.root)[0].value = 'new-key';
  submit(ctx); submit(ctx); submit(ctx);
  release(); await flush();
  assert.deepEqual(appended, [['new-key']], 'one in-flight append only; repeats while busy are ignored');
  ctx.window.close();
});

test('submit is refused after read failure until refresh restores health', async () => {
  const ctx = setup(); let calls = 0;
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(true),
    credentialRead: async () => { throw '读取失败'; },
    credentialAppend: async (source, keys) => { calls += 1; return status(true); },
  }));
  draftInputs(ctx.root)[0].value = 'new-key';
  submit(ctx); await flush2();
  assert.equal(calls, 0, 'no write without a successful read anchor');
  ctx.window.close();
});


test('empty submit surfaces a prompt instead of silently doing nothing', async () => {
  const ctx = setup(); let calls = 0;
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(true),
    credentialRead: async () => ({ value: KEY }),
    credentialAppend: async () => { calls += 1; return status(true); },
  }));
  submit(ctx); await flush();
  assert.equal(calls, 0);
  assert.match(ctx.root.querySelector('[data-info="error"]').textContent, /请先输入至少一条 Key/);
  ctx.window.close();
});

test('remove-draft is disabled while reads are unhealthy', async () => {
  const ctx = setup();
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(true),
    credentialRead: async () => { throw '读取失败'; },
  }));
  assert.equal(ctx.root.querySelector('[data-action="remove-draft"]').disabled, true);
  ctx.window.close();
});


test('masked keys reveal only on demand and copy is disabled until revealed', async () => {
  const ctx = setup(); let reveals = 0;
  const mounted = await mountCredentials(ctx.root, api({
    credentialRead: async () => ({ value: '••••••••', snapshot: 'revision-1' }),
    credentialReveal: async () => { reveals++; return { value: KEY, snapshot: 'revision-1' }; },
  }));
  assert.equal(reveals, 0); assert.deepEqual(savedInputs(ctx.root), ['••••••••']);
  assert.equal(ctx.root.querySelector('[data-action="copy"]').disabled, true);
  ctx.root.querySelector('[data-action="reveal"]').click(); await flush2();
  assert.equal(reveals, 1); assert.deepEqual(savedInputs(ctx.root), [KEY]);
  assert.equal(ctx.root.querySelector('[data-action="copy"]').disabled, false);
  ctx.root.querySelector('[data-action="reveal"]').click();
  assert.deepEqual(savedInputs(ctx.root), ['••••••••']);
  assert.equal(ctx.root.querySelector('[data-action="copy"]').disabled, true);
  ctx.root.querySelector('[data-action="reveal"]').click(); await flush2();
  mounted.dispose(); assert.equal(ctx.root.querySelector('[data-saved-input]'), null); ctx.window.close();
});


test('catalog drives the source list: labels are literal text and scrape-only providers come from the catalog', async () => {
  assert.deepEqual(SOURCES.map(entry => entry.source), [
    'baidu', 'brave', 'parallel', 'tavily', 'exa', 'firecrawl', 'serpapi',
    'github_repos', 'hackernews', 'stackoverflow', 'sov2ex', 'twitter',
  ]);
  // Jina is the only scrape-only provider that owns a keyed credential, so it appears here
  // from the catalog alone; nothing in this list is hardcoded by the UI.
  assert.deepEqual(scrapeCredentialProviders(), [
    { source: 'jina', label: 'Jina Reader', keyed: true, cookie: false, search: false },
  ]);
  const ctx = setup();
  await mountCredentials(ctx.root, api(), { source: 'github_repos' });
  assert.match(ctx.root.querySelector('h1').textContent, /^GitHub 仓库 凭据$/);
  assert.equal(ctx.root.querySelector('img'), null);
  ctx.window.close();
});

test('full credential page uses its navigation number and a focusable heading', async () => {
  const ctx = setup();
  await mountCredentials(ctx.root, api(), { number: '09' });
  assert.match(ctx.root.querySelector('.eyebrow').textContent, /^09 \/ /);
  assert.equal(ctx.root.querySelector('h1').getAttribute('tabindex'), '-1');
  ctx.window.close();
});

test('status and saved values are read exactly once on mount', async () => {
  const ctx = setup(); const calls = [];
  await mountCredentialBody(ctx.root, api({
    credentialStatus: async source => { calls.push(['status', source]); return status(true); },
    credentialRead: async source => { calls.push(['read', source]); return { value: KEY, snapshot: 's' }; },
  }), { source: 'brave' });
  assert.deepEqual(calls, [['status', 'brave'], ['read', 'brave']]);
  ctx.window.close();
});

test('an English backend reason is never shown; the raw reason stays in the tooltip', async () => {
  const ctx = setup();
  await mountCredentials(ctx.root, api({ credentialAppend: async () => { throw 'Credential append worker failed'; } }));
  draftInputs(ctx.root)[0].value = KEY;
  submit(ctx); await flush2();
  const error = ctx.root.querySelector('[data-info="error"]');
  assert.match(error.textContent, /保存失败，编辑值已保留/);
  assert.doesNotMatch(error.textContent, /worker/);
  assert.equal(error.title, 'Credential append worker failed');
  assert.equal(draftInputs(ctx.root)[0].value, KEY, 'the draft is kept for a retry');
  ctx.window.close();
});

test('a coded backend failure shows the mapped Chinese message', async () => {
  const ctx = setup();
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(true),
    credentialRead: async () => ({ value: KEY, snapshot: 's' }),
    credentialRemove: async () => { throw coded('credential_remove_failed', 'Credential remove worker failed'); },
  }));
  ctx.root.querySelector('[data-action="remove"]').click();
  ctx.root.querySelector('[data-action="confirm-remove"]').click(); await flush2();
  assert.equal(ctx.root.querySelector('[data-info="error"]').textContent, '凭据删除失败，已保存的值没有改变。');
  assert.deepEqual(savedInputs(ctx.root), [KEY]);
  ctx.window.close();
});

test('a failed save writes nothing into the test-result area', async () => {
  const ctx = setup();
  await mountCredentials(ctx.root, api({ credentialAppend: async () => { throw coded('credential_append_failed'); } }));
  draftInputs(ctx.root)[0].value = KEY;
  submit(ctx); await flush2();
  assert.equal(ctx.root.querySelector('[data-status="test"]').textContent, '尚未测试');
  assert.equal(ctx.root.querySelector('[data-info="test"]').textContent, '');
  ctx.window.close();
});

test('a test that cannot start reports through the error slot, not as a provider verdict', async () => {
  const ctx = setup();
  await mountCredentials(ctx.root, api({ credentialTest: async () => { throw coded('credential_test_failed', 'Test worker failed'); } }));
  ctx.root.querySelector('[data-action="test"]').click(); await flush2();
  assert.equal(ctx.root.querySelector('[data-info="error"]').textContent, '凭据测试启动失败，请检查 CLI 后重试。');
  assert.equal(ctx.root.querySelector('[data-status="test"]').textContent, '测试失败');
  assert.equal(ctx.root.querySelector('[data-info="test"]').textContent, '');
  ctx.window.close();
});

test('no saved key value reaches the markup, even after reveal', async () => {
  const ctx = setup();
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(true),
    credentialRead: async () => ({ value: '••••0001', snapshot: 'r1' }),
    credentialReveal: async () => ({ value: KEY, snapshot: 'r1' }),
  }));
  ctx.root.querySelector('[data-action="reveal"]').click(); await flush2();
  assert.deepEqual(savedInputs(ctx.root), [KEY]);
  assert.ok(!ctx.root.innerHTML.includes(KEY), 'revealed values live only in input.value');
  ctx.window.close();
});

test('row delete confirmation focuses cancel, closes on Escape and returns focus to its button', async () => {
  const ctx = setup(); const removed = [];
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(true),
    credentialRead: async () => ({ value: KEY + '\nsecond-key', snapshot: 'r1' }),
    credentialRemove: async (...args) => { removed.push(args); return status(true); },
  }));
  const trigger = ctx.root.querySelectorAll('[data-action="remove"]')[1];
  trigger.focus();
  trigger.click();
  const panel = ctx.root.querySelector('[data-confirm="remove"]');
  assert.equal(panel.getAttribute('role'), 'group');
  assert.equal(ctx.window.document.activeElement, panel.querySelector('[data-action="cancel-remove"]'));
  panel.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(ctx.root.querySelector('[data-confirm="remove"]'), null);
  assert.equal(ctx.window.document.activeElement, trigger);
  assert.deepEqual(removed, []);
  ctx.window.close();
});

test('the typed adapter sends no executable path with a credential test', async () => {
  const calls = [];
  const client = managementApi(async (cmd, args) => { calls.push([cmd, args]); return { result: 'success', message: '' }; });
  await client.credentialTest('tavily', 'C:\\evil\\multi-search.exe');
  assert.deepEqual(calls, [['credential_test', { source: 'tavily' }]]);
});

test('Core-reported provenance is labelled; the optional fields may be absent', async () => {
  const cases = [
    [status(true, { effective_source: 'env', env_var: 'TAVILY_API_KEY', env_overrides_store: true }), '环境变量 TAVILY_API_KEY'],
    [status(true, { effective_source: 'file', file_key_count: 3 }), '旧 Key 文件中的 3 个 Key'],
    [status(true, { effective_source: 'credential_store' }), '本机凭据库'],
    [status(true), 'SQLite / DPAPI'],
    [status(true, { effective_source: 'future_store' }), '未知来源（future_store）'],
  ];
  for (const [view, label] of cases) {
    const ctx = setup();
    await mountCredentials(ctx.root, api({ credentialStatus: async () => view, credentialRead: async () => ({ value: KEY, snapshot: 's' }) }));
    assert.equal(ctx.root.querySelector('[data-status="source"]').textContent, label);
    ctx.window.close();
  }
});
