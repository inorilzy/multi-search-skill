import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountCredentials, mountCredentialBody, SOURCES, scrapeCredentialProviders } from '../ui/credentials.js';
import { managementApi } from '../ui/api.js';
const KEY = 'synthetic-ui-key-0001';
const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const flush2 = async () => { await flush(); await flush(); };
// Before Core answers, a saved provider reports `file` and an unsaved one `none`.
const status = (saved = false, extra = {}) => ({ store: { state: saved ? 'present' : 'absent', saved_at: saved ? 1 : null, error: '' }, effective_source: saved ? 'file' : 'none', key_application_available: false, key_application_open_supported: true, ...extra });
function setup() { const window = new Window(); const root = window.document.createElement('main'); window.document.body.append(root); return { window, root }; }
const submit = ({ window, root }) => root.querySelector('form').dispatchEvent(new window.Event('submit', { cancelable: true }));
function api(overrides = {}) { return { credentialStatus: async () => status(), credentialRead: async () => ({ value: '' }), credentialAppend: async () => status(true), credentialRemove: async () => status(), ...overrides }; }
const coded = (code, message = '') => JSON.stringify({ code, message });
const savedInputs = root => [...root.querySelectorAll('[data-saved-list] input')].map(input => input.value);
const draftRows = root => [...root.querySelectorAll('[data-draft-list] input')];
// Draft rows only exist after "新增 Key"; open one (when writes allow it) before reading drafts.
const draftInputs = root => {
  if (draftRows(root).length === 0) root.querySelector('[data-action="add"]')?.click();
  return draftRows(root);
};

test('saved values render one readonly input per line, never through HTML', async () => {
  const ctx = setup(); const seen = [];
  await mountCredentials(ctx.root, api({ credentialStatus: async () => status(true), credentialRead: async source => { seen.push(source); return { value: KEY + '\nsecond-key' }; } }));
  assert.equal(ctx.root.querySelector('textarea'), null);
  assert.deepEqual(seen, ['tavily']);
  assert.deepEqual(savedInputs(ctx.root), [KEY, 'second-key']);
  assert.equal(ctx.root.querySelectorAll('[data-saved-list] input')[0].readOnly, true);
  assert.equal(ctx.root.querySelectorAll('[type="password"]').length, 2);
  assert.ok(!ctx.root.innerHTML.includes(KEY), 'saved values go through .value, not HTML interpolation');
  assert.equal(ctx.root.querySelectorAll('[data-draft-list] input').length, 0, 'no draft row until 新增 Key is clicked');
  assert.equal(ctx.root.querySelector('[data-action="save"]').hidden, true, 'save appears only with a draft row');
  ctx.window.close();
});

test('all keyed sources query their own overview and read command', async () => {
  assert.equal(SOURCES.filter(s => s.keyed).length, 10);
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
  assert.deepEqual(draftRows(ctx.root), [], 'submitted drafts cleared');
  assert.equal(ctx.root.querySelector('[data-status="source"]').textContent, 'Key 文件（~/.multi-search/keys.json）');
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
  assert.equal(ctx.root.querySelector('[data-action="add"]').disabled, true);
  assert.deepEqual(draftInputs(ctx.root), [], 'a disabled add opens no draft row');
  assert.equal(ctx.root.querySelectorAll('[data-action="remove"]').length, 0, 'no saved rows without a read');
  fail = false;
  ctx.root.querySelector('[data-action="refresh"]').click(); await flush2();
  assert.equal(ctx.root.querySelector('[data-action="add"]').disabled, false);
  assert.equal(draftInputs(ctx.root)[0].disabled, false);
  assert.equal(ctx.root.querySelector('[data-action="save"]').disabled, false);
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
  assert.deepEqual(draftRows(ctx.root), [], 'draft cleared so a retry cannot re-append');
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
    if (!available) assert.match(ctx.root.textContent, /该搜索源暂无固定申请链接，无法打开申请页。/); ctx.window.close();
  }
});

