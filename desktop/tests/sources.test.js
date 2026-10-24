import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountSources } from '../ui/sources.js';

const ALL = ['baidu', 'brave', 'parallel', 'tavily', 'exa', 'firecrawl', 'serpapi', 'github_repos', 'hackernews', 'stackoverflow', 'sov2ex', 'twitter'];
const KEYED = ALL.slice(0, 8);

const absent = { store: { state: 'absent', saved_at: null, error: null }, effective_source: 'none', env_overrides_store: false, env_var: '', file_key_count: 0 };
const settings = (overrides = {}) => ({ route: 'default', timeout: 60, disabled_sources: [], twitter_cookies_path: null, route_ok: true, ...overrides });

function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root };
}

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
  assert.deepEqual(rows, ALL, 'all twelve sources appear as list rows in a stable order');
  assert.equal(root.querySelectorAll('[data-source-row][data-expanded="true"]').length, 0, 'no detail is expanded on entry');
  assert.equal(root.querySelectorAll('[data-source-detail] [data-field="key"]').length, 0);
  await pick(root, 'baidu');
  assert.equal(root.querySelectorAll('[data-source-detail] [data-field="key"]').length, 1, 'only one source detail is mounted at a time');

  for (const name of KEYED) {
    await pick(root, name);
    assert.ok(detailOf(root).querySelector('[data-action="test"]'), `${name} detail exposes a test control`);
    assert.ok(detailOf(root).querySelector('[data-field="key"]'), `${name} detail exposes its key field`);
  }
  assert.deepEqual(seen.slice(0, 8), KEYED, 'each keyed source is queried for the initial overview');
  assert.deepEqual(seen.slice(8), KEYED, 'each keyed source refreshes when its detail opens');

  for (const name of ALL.slice(8)) {
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
  const stored = { store: { state: 'present', saved_at: 1, error: null }, effective_source: 'credential_store', env_overrides_store: false, env_var: '', file_key_count: 0 };
  const outcomes = { tavily: 'success', brave: 'auth_failed', exa: 'quota' };
  const resolvers = {};
  const api = {
    settingsView: async () => settings(),
    credentialStatus: async () => stored,
    credentialTest: source => new Promise(resolve => { resolvers[source] = () => resolve({ result: outcomes[source], message: '' }); }),
  };
  await mountSources(root, api);

  const expected = {
    tavily: '测试成功：Tavily 本次使用 Windows 凭据库。',
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

test('all twelve sources expose independent explicit test controls', async () => {
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
  assert.equal(new Set(called).size, 12);
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
    timeout: 25,
    disabled_sources: ['exa', 'brave'],
    twitter_cookies_path: 'C:/cookies.json',
  }, 'the toggle must not clobber settings it did not touch');
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
    credentialStatus: async source => source === 'baidu' ? { ...absent, effective_source: 'credential_store', store: { state: 'present', saved_at: 1 } } : absent,
  });
  assert.equal(root.querySelector('[data-stat="enabled"]').textContent, '10');
  assert.equal(root.querySelector('[data-stat="configured"]').textContent, '1');
  assert.equal(root.querySelector('[data-stat="absent"]').textContent, '8');
  assert.equal(root.querySelectorAll('[data-source-row][data-expanded="true"]').length, 0, 'entering the page expands nothing');
  root.querySelector('[data-filter="unconfigured"]').click();
  const visible = () => [...root.querySelectorAll('[data-source-row]')].filter(row => !row.hidden);
  assert.equal(visible().length, 8);
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
    settingsSave: async input => { await flush(); current = settings(input); return current; },
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
  const stored = { ...absent, effective_source: 'credential_store', store: { state: 'present', saved_at: 1 } };
  await mountSources(root, {
    settingsView: async () => settings(),
    credentialStatus: async () => stored,
    credentialTest: async () => { calls += 1; return { result: 'success', message: 'synthetic response' }; },
    credentialSave: async () => ({ ...stored, store: { state: 'present', saved_at: 2 } }),
  });
  const row = root.querySelector('[data-source-row="tavily"]');
  row.querySelector('[data-row-test]').click();
  await flush(); await flush();
  assert.equal(calls, 1);
  assert.equal(row.querySelector('[data-row-result]').dataset.kind, 'success');
  assert.match(detailOf(root).querySelector('[data-status="test"]').textContent, /测试成功/);
  detailOf(root).querySelector('[data-field="key"]').value = 'synthetic';
  detailOf(root).querySelector('form').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(row.querySelector('[data-row-result]').dataset.kind, 'idle');
  assert.equal(calls, 1);
  window.close();
});

function flush() { return new Promise(resolve => setTimeout(resolve, 0)); }
