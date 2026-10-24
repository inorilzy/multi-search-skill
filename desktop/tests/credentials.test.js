import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountCredentials, SOURCES } from '../ui/credentials.js';

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
    env_var: '',
    file_key_count: 0,
    ...overrides,
  };
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

test('reveal only shows newly typed input and saved keys are never fetched', async () => {
  const { window, root } = setup();
  await mountCredentials(root, {
    credentialStatus: async () => status({ store: { state: 'present', saved_at: 1 }, effective_source: 'credential_store' }),
    credentialSave: async () => status({ store: { state: 'present', saved_at: 2 }, effective_source: 'credential_store' }),
  });
  const input = root.querySelector('[data-field="key"]');
  const reveal = root.querySelector('[data-action="reveal"]');
  assert.equal(input.value, '');
  assert.equal(input.type, 'password');
  input.value = SYNTHETIC_KEY;
  reveal.click();
  assert.equal(input.type, 'text');
  assert.equal(reveal.getAttribute('aria-pressed'), 'true');
  reveal.click();
  assert.equal(input.type, 'password');
  root.querySelector('form').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(input.value, '');
  assert.ok(!root.innerHTML.includes(SYNTHETIC_KEY));
  window.close();
});

test('page shows saved state, effective source, and env override notice without values', async () => {
  const { window, root } = setup();
  const api = { credentialStatus: async () => status({ store: { state: 'present', saved_at: 1, error: null }, effective_source: 'env', env_overrides_store: true, env_var: 'TAVILY_API_KEY' }) };
  await mountCredentials(root, api);
  assert.equal(root.querySelector('[data-status="store"]').textContent, '已保存');
  assert.equal(root.querySelector('[data-status="source"]').textContent, '环境变量 TAVILY_API_KEY');
  assert.match(root.querySelector('[data-info="override"]').textContent, /覆盖已保存的 API Key|覆盖已保存的 Key/);
  assert.match(root.querySelector('[data-info="override"]').textContent, /TAVILY_API_KEY/);
  window.close();
});

test('a keyed source mounts its own panel and queries the backend by public name', async () => {
  assert.deepEqual(
    SOURCES.filter(item => item.keyed).map(item => item.source),
    ['baidu', 'brave', 'parallel', 'tavily', 'exa', 'firecrawl', 'serpapi', 'github_repos'],
  );
  for (const entry of SOURCES.filter(item => item.keyed)) {
    const { window, root } = setup();
    const seen = [];
    const api = { credentialStatus: async source => { seen.push(source); return status(); } };
    await mountCredentials(root, api, { source: entry.source });
    assert.deepEqual(seen, [entry.source]);
    assert.match(root.querySelector('.eyebrow').textContent, new RegExp(entry.source));
    assert.ok(root.textContent.includes(entry.label), entry.source);
    window.close();
  }
});

