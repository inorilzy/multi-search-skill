import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountSources } from '../ui/sources.js';
import { managementApi } from '../ui/api.js';

const flush = async () => { await new Promise(resolve => setTimeout(resolve, 0)); await new Promise(resolve => setTimeout(resolve, 0)); };
const settings = { route: 'default', timeout: 60, disabled_sources: [], twitter_cookies_path: null };
const status = (effective_source = 'none') => ({ store: { state: effective_source === 'file' ? 'present' : 'absent', error: '' }, effective_source, key_application_available: false });
function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root };
}

test('T05: Jina row can add, reveal and remove keys without a search toggle or test control', async () => {
  const { window, root } = setup();
  let keys = [], revision = 0;
  const mounted = await mountSources(root, {
    settingsView: async () => settings,
    credentialStatus: async () => status(),
    credentialRead: async source => { assert.equal(source, 'jina'); return { value: keys.map(() => '********').join('\n'), snapshot: String(revision) }; },
    credentialReveal: async source => { assert.equal(source, 'jina'); return { value: keys.join('\n'), snapshot: String(revision) }; },
    credentialAppend: async (source, values) => { assert.equal(source, 'jina'); keys.push(...values); revision += 1; return status('file'); },
    credentialRemove: async (source, index, expected) => { assert.equal(source, 'jina'); assert.equal(expected, String(revision)); keys.splice(index, 1); revision += 1; return status(); },
    credentialTest: async () => assert.fail('Jina must never launch a search test'),
  });
  const row = root.querySelector('[data-source-row="jina"]');
  assert.ok(row, 'Jina has a credential row on page 04');
  assert.equal(row.querySelector('[data-row-test]'), null);
  assert.equal(row.querySelector('[data-toggle]'), null);
  row.querySelector('[data-expand]').click(); await flush();
  const detail = row.querySelector('[data-source-detail]');
  assert.ok(!detail.querySelector('[data-action="test"]') || detail.querySelector('[data-action="test"]').hidden);
  assert.match(detail.textContent, /仅用于网页抓取/);
  detail.querySelector('[data-action="add"]').click();
  const input = detail.querySelector('[data-draft-input]');
  assert.equal(window.document.activeElement, input);
  input.value = 'synthetic-jina-t05';
  detail.querySelector('form').dispatchEvent(new window.Event('submit', { cancelable: true })); await flush();
  assert.deepEqual(keys, ['synthetic-jina-t05']);
  detail.querySelector('[data-action="reveal"]').click(); await flush();
  assert.equal(detail.querySelector('[data-saved-input]').value, 'synthetic-jina-t05');
  detail.querySelector('[data-action="remove"]').click();
  detail.querySelector('[data-action="confirm-remove"]').click(); await flush();
  assert.deepEqual(keys, []);
  assert.equal(detail.querySelector('[data-saved-empty]').hidden, false);
  mounted.dispose(); window.close();
});

for (const provenance of ['env', 'file']) {
  test(`T05: Twitter uses Core ${provenance} status even when settings contain no Cookie path`, async () => {
    const { window, root } = setup();
    const mounted = await mountSources(root, {
      settingsView: async () => settings,
      settingsSave: async input => ({ ...settings, ...input }),
      credentialStatus: async source => source === 'twitter' ? status(provenance) : status(),
    });
    const row = root.querySelector('[data-source-row="twitter"]');
    assert.equal(row.querySelector('[data-row-status]').dataset.kind, 'configured');
    assert.match(row.querySelector('[data-key-summary-text]').textContent, /已配置/);
    const toggle = root.querySelector('[data-toggle="brave"]');
    toggle.checked = false; toggle.dispatchEvent(new window.Event('change')); await flush();
    assert.equal(row.querySelector('[data-row-status]').dataset.kind, 'configured', 'saving another switch does not erase Core provenance');
    mounted.dispose(); window.close();
  });
}

test('T05: the key selector defaults to the newly saved row and sends only its index and snapshot', async () => {
  const { window, root } = setup();
  const calls = [];
  const mounted = await mountSources(root, {
    settingsView: async () => settings,
    credentialStatus: async () => status('env'),
    credentialRead: async () => ({ value: 'good********key\nbad********key', snapshot: 't05-snapshot' }),
    credentialTest: async (...args) => { calls.push(args); return { result: 'auth_failed', message: 'synthetic rejection' }; },
  });
  root.querySelector('[data-pick="tavily"]').click(); await flush();
  const detail = root.querySelector('[data-source-row="tavily"] [data-source-detail]');
  const select = detail.querySelector('[data-test-key]');
  assert.ok(select, 'users can choose one saved key');
  assert.equal(select.value, '1');
  detail.querySelector('[data-action="test"]').click(); await flush();
  assert.deepEqual(calls, [['tavily', { index: 1, expected: 't05-snapshot' }]]);
  assert.match(detail.querySelector('[data-status="test"]').textContent, /认证失败/);
  assert.doesNotMatch(detail.querySelector('[data-status="test"]').textContent, /成功/);
  select.value = 'env'; select.dispatchEvent(new window.Event('change'));
  assert.equal(detail.querySelector('[data-status="test"]').textContent, '尚未测试');
  detail.querySelector('[data-action="test"]').click(); await flush();
  assert.deepEqual(calls[1], ['tavily'], 'the environment Key is a separate explicit choice');
  mounted.dispose(); window.close();
});

test('T05: IPC forwards a selected row without forwarding plaintext or executable paths', async () => {
  const calls = [];
  const api = managementApi(async (command, args) => { calls.push([command, args]); return { result: 'auth_failed', message: '' }; });
  await api.credentialTest('tavily', { index: 1, expected: 't05-snapshot' });
  assert.deepEqual(calls, [['credential_test', { source: 'tavily', index: 1, expected: 't05-snapshot' }]]);
});