test('missing application mapping disables opening without guessing or echoing a link', async () => {
  const ctx = setup(), opened = [];
  await mountCredentials(ctx.root, api({ credentialStatus: async () => status(false, { key_application_available: false, key_application_open_supported: false, key_application_url: undefined }), credentialApplicationOpen: async source => { opened.push(source); } }), { source: 'serpapi' });
  const button = ctx.root.querySelector('[data-action="application"]');
  const note = ctx.root.querySelector('[data-info="application"]');
  assert.equal(button.disabled, true);
  assert.match(note.textContent, /暂无固定申请链接/);
  // The explanation must not fabricate an address for the missing mapping.
  assert.doesNotMatch(note.textContent, /https?:/);
  button.click(); await flush();
  assert.deepEqual(opened, []);
  ctx.window.close();
});

test('unsupported platform pre-disables opening and offers the fixed link for manual copy', async () => {
  const ctx = setup(), opened = [];
  await mountCredentials(ctx.root, api({ credentialStatus: async () => status(false, { key_application_available: true, key_application_open_supported: false, key_application_url: 'https://api.search.brave.com/app/keys' }), credentialApplicationOpen: async source => { opened.push(source); } }), { source: 'brave' });
  const button = ctx.root.querySelector('[data-action="application"]');
  const note = ctx.root.querySelector('[data-info="application"]');
  assert.equal(button.disabled, true, 'disabled before any click, not failing after');
  assert.match(note.textContent, /无法直接打开系统浏览器/);
  assert.match(note.textContent, /https:\/\/api\.search\.brave\.com\/app\/keys/);
  button.click(); await flush();
  assert.deepEqual(opened, []);
  ctx.window.close();
});

test('browser launch failure shows the trusted fixed link for manual copy and retry clears it', async () => {
  const ctx = setup(); let attempts = 0;
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(false, { key_application_available: true, key_application_open_supported: true, key_application_url: 'https://app.tavily.com/' }),
    credentialApplicationOpen: async () => { attempts += 1; if (attempts === 1) throw coded('credential_application_failed', '申请链接打开失败'); },
  }));
  const button = ctx.root.querySelector('[data-action="application"]');
  const fallback = ctx.root.querySelector('[data-application-fallback]');
  const link = ctx.root.querySelector('[data-application-url]');
  assert.equal(fallback.hidden, true, 'no link shown before any failure');
  button.click(); await flush2();
  assert.equal(attempts, 1);
  assert.equal(fallback.hidden, false, 'failure exposes the copyable link');
  assert.equal(link.value, 'https://app.tavily.com/');
  assert.equal(link.readOnly, true);
  assert.doesNotMatch(ctx.root.querySelector('[data-info="error"]').textContent, /已打开/);
  assert.equal(button.disabled, false, 'retry stays available after a failed launch');
  button.click(); await flush2();
  assert.equal(attempts, 2);
  assert.equal(fallback.hidden, true, 'successful retry clears the failure and the link');
  assert.equal(ctx.root.querySelector('[data-info="error"]').textContent, '');
  ctx.window.close();
});

test('a failed launch without a trusted mapping never creates a link', async () => {
  const ctx = setup();
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(false, { key_application_available: true, key_application_open_supported: true }),
    credentialApplicationOpen: async () => { throw coded('credential_application_failed', ''); },
  }));
  const button = ctx.root.querySelector('[data-action="application"]');
  button.click(); await flush2();
  assert.equal(ctx.root.querySelector('[data-application-fallback]').hidden, true);
  assert.equal(ctx.root.querySelector('[data-application-url]').value, '');
  // An unknown link must not fall back to some invented or http-prefixed address.
  assert.doesNotMatch(ctx.root.textContent, /https?:\/\//);
  ctx.window.close();
});

