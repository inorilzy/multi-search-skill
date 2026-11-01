import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountSources } from '../ui/sources.js';

const ALL = ['baidu', 'brave', 'parallel', 'tavily', 'exa', 'firecrawl', 'serpapi', 'github_repos', 'github_code', 'hackernews', 'stackoverflow', 'sov2ex', 'twitter'];
const KEYED = [...ALL.slice(0, 9), 'stackoverflow'];

const absent = { source: '', store: { state: 'absent', saved_at: null, error: '' }, effective_source: 'none', key_application_available: false };
const settings = (overrides = {}) => ({ route: 'default', timeout: 60, disabled_sources: [], twitter_cookies_path: null, route_ok: true, ...overrides });

function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root };
}

const flush2 = async () => { await flush(); await flush(); };
const pick = async (root, name) => { const button = root.querySelector(`[data-pick="${name}"]`); if (button.getAttribute('aria-expanded') !== 'true') button.click(); await flush(); };
const detailOf = root => root.querySelector('[data-source-row][data-expanded="true"] [data-source-detail]');

test('sources page lists every allowlisted source once and mounts only the selected detail', async () => {
  const { window, root } = setup();
  const seen = [];
  const api = {
    settingsView: async () => settings(),
    credentialStatus: async source => { seen.push(source); return absent; },
    credentialTest: async () => ({ result: 'success', message: '' }),
  };
  const mounted = await mountSources(root, api);

  const rows = [...root.querySelectorAll('[data-source-row]')].map(node => node.getAttribute('data-source-row'));
  assert.deepEqual(rows, ALL, 'all thirteen sources appear as list rows in a stable order');
  assert.equal(root.querySelectorAll('[data-source-row][data-expanded="true"]').length, 0, 'no detail is expanded on entry');
  assert.equal(root.querySelectorAll('[data-source-detail] [data-field="key"]').length, 0);
  await pick(root, 'baidu');
  assert.equal(root.querySelectorAll('[data-source-detail] [data-action="add"]').length, 1, 'only one source detail is mounted at a time');

  for (const name of KEYED) {
    await pick(root, name);
    assert.ok(detailOf(root).querySelector('[data-action="test"]'), `${name} detail exposes a test control`);
    assert.ok(detailOf(root).querySelector('[data-action="add"]'), `${name} detail exposes its add-key control`);
  }
  assert.deepEqual(seen.slice(0, KEYED.length), KEYED, 'each keyed source is queried for the initial overview');
  assert.deepEqual(seen.slice(KEYED.length), KEYED, 'each keyed source refreshes when its detail opens');

  await pick(root, 'stackoverflow');
  assert.match(detailOf(root).textContent, /无需 API Key 也能使用/, 'an optional key says the source works without one');

  for (const name of ALL.slice(9).filter(name => !KEYED.includes(name))) {
    await pick(root, name);
    const detail = detailOf(root);
    assert.ok(detail.querySelector('[data-action="test"]'), `${name} detail exposes a test control`);
    assert.equal(detail.querySelector('[data-field="key"]'), null, `${name} needs no key field`);
    assert.match(detail.textContent, name === 'twitter' ? /Cookie.*路径/ : /无需 API Key/);
  }
  assert.ok(!root.textContent.includes('Jina'), 'Jina is out of scope for the sources page');
  mounted.dispose();
  window.close();
});

test('per-source test outcomes map to their own source and never leak into a rebuilt detail', async () => {
  const { window, root } = setup();
  const stored = { ...absent, store: { state: 'present', saved_at: 1, error: '' }, effective_source: 'file' };
  const outcomes = { tavily: 'success', brave: 'auth_failed', exa: 'quota' };
  const resolvers = {};
  const api = {
    settingsView: async () => settings(),
    credentialStatus: async () => stored,
    credentialTest: source => new Promise(resolve => { resolvers[source] = () => resolve({ result: outcomes[source], message: '' }); }),
  };
  await mountSources(root, api);

  const expected = {
    tavily: '测试成功：Tavily 本次使用 Key 文件（~/.multi-search/keys.json）。',
    brave: '认证失败：Brave 搜索 拒绝了该 Key。',
    exa: '额度不足：Exa 额度已用尽。',
  };
  for (const name of ['tavily', 'brave', 'exa']) {
    await pick(root, name);
    detailOf(root).querySelector('[data-action="test"]').click();
    await flush();
    resolvers[name]();
    await flush();
    assert.equal(detailOf(root).querySelector('[data-status="test"]').textContent, expected[name]);
  }

  // Late response from a source whose detail was replaced must not overwrite the current one.
  await pick(root, 'tavily');
  detailOf(root).querySelector('[data-action="test"]').click();
  await flush();
  await pick(root, 'brave');
  assert.equal(detailOf(root).querySelector('[data-status="test"]').textContent, expected.brave, 'same provenance retains only this source’s result');
  resolvers.tavily();
  await flush();
  assert.equal(detailOf(root).querySelector('[data-status="test"]').textContent, expected.brave, 'stale outcome is ignored');
  window.close();
});