test('saving clears the input, never renders the key, and does not run a test', async () => {
  const { window, root } = setup();
  let saved = null;
  const api = {
    credentialStatus: async () => status(),
    credentialSave: async (source, key) => { saved = { source, key }; return status({ store: { state: 'present', saved_at: 2, error: null }, effective_source: 'credential_store' }); },
  };
  await mountCredentials(root, api);
  const field = root.querySelector('[data-field="key"]');
  field.value = SYNTHETIC_KEY;
  root.querySelector('[data-save-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.deepEqual(saved, { source: 'tavily', key: SYNTHETIC_KEY });
  assert.equal(field.value, '');
  assert.equal(root.querySelector('[data-status="store"]').textContent, '已保存');
  assert.equal(root.querySelector('[data-status="test"]').textContent, '尚未测试');
  assert.match(root.querySelector('[data-info="test"]').textContent, /尚未测试/);
  assert.ok(!root.innerHTML.includes(SYNTHETIC_KEY));
  window.close();
});

test('successful test expires on replacement, deletion and provenance refresh', async () => {
  const { window, root } = setup();
  let overview = status({ store: { state: 'present', saved_at: 1 }, effective_source: 'credential_store' });
  const api = {
    credentialStatus: async () => overview,
    credentialTest: async () => ({ result: 'success' }),
    credentialSave: async () => overview,
    credentialDelete: async () => status(),
  };
  await mountCredentials(root, api);
  for (const operation of ['save', 'delete', 'refresh']) {
    root.querySelector('[data-action="test"]').click();
    await flush();
    assert.match(root.querySelector('[data-status="test"]').textContent, /测试成功/);
    if (operation === 'save') {
      root.querySelector('[data-field="key"]').value = SYNTHETIC_KEY;
      root.querySelector('[data-save-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
    } else if (operation === 'delete') {
      root.querySelector('[data-action="delete"]').click();
      root.querySelector('[data-action="confirm-delete"]').click();
    } else {
      overview = status({ effective_source: 'env', env_var: 'TAVILY_API_KEY' });
      root.querySelector('[data-action="refresh"]').click();
    }
    await flush();
    assert.equal(root.querySelector('[data-status="test"]').textContent, '尚未测试', operation);
  }
  root.querySelector('[data-action="test"]').click();
  await flush();
  assert.match(root.querySelector('[data-status="test"]').textContent, /环境变量 TAVILY_API_KEY/);
  assert.doesNotMatch(root.querySelector('[data-status="test"]').textContent, /已保存的 Key/);
  window.close();
});

test('late credential test cannot validate a replacement key', async () => {
  const { window, root } = setup();
  let resolveTest;
  const overview = status({ store: { state: 'present', saved_at: 1 }, effective_source: 'credential_store' });
  await mountCredentials(root, {
    credentialStatus: async () => overview,
    credentialTest: () => new Promise(resolve => { resolveTest = resolve; }),
    credentialSave: async () => overview,
  });
  root.querySelector('[data-action="test"]').click();
  root.querySelector('[data-field="key"]').value = SYNTHETIC_KEY;
  root.querySelector('[data-save-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  resolveTest({ result: 'success', message: 'old credential response' });
  await flush();
  assert.equal(root.querySelector('[data-status="test"]').textContent, '尚未测试');
  assert.doesNotMatch(root.textContent, /old credential response/);
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
  await flush();
  assert.match(root.querySelector('[data-info="error"]').textContent, /未保存/);
  assert.equal(field.value, '');
  assert.ok(!root.innerHTML.includes(SYNTHETIC_KEY));
  window.close();
});

test('save with a file key list asks for confirmation; cancel writes nothing', async () => {
  const { window, root } = setup();
  let saveCalls = 0;
  const api = {
    credentialStatus: async () => status({ file_key_count: 2, effective_source: 'file' }),
    credentialSave: async () => { saveCalls += 1; return status(); },
  };
  await mountCredentials(root, api, { source: 'github_repos' });
  const field = root.querySelector('[data-field="key"]');
  field.value = SYNTHETIC_KEY;
  root.querySelector('[data-save-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(saveCalls, 0, 'nothing is written before confirmation');
  const prompt = root.querySelector('[data-confirm="save"]');
  assert.ok(prompt);
  assert.match(prompt.textContent, /保存后使用凭据库 Key，文件中的 2 个 Key 保留但不参与本来源轮换/);
  root.querySelector('[data-action="cancel-save"]').click();
  await flush();
  assert.equal(saveCalls, 0);
  assert.equal(root.querySelector('[data-confirm="save"]'), null);
  assert.ok(!root.innerHTML.includes(SYNTHETIC_KEY));
  window.close();
});

test('confirmed save with a file key list writes exactly once with the source name', async () => {
  const { window, root } = setup();
  const calls = [];
  const api = {
    credentialStatus: async () => status({ file_key_count: 2, effective_source: 'file' }),
    credentialSave: async (source, key) => { calls.push({ source, key }); return status({ file_key_count: 2, store: { state: 'present', saved_at: 3, error: null }, effective_source: 'credential_store' }); },
  };
  await mountCredentials(root, api, { source: 'github_repos' });
  const field = root.querySelector('[data-field="key"]');
  field.value = SYNTHETIC_KEY;
  root.querySelector('[data-save-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  root.querySelector('[data-action="confirm-save"]').click();
  await flush();
  assert.deepEqual(calls, [{ source: 'github_repos', key: SYNTHETIC_KEY }]);
  assert.equal(root.querySelector('[data-confirm="save"]'), null);
  assert.equal(root.querySelector('[data-status="source"]').textContent, 'Windows 凭据库');
  assert.match(root.querySelector('[data-info="override"]').textContent, /文件中的 2 个 Key 已保留/);
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
  await flush();
  root.querySelector('[data-action="confirm-delete"]').click();
  await flush();
  assert.equal(deleted, true);
  assert.equal(root.querySelector('[data-status="store"]').textContent, '未保存');
  assert.equal(root.querySelector('[data-status="source"]').textContent, '未配置');
  window.close();
});

test('delete warning with a file list says the file keys will be restored', async () => {
  const { window, root } = setup();
  const api = {
    credentialStatus: async () => status({ store: { state: 'present', saved_at: 1, error: null }, effective_source: 'credential_store', file_key_count: 2 }),
    credentialDelete: async () => status({ file_key_count: 2, effective_source: 'file' }),
  };
  await mountCredentials(root, api, { source: 'github_repos' });
  root.querySelector('[data-action="delete"]').click();
  await flush();
  const text = root.querySelector('[data-confirm="delete"]').textContent;
  assert.match(text, /删除后将恢复使用文件中的 2 个 Key/);
  assert.doesNotMatch(text, /需要重新粘贴/);
  root.querySelector('[data-action="confirm-delete"]').click();
  await flush();
  assert.match(root.querySelector('[data-info="test"]').textContent, /已恢复使用文件中的 2 个 Key/);
  window.close();
});

test('delete warning with an env var says the env var still overrides and never claims no credentials', async () => {
  const { window, root } = setup();
  const api = {
    credentialStatus: async () => status({ store: { state: 'present', saved_at: 1, error: null }, effective_source: 'env', env_overrides_store: true, env_var: 'TAVILY_API_KEY' }),
    credentialDelete: async () => status({ effective_source: 'env', env_overrides_store: true, env_var: 'TAVILY_API_KEY' }),
  };
  await mountCredentials(root, api);
  root.querySelector('[data-action="delete"]').click();
  await flush();
  const text = root.querySelector('[data-confirm="delete"]').textContent;
  assert.match(text, /环境变量 TAVILY_API_KEY 仍会覆盖/);
  assert.doesNotMatch(text, /没有|需要重新粘贴/);
  root.querySelector('[data-action="confirm-delete"]').click();
  await flush();
  const message = root.querySelector('[data-info="test"]').textContent;
  assert.match(message, /仍由环境变量 TAVILY_API_KEY 生效/);
  assert.doesNotMatch(message, /当前没有可用的 Key/);
  window.close();
});

test('delete warning with no fallback says the key must be pasted again', async () => {
  const { window, root } = setup();
  const api = {
    credentialStatus: async () => status({ store: { state: 'present', saved_at: 1, error: null }, effective_source: 'credential_store' }),
  };
  await mountCredentials(root, api);
  root.querySelector('[data-action="delete"]').click();
  await flush();
  assert.match(root.querySelector('[data-confirm="delete"]').textContent, /需要重新粘贴 Key/);
  window.close();
});

test('test results distinguish success, auth, quota, and network outcomes', async () => {
  const cases = [
    ['success', '测试成功：Tavily 本次使用 Windows 凭据库。'],
    ['auth_failed', '认证失败：Tavily 拒绝了该 Key。'],
    ['quota', '额度不足：Tavily 额度已用尽。'],
    ['missing_key', '缺少 Key：请先保存。'],
    ['credential_store', '凭据库错误：无法读取这个来源的 Key，请重新保存。'],
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
    await flush();
    assert.equal(root.querySelector('[data-status="test"]').textContent, label, result);
    window.close();
  }
});

test('delete requires an in-page confirmation; cancel never calls the API', async () => {
  const { window, root } = setup();
  let deleteCalls = 0;
  const api = {
    credentialStatus: async () => status({ store: { state: 'present', saved_at: 1, error: null }, effective_source: 'credential_store' }),
    credentialDelete: async () => { deleteCalls += 1; return status(); },
  };
  await mountCredentials(root, api);
  root.querySelector('[data-action="delete"]').click();
  await flush();
  assert.equal(deleteCalls, 0);
  assert.ok(root.querySelector('[data-confirm="delete"]'));
  root.querySelector('[data-action="cancel-delete"]').click();
  await flush();
  assert.equal(deleteCalls, 0);
  assert.equal(root.querySelector('[data-confirm="delete"]'), null);
  assert.equal(root.querySelector('[data-status="store"]').textContent, '已保存');
  window.close();
});

test('confirmed delete calls the API exactly once and a failure stays visible', async () => {
  const { window, root } = setup();
  let deleteCalls = 0;
  const api = {
    credentialStatus: async () => status({ store: { state: 'present', saved_at: 1, error: null }, effective_source: 'credential_store' }),
    credentialDelete: async () => { deleteCalls += 1; throw '凭据库不可用，未删除 key。'; },
  };
  await mountCredentials(root, api);
  root.querySelector('[data-action="delete"]').click();
  await flush();
  root.querySelector('[data-action="confirm-delete"]').click();
  await flush();
  assert.equal(deleteCalls, 1);
  assert.match(root.querySelector('[data-info="error"]').textContent, /未删除/);
  window.close();
});

test('test page warns about external requests and quota before running', async () => {
  const { window, root } = setup();
  await mountCredentials(root, { credentialStatus: async () => status() });
  assert.match(root.querySelector('[data-info="warning"]').textContent, /外部搜索请求/);
  assert.match(root.querySelector('[data-info="warning"]').textContent, /额度/);
  assert.equal(root.querySelector('[data-status="test"]').textContent, '尚未测试');
  window.close();
});