test('the fallback link is the mapping URL, never an address carried by the error text', async () => {
  const ctx = setup(); const opened = [];
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(false, { key_application_available: true, key_application_open_supported: true, key_application_url: 'https://dashboard.exa.ai/api-keys' }),
    credentialApplicationOpen: async source => {
      opened.push(source);
      throw coded('credential_application_failed', 'https://attacker.example.invalid/?key=leak');
    },
  }), { source: 'exa' });
  ctx.root.querySelector('[data-action="application"]').click(); await flush2();
  assert.deepEqual(opened, ['exa'], 'the launch request carries only the source identifier');
  assert.equal(ctx.root.querySelector('[data-application-url]').value, 'https://dashboard.exa.ai/api-keys');
  assert.doesNotMatch(ctx.root.textContent, /attacker\.example\.invalid/, 'error text never becomes page content');
  assert.equal(ctx.root.querySelector('a[href*="attacker"]'), null);
  assert.equal(ctx.root.querySelector('[data-application-fallback] a'), null, 'the fallback is selectable text, never a launcher');
  ctx.window.close();
});

test('a successful retry keeps an unrelated error message that arrived meanwhile', async () => {
  const ctx = setup(); let attempts = 0;
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(false, { key_application_available: true, key_application_open_supported: true, key_application_url: 'https://app.tavily.com/' }),
    credentialTest: async () => { throw coded('credential_test_failed', 'Test worker failed'); },
    credentialApplicationOpen: async () => { attempts += 1; if (attempts === 1) throw coded('credential_application_failed', ''); },
  }));
  const button = ctx.root.querySelector('[data-action="application"]');
  const slot = ctx.root.querySelector('[data-info="error"]');
  button.click(); await flush2();
  assert.equal(slot.textContent, '无法打开系统浏览器，请重试或手动复制固定申请链接。');
  assert.equal(ctx.root.querySelector('[data-application-fallback]').hidden, false);
  ctx.root.querySelector('[data-action="test"]').click(); await flush2();
  assert.match(slot.textContent, /凭据测试启动失败/);
  button.click(); await flush2();
  assert.equal(attempts, 2);
  assert.equal(ctx.root.querySelector('[data-application-fallback]').hidden, true);
  assert.match(slot.textContent, /凭据测试启动失败/, 'only the launch failure is cleared');
  ctx.window.close();
});

test('repeated clicks while a launch is in flight start only one browser open', async () => {
  const ctx = setup(); let opens = 0, release;
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(false, { key_application_available: true, key_application_open_supported: true, key_application_url: 'https://app.tavily.com/' }),
    credentialApplicationOpen: () => { opens += 1; return new Promise(resolve => { release = resolve; }); },
  }));
  const button = ctx.root.querySelector('[data-action="application"]');
  button.click(); button.click(); button.click(); await flush();
  assert.equal(opens, 1);
  assert.equal(button.disabled, true, 'button is held while the launch is in flight');
  release(); await flush2();
  assert.equal(button.disabled, false);
  ctx.window.close();
});

test('application entry stays disabled and pending while the metadata query is in flight', async () => {
  const ctx = setup(), opened = [];
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const mounting = mountCredentials(ctx.root, api({
    credentialStatus: async () => { await gate; return status(false, { key_application_available: true }); },
    credentialApplicationOpen: async source => { opened.push(source); },
  }), { source: 'tavily' });
  await flush();
  const button = ctx.root.querySelector('[data-action="application"]');
  const note = ctx.root.querySelector('[data-info="application"]');
  // An unconfirmed entry must never be clickable or claim a definite state.
  assert.equal(button.disabled, true);
  assert.match(note.textContent, /正在确认申请链接与打开能力/);
  assert.doesNotMatch(note.textContent, /暂无固定申请链接|无法直接打开系统浏览器/);
  button.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true })); await flush();
  assert.deepEqual(opened, [], 'no open request from an unconfirmed entry');
  release(); await mounting; await flush();
  assert.equal(button.disabled, false);
  assert.match(note.textContent, /使用系统浏览器打开固定申请链接/);
  ctx.window.close();
});