test('all thirteen sources expose independent explicit test controls', async () => {
  const { window, root } = setup();
  const called = [];
  const api = {
    settingsView: async () => settings(),
    credentialStatus: async () => absent,
    credentialTest: async source => { called.push(source); return { result: 'success', message: source }; },
  };
  const mounted = await mountSources(root, api);
  for (const name of ALL) {
    await pick(root, name);
    const detail = detailOf(root);
    detail.querySelector('[data-action="test"]').click();
    await flush();
    assert.match(detail.querySelector('[data-status="test"]').textContent, /测试成功/);
    assert.equal(detail.querySelector('[data-info="test"]').textContent, name);
  }
  assert.equal(new Set(called).size, 13);
  mounted.dispose();
  window.close();
});

test('an enable toggle preserves route, timeout and the Twitter path it was not editing', async () => {
  const { window, root } = setup();
  let sent = null;
  const current = settings({ route: 'dev', timeout: 25, disabled_sources: ['exa'], twitter_cookies_path: 'C:/cookies.json' });
  const api = {
    credentialStatus: async () => absent,
    settingsView: async () => current,
    settingsSave: async input => { sent = input; return settings({ ...input }); },
  };
  await mountSources(root, api);
  const toggle = root.querySelector('[data-toggle="brave"]');
  toggle.checked = false;
  toggle.dispatchEvent(new window.Event('change'));
  await flush();
  assert.deepEqual(sent, {
    route: 'dev',
    timeout: null,
    disabled_sources: ['exa', 'brave'],
    twitter_cookies_path: 'C:/cookies.json',
  }, 'the toggle must not clobber settings it did not touch; timeout null keeps the stored value');
  assert.equal(root.querySelector('[data-toggle="brave"]').checked, false);
  window.close();
});

test('a rejected toggle save reverts the switch and keeps the error visible', async () => {
  const { window, root } = setup();
  const api = {
    settingsView: async () => settings(),
    credentialStatus: async () => absent,
    settingsSave: async () => { throw '现有配置文件无法读取，保存已被阻止。'; },
  };
  await mountSources(root, api);
  const toggle = root.querySelector('[data-toggle="exa"]');
  toggle.checked = false;
  toggle.dispatchEvent(new window.Event('change'));
  await flush();
  assert.equal(root.querySelector('[data-toggle="exa"]').checked, true, 'the switch reverts when the save is rejected');
  assert.match(root.querySelector('[data-source-row="exa"] [data-row-error]').textContent, /无法读取/);
  window.close();
});

test('overview, search, filters and keyboard shortcut use real source state', async () => {
  const { window, root } = setup();
  const mounted = await mountSources(root, {
    settingsView: async () => settings({ disabled_sources: ['exa', 'twitter'] }),
    credentialStatus: async source => source === 'baidu' ? { ...absent, effective_source: 'file', store: { state: 'present', saved_at: 1, error: '' } } : absent,
  });
  assert.equal(root.querySelector('[data-stat="enabled"]').textContent, '11');
  assert.equal(root.querySelector('[data-stat="configured"]').textContent, '1');
  assert.equal(root.querySelector('[data-stat="absent"]').textContent, '10');
  assert.equal(root.querySelectorAll('[data-source-row][data-expanded="true"]').length, 0, 'entering the page expands nothing');
  root.querySelector('[data-filter="unconfigured"]').click();
  const visible = () => [...root.querySelectorAll('[data-source-row]')].filter(row => !row.hidden);
  assert.equal(visible().length, 10);
  assert.ok(!visible().some(row => row.dataset.sourceRow === 'hackernews'));
  const search = root.querySelector('[data-search]');
  search.value = 'Cookie';
  search.dispatchEvent(new window.Event('input'));
  assert.deepEqual(visible().map(row => row.dataset.sourceRow), ['twitter']);
  search.value = 'no-match';
  search.dispatchEvent(new window.Event('input'));
  assert.equal(root.querySelector('[data-empty]').hidden, false);
  window.document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'k', ctrlKey: true, cancelable: true }));
  assert.equal(window.document.activeElement, search);
  mounted.dispose();
  window.close();
});

