import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountSources } from '../ui/sources.js';

test('sources page mounts one scoped credential panel per allowlisted source', async () => {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  const seen = [];
  const api = {
    credentialStatus: async source => {
      seen.push(source);
      return { store: { state: 'absent', saved_at: null, error: null }, effective_source: 'none', env_overrides_store: false, env_var: '', file_key_count: 0 };
    },
  };
  const mounted = await mountSources(root, api);
  const panels = [...root.querySelectorAll('[data-source-panel]')].map(node => node.getAttribute('data-source-panel'));
  assert.deepEqual(panels, ['baidu', 'brave', 'parallel', 'tavily', 'exa', 'firecrawl', 'serpapi', 'github-repos', 'hackernews', 'stackoverflow', 'sov2ex', 'twitter']);
  assert.deepEqual(seen, panels.slice(0, 8));
  for (const name of panels.slice(8)) {
    const row = root.querySelector(`[data-source-panel="${name}"]`);
    assert.ok(row.querySelector('[data-action="test"]'));
    assert.equal(row.querySelector('[data-field="key"]'), null);
    assert.match(row.textContent, name === 'twitter' ? /Cookie.*路径/ : /无需凭据/);
  }
  assert.equal(root.querySelectorAll('[data-status="store"]').length, 8);
  assert.ok(!root.textContent.includes('Jina'), 'Jina is out of scope for 05');
  mounted.dispose();
  window.close();
});

test('per-source test results stay on their own row when outcomes interleave', async () => {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  const stored = { store: { state: 'present', saved_at: 1, error: null }, effective_source: 'credential_store', env_overrides_store: false, env_var: '', file_key_count: 0 };
  // Synthetic outcomes: tavily succeeds, brave fails auth, exa hits quota. Resolution order is reversed on purpose.
  const outcomes = { tavily: 'success', brave: 'auth_failed', exa: 'quota' };
  const resolvers = {};
  const api = {
    credentialStatus: async () => stored,
    credentialTest: (source) => new Promise(resolve => { resolvers[source] = () => resolve({ result: outcomes[source], message: '' }); }),
  };
  const mounted = await mountSources(root, api);
  const panel = name => root.querySelector(`[data-source-panel="${name}"]`);
  for (const name of ['brave', 'tavily', 'exa']) panel(name).querySelector('[data-action="test"]').click();
  await flush();
  resolvers.exa();
  resolvers.tavily();
  resolvers.brave();
  await flush();
  assert.equal(panel('tavily').querySelector('[data-status="test"]').textContent, '测试成功：Tavily 本次使用Windows 凭据库。');
  assert.equal(panel('brave').querySelector('[data-status="test"]').textContent, '认证失败：Brave 搜索 拒绝了该 key。');
  assert.equal(panel('exa').querySelector('[data-status="test"]').textContent, '额度不足：Exa 额度已用尽。');
  assert.equal(panel('parallel').querySelector('[data-status="test"]').textContent, '尚未测试', 'untested row is not touched');
  mounted.dispose();
  window.close();
});

test('all twelve sources expose independent explicit test controls', async () => {
  const window = new Window();
  const root = window.document.createElement('main');
  const called = [];
  const mounted = await mountSources(root, {
    credentialStatus: async () => ({ store: { state: 'absent' }, effective_source: 'none' }),
    credentialTest: async source => { called.push(source); return { result: 'success', message: source }; },
  });
  for (const row of root.querySelectorAll('[data-source-panel]')) {
    row.querySelector('[data-action="test"]').click();
    await flush();
    assert.match(row.querySelector('[data-status="test"]').textContent, /测试成功/);
    assert.equal(row.querySelector('[data-info="test"]').textContent, row.getAttribute('data-source-panel'));
  }
  assert.equal(new Set(called).size, 12);
  mounted.dispose();
  window.close();
});

function flush() { return new Promise(resolve => setTimeout(resolve, 0)); }