test('failed metadata query is unconfirmed with retry, and retry recovers each accurate outcome', async () => {
  const outcomes = [
    [{ key_application_available: true, key_application_open_supported: true }, /使用系统浏览器打开固定申请链接/, false],
    [{ key_application_available: false }, /该搜索源暂无固定申请链接/, true],
    [{ key_application_available: true, key_application_open_supported: false, key_application_url: 'https://api.search.brave.com/app/keys' }, /无法直接打开系统浏览器/, true],
  ];
  for (const [extra, expected, disabled] of outcomes) {
    const ctx = setup(); let calls = 0;
    await mountCredentials(ctx.root, api({
      credentialStatus: async () => { calls += 1; if (calls === 1) throw new Error('status failed'); return status(false, extra); },
    }), { source: 'brave' });
    const button = ctx.root.querySelector('[data-action="application"]');
    const note = ctx.root.querySelector('[data-info="application"]');
    // The failed query is neither "no link" nor "platform unsupported".
    assert.equal(button.disabled, true);
    assert.match(note.textContent, /无法确认申请链接与打开能力/);
    assert.match(note.textContent, /刷新已保存值/);
    assert.doesNotMatch(note.textContent, /暂无固定申请链接|无法直接打开系统浏览器/);
    // The existing refresh control is the retry entry.
    ctx.root.querySelector('[data-action="refresh"]').click(); await flush2();
    assert.equal(button.disabled, disabled, JSON.stringify(extra));
    assert.match(note.textContent, expected);
    ctx.window.close();
  }
});

test('an earlier metadata response cannot override the newer application state', async () => {
  const ctx = setup(); const resolvers = [];
  const mounted = mountCredentials(ctx.root, api({
    credentialStatus: () => new Promise(resolve => resolvers.push(resolve)),
  }), { source: 'tavily' });
  await flush();
  resolvers[0](status(false, { key_application_available: true, key_application_open_supported: true, key_application_url: 'https://app.tavily.com/' }));
  await mounted; await flush2();
  const button = ctx.root.querySelector('[data-action="application"]');
  const note = ctx.root.querySelector('[data-info="application"]');
  assert.equal(button.disabled, false);
  // Start a refresh, then a second request while the first is still in flight.
  ctx.root.querySelector('[data-action="refresh"]').click(); await flush();
  ctx.root.querySelector('[data-action="refresh"]').dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true })); await flush();
  const newer = resolvers[resolvers.length - 1], older = resolvers[1];
  newer(status(false, { key_application_available: false })); await flush2();
  assert.equal(button.disabled, true);
  assert.match(note.textContent, /该搜索源暂无固定申请链接/);
  // The older answer (link available) arrives last and must not revive the entry.
  older(status(false, { key_application_available: true, key_application_open_supported: true, key_application_url: 'https://app.tavily.com/' }));
  await flush2();
  assert.equal(button.disabled, true, 'stale answer must not re-enable a withdrawn entry');
  assert.match(note.textContent, /该搜索源暂无固定申请链接/);
  assert.doesNotMatch(note.textContent, /https:/);
  ctx.window.close();
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
  assert.deepEqual(draftInputs(ctx.root), [], 'no draft row can be opened while reads are unhealthy');
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
  assert.equal(ctx.root.querySelector('[data-action="add"]').disabled, true);
  ctx.root.querySelector('[data-action="add"]').click();
  assert.equal(ctx.root.querySelector('[data-action="remove-draft"]'), null, 'no draft row to remove');
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
    'github_repos', 'github_code', 'hackernews', 'stackoverflow', 'sov2ex', 'twitter',
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
    [status(true, { effective_source: 'env', env_var: 'TAVILY_API_KEY' }), '环境变量 TAVILY_API_KEY'],
    [status(true, { effective_source: 'env', env_var: '' }), '环境变量'],
    [status(true, { effective_source: 'file', file_key_count: 3 }), 'Key 文件（~/.multi-search/keys.json）中的 3 个 Key'],
    [status(true), 'Key 文件（~/.multi-search/keys.json）'],
    [status(false), '未配置'],
    [status(true, { effective_source: 'future_store' }), '未知来源（future_store）'],
  ];
  for (const [view, label] of cases) {
    const ctx = setup();
    await mountCredentials(ctx.root, api({ credentialStatus: async () => view, credentialRead: async () => ({ value: KEY, snapshot: 's' }) }));
    assert.equal(ctx.root.querySelector('[data-status="source"]').textContent, label);
    ctx.window.close();
  }
});