test('unknown settings never pretend sources are enabled', async () => {
  const { window, root } = setup();
  await mountSources(root, { settingsView: async () => { throw Error('offline'); }, credentialStatus: async () => absent });
  assert.equal(root.querySelector('[data-stat="enabled"]').textContent, '—');
  assert.ok([...root.querySelectorAll('[data-toggle]')].every(input => input.disabled));
  assert.match(root.querySelector('[data-list-error]').textContent, /状态未知/);
  window.close();
});

test('queued source changes reread current settings and preserve both toggles', async () => {
  const { window, root } = setup();
  let current = settings();
  let reads = 0;
  await mountSources(root, {
    credentialStatus: async () => absent,
    settingsView: async () => { reads += 1; return { ...current, disabled_sources: [...current.disabled_sources] }; },
    settingsSave: async input => { await flush(); current = settings({ ...input, timeout: input.timeout ?? current.timeout }); return current; },
  });
  current = settings({ route: 'dev', timeout: 22, twitter_cookies_path: 'new-cookie-path' });
  for (const source of ['exa', 'brave']) {
    const input = root.querySelector(`[data-toggle="${source}"]`);
    input.checked = false;
    input.dispatchEvent(new window.Event('change'));
  }
  for (let i = 0; i < 6; i += 1) await flush();
  assert.deepEqual(current.disabled_sources, ['exa', 'brave']);
  assert.equal(current.route, 'dev');
  assert.equal(current.timeout, 22);
  assert.equal(current.twitter_cookies_path, 'new-cookie-path');
  assert.equal(reads, 3);
  window.close();
});

test('row testing sends one request and saving invalidates row success', async () => {
  const { window, root } = setup();
  let calls = 0;
  const stored = { ...absent, effective_source: 'file', store: { state: 'present', saved_at: 1, error: '' } };
  await mountSources(root, {
    settingsView: async () => settings(),
    credentialStatus: async () => stored,
    credentialTest: async () => { calls += 1; return { result: 'success', message: 'synthetic response' }; },
    credentialRead: async () => ({ value: 'masked-1', snapshot: 'r1' }),
    credentialAppend: async () => ({ ...stored, store: { state: 'present', saved_at: 2, error: '' } }),
  });
  const row = root.querySelector('[data-source-row="tavily"]');
  row.querySelector('[data-row-test]').click();
  await flush(); await flush();
  assert.equal(calls, 1);
  assert.equal(row.querySelector('[data-row-result]').dataset.kind, 'success');
  assert.match(detailOf(root).querySelector('[data-status="test"]').textContent, /测试成功/);
  detailOf(root).querySelector('[data-action="add"]').click();
  detailOf(root).querySelector('[data-field="key"]').value = 'synthetic';
  detailOf(root).querySelector('form').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush(); await flush();
  assert.equal(row.querySelector('[data-row-result]').dataset.kind, 'idle');
  assert.equal(calls, 1);
  window.close();
});

function flush() { return new Promise(resolve => setTimeout(resolve, 0)); }

test('a failed test shows its full error inside the expanded detail, not only on hover', async () => {
  const { window, root } = setup();
  const message = '连接被拒绝：请检查网络代理后重试（synthetic）';
  await mountSources(root, {
    settingsView: async () => settings(),
    credentialStatus: async () => absent,
    credentialTest: async () => ({ result: 'network', message }),
  });
  await pick(root, 'hackernews');
  const detail = detailOf(root);
  detail.querySelector('[data-action="test"]').click();
  await flush(); await flush();

  const result = detail.querySelector('.test-result');
  assert.equal(result.dataset.kind, 'error', 'a failed test is marked as an error');
  assert.match(result.textContent, /连接被拒绝：请检查网络代理后重试/, 'the complete message is rendered as visible text in the expanded detail');
  assert.doesNotMatch(result.textContent, /测试成功/, 'a failure never reads as success');

  const row = root.querySelector('[data-source-row="hackernews"]');
  assert.match(row.querySelector('[data-row-result]').getAttribute('title') || '', /连接被拒绝/, 'the row hover title still carries the full message');
  window.close();
});

