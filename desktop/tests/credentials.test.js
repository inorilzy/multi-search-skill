import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountCredentials } from '../ui/credentials.js';

const SYNTHETIC_KEY = 'synthetic-ui-key-0001';

function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root };
}

function status(overrides = {}) {
  return {
    store: { state: 'absent', saved_at: null, error: null },
    effective_source: 'none',
    env_overrides_store: false,
    ...overrides,
  };
}

test('page shows saved state, effective source, and env override notice without values', async () => {
  const { window, root } = setup();
  const api = { credentialStatus: async () => status({ store: { state: 'present', saved_at: 1, error: null }, effective_source: 'env', env_overrides_store: true }) };
  await mountCredentials(root, api);
  assert.equal(root.querySelector('[data-status="store"]').textContent, '已保存');
  assert.equal(root.querySelector('[data-status="source"]').textContent, '环境变量 TAVILY_API_KEY');
  assert.match(root.querySelector('[data-info="override"]').textContent, /覆盖已保存的 key/);
  window.close();
});

test('saving clears the input, never renders the key, and does not run a test', async () => {
  const { window, root } = setup();
  let saved = null;
  const api = {
    credentialStatus: async () => status(),
    credentialSave: async key => { saved = key; return status({ store: { state: 'present', saved_at: 2, error: null }, effective_source: 'credential_store' }); },
  };
  await mountCredentials(root, api);
  const field = root.querySelector('[data-field="key"]');
  field.value = SYNTHETIC_KEY;
  root.querySelector('[data-save-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(saved, SYNTHETIC_KEY);
  assert.equal(field.value, '');
  assert.equal(root.querySelector('[data-status="store"]').textContent, '已保存');
  assert.equal(root.querySelector('[data-status="test"]').textContent, '尚未测试');
  assert.match(root.querySelector('[data-info="test"]').textContent, /尚未测试/);
  assert.ok(!root.innerHTML.includes(SYNTHETIC_KEY));
  window.close();
});

test('save errors are shown as-is and the key value is not echoed back', async () => {
  const { window, root } = setup();
  const api = {
    credentialStatus: async () => status(),
    credentialSave: async () => { throw '凭据库不可用，未保存 key。'; },
  };
  await mountCredentials(root, api);
  const field = root.querySelector('[data-field="key"]');
  field.value = SYNTHETIC_KEY;
  root.querySelector('[data-save-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.match(root.querySelector('[data-info="error"]').textContent, /未保存/);
  assert.equal(field.value, '');
  assert.ok(!root.innerHTML.includes(SYNTHETIC_KEY));
  window.close();
});

test('delete reports removal and refreshes store state', async () => {
  const { window, root } = setup();
  let deleted = false;
  const api = {
    credentialStatus: async () => status({ store: { state: 'present', saved_at: 1, error: null }, effective_source: 'credential_store' }),
    credentialDelete: async () => { deleted = true; return status(); },
  };
  await mountCredentials(root, api);
  root.querySelector('[data-action="delete"]').click();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(deleted, true);
  assert.equal(root.querySelector('[data-status="store"]').textContent, '未保存');
  assert.equal(root.querySelector('[data-status="source"]').textContent, '未配置');
  window.close();
});

test('test results distinguish success, auth, quota, and network outcomes', async () => {
  const cases = [
    ['success', '测试成功：Tavily 可以使用已保存的 key。'],
    ['auth_failed', '认证失败：Tavily 拒绝了该 key。'],
    ['quota', '额度不足：Tavily 额度已用尽。'],
    ['network', '网络错误：无法连接 Tavily。'],
  ];
  for (const [result, label] of cases) {
    const { window, root } = setup();
    const api = {
      credentialStatus: async () => status({ store: { state: 'present', saved_at: 1, error: null }, effective_source: 'credential_store' }),
      credentialTest: async () => ({ result, message: '' }),
    };
    await mountCredentials(root, api);
    root.querySelector('[data-action="test"]').click();
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(root.querySelector('[data-status="test"]').textContent, label, result);
    window.close();
  }
});

test('test page warns about external requests and quota before running', async () => {
  const { window, root } = setup();
  await mountCredentials(root, { credentialStatus: async () => status() });
  assert.match(root.querySelector('[data-info="warning"]').textContent, /外部搜索请求/);
  assert.match(root.querySelector('[data-info="warning"]').textContent, /额度/);
  assert.equal(root.querySelector('[data-status="test"]').textContent, '尚未测试');
  window.close();
});