test('the page states where keys are stored and has no platform-capability banner', async () => {
  const ctx = setup();
  await mountCredentials(ctx.root, api());
  assert.equal(ctx.root.querySelector('[data-keys-file-note]').textContent, 'Key 以明文保存在 ~/.multi-search/keys.json（仅当前用户可读写）');
  assert.equal(ctx.root.querySelector('[data-capability]'), null);
  assert.doesNotMatch(ctx.root.textContent, /DPAPI|SQLite|凭据库|旧 Key 文件/);
  // Writes are available on every platform once the rows were read.
  assert.equal(ctx.root.querySelector('[data-action="save"]').disabled, false);
  ctx.window.close();
});

// 状态查询的加载、失败与重试恢复：可控制完成顺序的响应。

test('status failure keeps writes disabled until a status refresh succeeds', async () => {
  const ctx = setup(); let failStatus = true;
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => { if (failStatus) throw '状态读取失败'; return status(true); },
    credentialRead: async () => ({ value: KEY, snapshot: 's' }),
  }));
  assert.equal(ctx.root.querySelector('[data-action="add"]').disabled, true);
  assert.deepEqual(draftInputs(ctx.root), []);
  assert.equal(ctx.root.querySelector('[data-info="error"]').textContent, '状态读取失败');
  // Store status is not fabricated as absent/present.
  assert.equal(ctx.root.querySelector('[data-status="store"]').textContent, '');
  failStatus = false;
  ctx.root.querySelector('[data-action="refresh"]').click(); await flush2();
  draftInputs(ctx.root)[0].value = KEY;
  ctx.root.querySelector('[data-action="refresh"]').click(); await flush2();
  assert.equal(ctx.root.querySelector('[data-action="save"]').disabled, false);
  assert.equal(draftRows(ctx.root)[0].value, KEY, 'drafts survive a refresh');
  ctx.window.close();
});

test('writes stay disabled while the first status is loading', async () => {
  const ctx = setup();
  let resolveStatus;
  const pending = new Promise(resolve => { resolveStatus = resolve; });
  const mounted = mountCredentials(ctx.root, api({
    credentialStatus: () => pending,
    credentialRead: async () => ({ value: KEY, snapshot: 's' }),
  }));
  await flush();
  assert.equal(ctx.root.querySelector('[data-action="add"]').disabled, true, 'no brief writable window');
  assert.deepEqual(draftInputs(ctx.root), []);
  resolveStatus(status(true));
  await mounted; await flush2();
  assert.equal(ctx.root.querySelector('[data-action="add"]').disabled, false);
  draftInputs(ctx.root);
  assert.equal(ctx.root.querySelector('[data-action="save"]').disabled, false);
  ctx.window.close();
});

test('an unreadable keys file shows its reason and keeps writes disabled', async () => {
  const ctx = setup(); const calls = [];
  const broken = { ...status(false), store: { state: 'unavailable', saved_at: null, error: '密钥文件不是有效的 JSON 对象，未保存；请先修复 ~/.multi-search/keys.json' } };
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => broken,
    credentialRead: async () => { throw '密钥文件不是有效的 JSON 对象，未保存；请先修复 ~/.multi-search/keys.json'; },
    credentialAppend: async () => { calls.push('append'); return broken; },
  }));
  assert.equal(ctx.root.querySelector('[data-status="store"]').textContent, 'Key 文件无法读取');
  assert.match(ctx.root.querySelector('[data-info="error"]').textContent, /请先修复 ~\/\.multi-search\/keys\.json/);
  assert.deepEqual(draftInputs(ctx.root), [], 'no draft row can be opened for a corrupt file');
  submit(ctx); await flush2();
  assert.deepEqual(calls, [], 'a corrupt file is never written from the UI');
  ctx.window.close();
});