test('row test button reports its source, blocks repeat submits while running and recovers', async () => {
  const { window, root } = setup();
  let calls = 0;
  let resolveTest;
  const api = {
    settingsView: async () => settings(),
    credentialStatus: async () => absent,
    credentialTest: () => new Promise(resolve => { calls += 1; resolveTest = resolve; }),
  };
  await mountSources(root, api);
  const row = root.querySelector('[data-source-row="hackernews"]');
  const button = row.querySelector('[data-row-test]');
  assert.equal(button.getAttribute('aria-label'), '测试 Hacker News', 'the row test button names its source');
  assert.equal(button.disabled, false, 'idle button is enabled');

  button.click();
  await flush(); await flush();
  assert.equal(row.querySelector('[data-row-result]').dataset.kind, 'running', 'row state enters running');
  assert.equal(button.disabled, true, 'running keeps the trigger disabled');
  button.click();
  await flush();
  assert.equal(calls, 1, 'a disabled trigger cannot submit a second test');

  resolveTest({ result: 'error', message: '缺少 Key：请先保存。' });
  await flush(); await flush();
  assert.equal(row.querySelector('[data-row-result]').dataset.kind, 'error');
  assert.match(row.querySelector('[data-row-result] strong').textContent, /测试失败/);
  assert.match(row.querySelector('[data-row-result]').getAttribute('title'), /缺少 Key/, 'the full error text stays readable via the title');
  assert.doesNotMatch(row.querySelector('[data-row-result]').textContent, /测试成功/, 'a failed test never reports success');
  assert.equal(button.disabled, false, 'a finished test restores the trigger');
  window.close();
});

test('keyless detail test is keyboard reachable, sends one request and restores the button', async () => {
  const { window, root } = setup();
  let calls = 0;
  let resolveTest;
  await mountSources(root, {
    settingsView: async () => settings(),
    credentialStatus: async () => absent,
    credentialTest: () => new Promise(resolve => { calls += 1; resolveTest = resolve; }),
  });
  await pick(root, 'hackernews');
  const detail = detailOf(root);
  const button = detail.querySelector('[data-action="test"]');
  button.focus();
  assert.equal(window.document.activeElement, button, 'the detail test control takes focus');
  assert.equal(button.disabled, false);

  button.click();
  await flush();
  assert.equal(button.disabled, true, 'running disables the detail control');
  assert.equal(detail.querySelector('[data-status="test"]').textContent, '正在测试');
  assert.equal(detail.querySelector('[data-test-result], .test-result').dataset.kind, 'running');
  button.click();
  await flush();
  assert.equal(calls, 1, 'no duplicate request while running');

  resolveTest({ result: 'success', message: 'synthetic' });
  await flush(); await flush();
  assert.equal(button.disabled, false, 'completion re-enables the control');
  assert.match(detail.querySelector('[data-status="test"]').textContent, /测试成功/);
  window.close();
});

test('expand and collapse are real buttons with accessible names that flip with state', async () => {
  const { window, root } = setup();
  await mountSources(root, {
    settingsView: async () => settings(),
    credentialStatus: async () => absent,
  });
  const row = root.querySelector('[data-source-row="brave"]');
  const expand = row.querySelector('[data-expand]');
  const pick = row.querySelector('[data-pick]');
  for (const el of [expand, pick]) assert.equal(el.tagName, 'BUTTON', 'expand controls stay keyboard operable');
  assert.equal(expand.getAttribute('aria-label'), '展开 Brave 搜索');
  assert.equal(expand.getAttribute('aria-expanded'), 'false');
  assert.equal(expand.getAttribute('aria-controls'), 'detail-brave');

  expand.click();
  await flush();
  assert.equal(row.dataset.expanded, 'true');
  assert.equal(expand.getAttribute('aria-expanded'), 'true');
  assert.equal(expand.getAttribute('aria-label'), '收起 Brave 搜索');
  assert.equal(row.querySelector('[data-source-detail]').hidden, false);

  expand.click();
  await flush();
  assert.equal(row.dataset.expanded, 'false');
  assert.equal(expand.getAttribute('aria-expanded'), 'false');
  assert.equal(expand.getAttribute('aria-label'), '展开 Brave 搜索');
  assert.equal(row.querySelector('[data-source-detail]').hidden, true);
  window.close();
});

test('every row test and expand control exposes its source in the accessible name', async () => {
  const { window, root } = setup();
  const mounted = await mountSources(root, {
    settingsView: async () => settings(),
    credentialStatus: async () => absent,
  });
  const labels = { baidu: 'Baidu AI 搜索', brave: 'Brave 搜索', parallel: 'Parallel', tavily: 'Tavily', exa: 'Exa', firecrawl: 'Firecrawl', serpapi: 'SerpAPI', github_repos: 'GitHub 仓库', github_code: 'GitHub 代码', hackernews: 'Hacker News', stackoverflow: 'Stack Overflow', sov2ex: 'V2EX', twitter: 'Twitter / X' };
  for (const [source, label] of Object.entries(labels)) {
    const row = root.querySelector(`[data-source-row="${source}"]`);
    assert.equal(row.querySelector('[data-row-test]').getAttribute('aria-label'), `测试 ${label}`, source);
    assert.match(row.querySelector('[data-expand]').getAttribute('aria-label'), new RegExp(`^(展开|收起) ${label.replace(/[/.]/g, '\\$&')}`), source);
  }
  mounted.dispose();
  window.close();
});

test('disposal or navigation abort releases the Ctrl K shortcut', async () => {
  const { window, root } = setup();
  const api = { settingsView: async () => settings(), credentialStatus: async () => absent };
  const mounted = await mountSources(root, api);
  mounted.dispose();
  window.document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'k', ctrlKey: true, cancelable: true }));
  assert.notEqual(window.document.activeElement, root.querySelector('[data-search]'));

  const second = setup();
  const controller = new second.window.AbortController();
  await mountSources(second.root, api, { signal: controller.signal });
  controller.abort();
  second.window.document.dispatchEvent(new second.window.KeyboardEvent('keydown', { key: 'k', ctrlKey: true, cancelable: true }));
  assert.notEqual(second.window.document.activeElement, second.root.querySelector('[data-search]'));
  window.close(); second.window.close();
});

// 03 Key 文件状态不误伤生效来源展示和连接测试。

test('env effective source is shown as 环境变量生效 even when the keys file is unreadable', async () => {
  const { window, root } = setup();
  const broken = { ...absent, effective_source: 'env', env_var: 'TAVILY_API_KEY', store: { state: 'unavailable', saved_at: null, error: 'not JSON' } };
  await mountSources(root, { settingsView: async () => settings(), credentialStatus: async () => broken });
  const row = root.querySelector('[data-source-row="tavily"]');
  assert.equal(row.querySelector('[data-row-status]').textContent, '环境变量生效');
  assert.equal(row.querySelector('[data-row-status]').dataset.kind, 'configured');
  // The test button is not disabled by the broken file.
  assert.equal(row.querySelector('[data-row-test]').disabled, false);
  window.close();
});

test('an unreadable keys file without an env key is shown as an error, not as 未配置', async () => {
  const { window, root } = setup();
  const view = { ...absent, effective_source: 'none', store: { state: 'unavailable', saved_at: null, error: 'not JSON' } };
  await mountSources(root, { settingsView: async () => settings(), credentialStatus: async () => view });
  assert.equal(root.querySelector('[data-source-row="tavily"] [data-row-status]').textContent, 'Key 文件无法读取');
  assert.equal(root.querySelector('[data-source-row="tavily"] [data-row-status]').dataset.kind, 'error');
  window.close();
});

test('file effective_source reports Key 文件生效 and tests stay enabled', async () => {
  const { window, root } = setup();
  const view = { ...absent, effective_source: 'file', file_key_count: 1, store: { state: 'present', saved_at: 1, error: '' } };
  let tested = 0;
  await mountSources(root, {
    settingsView: async () => settings(),
    credentialStatus: async () => view,
    credentialTest: async () => { tested += 1; return { result: 'success', message: '' }; },
    credentialRead: async () => ({ value: 'masked', snapshot: 's' }),
  });
  const row = root.querySelector('[data-source-row="tavily"]');
  assert.equal(row.querySelector('[data-row-status]').textContent, 'Key 文件生效');
  row.querySelector('[data-row-test]').click();
  await flush(); await flush();
  assert.equal(tested, 1, 'a file-backed source still runs the connection test');
  assert.equal(row.querySelector('[data-row-result]').dataset.kind, 'success');
  window.close();
});