test('a slower older refresh cannot overwrite a newer outcome', async () => {
  const ctx = setup(); const resolvers = [];
  const mounted = mountCredentials(ctx.root, api({
    credentialStatus: () => new Promise(resolve => resolvers.push(resolve)),
    credentialRead: async () => ({ value: KEY, snapshot: 's' }),
  }));
  await flush();
  resolvers[0](status(true));
  await mounted; await flush2();
  ctx.root.querySelector('[data-action="refresh"]').click();
  await flush();
  ctx.root.querySelector('[data-action="refresh"]').dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true }));
  await flush();
  const newer = resolvers[resolvers.length - 1], older = resolvers[1];
  newer(status(true, { effective_source: 'env', env_var: 'NEW_VAR' }));
  await flush2();
  older(status(false, { effective_source: 'none' }));
  await flush2();
  assert.equal(ctx.root.querySelector('[data-status="source"]').textContent, '环境变量 NEW_VAR', 'newer outcome stays');
  assert.equal(ctx.root.querySelector('[data-action="save"]').disabled, false);
  ctx.window.close();
});

test('no write request is issued during a failed status window', async () => {
  const ctx = setup(); const writes = [];
  let fail = true;
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => { if (fail) throw 'x'; return status(true); },
    credentialRead: async () => ({ value: KEY, snapshot: 's' }),
    credentialAppend: async () => { writes.push('append'); return status(true); },
  }));
  assert.deepEqual(draftInputs(ctx.root), [], 'no draft row while status is unknown');
  submit(ctx); await flush2();
  assert.equal(writes.length, 0, 'no append while status is unknown');
  fail = false;
  ctx.root.querySelector('[data-action="refresh"]').click(); await flush2();
  draftInputs(ctx.root)[0].value = KEY;
  submit(ctx); await flush2();
  assert.equal(writes.length, 1, 'write allowed once status is known');
  ctx.window.close();
});

test('a slow launch that resolves after the editor is disposed cannot write into the next target', async () => {
  const ctx = setup(); let release, rejectOpen;
  const mounted = await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(false, { key_application_available: true, key_application_open_supported: true, key_application_url: 'https://app.tavily.com/' }),
    credentialApplicationOpen: () => new Promise((resolve, reject) => { release = resolve; rejectOpen = reject; }),
  }), { source: 'tavily' });
  const errorSlot = ctx.root.querySelector('[data-info="error"]');
  ctx.root.querySelector('[data-action="application"]').click(); await flush();
  // Switch the card away: the old editor is disposed while its launch is still pending.
  mounted.dispose();
  // The next target mounts into the same container and shows its own (empty) slots.
  ctx.root.innerHTML = '';
  const next = await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(false, { key_application_available: true, key_application_open_supported: true, key_application_url: 'https://dashboard.exa.ai/api-keys' }),
  }), { source: 'exa' });
  rejectOpen(coded('credential_application_failed', 'stale failure from tavily'));
  await flush2();
  const nextSlot = ctx.root.querySelector('[data-info="error"]');
  assert.equal(nextSlot.textContent, '', 'the old launch failure must not reach the new target');
  assert.equal(ctx.root.querySelector('[data-application-fallback]').hidden, true, 'the old fallback must not appear on the new target');
  assert.equal(ctx.root.querySelector('[data-application-url]').value, '', 'no old link is written into the new target');
  assert.doesNotMatch(ctx.root.textContent, /stale failure from tavily|app\.tavily\.com/);
  next.dispose();
  ctx.window.close();
});

test('a new editor for another source starts with no in-flight lock or fallback from the old one', async () => {
  const ctx = setup(); const opened = []; let release;
  const first = await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(false, { key_application_available: true, key_application_open_supported: true, key_application_url: 'https://app.tavily.com/' }),
    credentialApplicationOpen: source => { opened.push(source); return new Promise(resolve => { release = resolve; }); },
  }), { source: 'tavily' });
  ctx.root.querySelector('[data-action="application"]').click(); await flush();
  first.dispose();
  ctx.root.replaceChildren();
  await mountCredentials(ctx.root, api({
    credentialStatus: async () => status(false, { key_application_available: true, key_application_open_supported: true, key_application_url: 'https://dashboard.exa.ai/api-keys' }),
    credentialApplicationOpen: async source => { opened.push(source); },
  }), { source: 'exa' });
  const button = ctx.root.querySelector('[data-action="application"]');
  assert.equal(button.disabled, false, 'the old in-flight launch does not lock the new target');
  button.click(); await flush2();
  assert.deepEqual(opened, ['tavily', 'exa']);
  release();
  ctx.window.close();
});