test('an absent keys file does not fabricate credential errors for a keyless source test', async () => {
  const { window, root } = setup();
  let tested = 0;
  await mountSources(root, {
    settingsView: async () => settings(),
    credentialStatus: async () => absent,
    credentialTest: async source => { tested += 1; return source === 'hackernews' ? { result: 'success', message: '' } : { result: 'error', message: 'x' }; },
  });
  const row = root.querySelector('[data-source-row="hackernews"]');
  row.querySelector('[data-row-test]').click();
  await flush(); await flush();
  assert.equal(tested, 1);
  assert.equal(row.querySelector('[data-row-result]').dataset.kind, 'success');
  window.close();
});

test('a launch started on source A that fails after switching to B never writes into B', async () => {
  const { window, root } = setup();
  const present = { ...absent, store: { state: 'present', saved_at: 1, error: '' }, effective_source: 'sqlite', key_application_available: true, key_application_open_supported: true, key_application_url: 'https://app.tavily.com/' };
  const exaApp = { ...present, key_application_url: 'https://dashboard.exa.ai/api-keys' };
  const rejects = [];
  const api = {
    settingsView: async () => settings(),
    credentialStatus: async source => (source === 'exa' ? exaApp : present),
    credentialRead: async () => ({ value: '', snapshot: 's' }),
    credentialApplicationOpen: () => new Promise((_, reject) => rejects.push(reject)),
  };
  await mountSources(root, api);
  await pick(root, 'tavily');
  detailOf(root).querySelector('[data-action="application"]').click();
  await flush();
  // Switch the card to B while A's launch is still pending.
  await pick(root, 'exa');
  const exaSlot = detailOf(root).querySelector('[data-info="error"]');
  const exaApplication = detailOf(root).querySelector('[data-info="application"]').textContent;
  // A's launch now fails.
  rejects[0](Object.assign(new Error('x'), { code: 'credential_application_failed', message: 'stale tavily failure' }));
  await flush2();
  assert.equal(detailOf(root).querySelector('[data-info="error"]').textContent, exaSlot.textContent, 'B error slot unchanged');
  assert.equal(detailOf(root).querySelector('[data-info="error"]').textContent, '', 'no launch failure written into B');
  assert.equal(detailOf(root).querySelector('[data-application-fallback]').hidden, true, 'A fallback link is not shown on B');
  assert.equal(detailOf(root).querySelector('[data-application-url]').value, '', 'no A link value on B');
  assert.equal(detailOf(root).querySelector('[data-info="application"]').textContent, exaApplication, 'B application note untouched');
  assert.equal(detailOf(root).querySelector('[data-action="application"]').disabled, false, 'B button not disabled by A launch');
  assert.doesNotMatch(root.textContent, /stale tavily failure/);
  window.close();
});

test('collapsing the card with an in-flight launch drops the late result and re-expanding shows no stale feedback', async () => {
  const { window, root } = setup();
  const present = { ...absent, store: { state: 'present', saved_at: 1, error: '' }, effective_source: 'sqlite', key_application_available: true, key_application_open_supported: true, key_application_url: 'https://app.tavily.com/' };
  const opens = []; const resolves = [];
  const api = {
    settingsView: async () => settings(),
    credentialStatus: async () => present,
    credentialRead: async () => ({ value: '', snapshot: 's' }),
    credentialApplicationOpen: () => { opens.push(1); return new Promise((resolve, reject) => resolves.push({ resolve, reject })); },
  };
  await mountSources(root, api);
  await pick(root, 'tavily');
  detailOf(root).querySelector('[data-action="application"]').click();
  await flush();
  // Collapse A with its own expand control (pick() would not collapse an expanded row).
  root.querySelector('[data-source-row][data-expanded="true"] [data-expand]').click(); await flush();
  assert.equal(detailOf(root), null, 'A is collapsed');
  resolves[0].reject(Object.assign(new Error('x'), { code: 'credential_application_failed', message: 'late failure' }));
  await flush2();
  // Re-expand A: the earlier launch's failure and fallback must not reappear.
  await pick(root, 'tavily');
  assert.equal(detailOf(root).querySelector('[data-info="error"]').textContent, '', 'no stale launch error after re-expand');
  assert.equal(detailOf(root).querySelector('[data-application-fallback]').hidden, true, 'no stale fallback after re-expand');
  assert.equal(detailOf(root).querySelector('[data-action="application"]').disabled, false, 'button is usable after re-expand');
  assert.doesNotMatch(root.textContent, /late failure/);
  window.close();
});
