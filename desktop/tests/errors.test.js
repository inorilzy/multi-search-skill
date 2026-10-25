import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Window } from 'happy-dom';
import { managementApi, normalizeError, errorReason, showError, IpcError } from '../ui/api.js';
import { mountDiagnostics } from '../ui/diagnostics.js';
import { mountInstall } from '../ui/install.js';
import { mountSkill } from '../ui/skill.js';
import { mountCredentials } from '../ui/credentials.js';
import { mountSettings } from '../ui/settings.js';
import { mountSources } from '../ui/sources.js';
import { mountMigration } from '../ui/migration.js';

const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const here = new URL('.', import.meta.url);
const read = path => readFileSync(new URL(path, here), 'utf8');
const coded = (code, message = '') => JSON.stringify({ code, message });

function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root };
}
const readyDetect = () => ({ app: { status: 'ready' }, user: { status: 'ready' }, execution: { status: 'ready' } });

test('normalizeError maps codes to Chinese, keeps localized reasons and hides English details', () => {
  const mapped = normalizeError(coded('settings_view_failed', 'settings viewer failed'));
  assert.equal(mapped.code, 'settings_view_failed');
  assert.equal(mapped.message, '设置读取失败，请重新读取。');
  assert.equal(mapped.detail, 'settings viewer failed');

  const localized = normalizeError(coded('operation_failed', '现有配置文件不是有效的 JSON 对象'));
  assert.equal(localized.message, '现有配置文件不是有效的 JSON 对象');

  const english = normalizeError('Search worker failed');
  assert.equal(english.message, '操作失败，请重试。');
  assert.equal(english.detail, 'Search worker failed');

  assert.equal(normalizeError(new IpcError('execution_cancel_failed', '取消失败')).message, '取消失败');
  assert.equal(normalizeError(new Error('boom')).message, '操作失败，请重试。');
  assert.equal(normalizeError(null, '备用文案').message, '备用文案');
  assert.equal(errorReason(coded('cli_detect_failed')), 'CLI 检测失败，请重新检测。');
});

test('showError writes display text and keeps the raw reason in the tooltip', () => {
  const { window, root } = setup();
  showError(root, coded('execution_poll_failed', 'Execution state unavailable'), 'fallback');
  assert.equal(root.textContent, '执行状态读取失败，请稍后重试或取消本次执行。');
  assert.equal(root.title, 'Execution state unavailable');
  window.close();
});

test('the API layer rejects with normalized IpcError objects', async () => {
  const api = managementApi(async () => { throw coded('credential_save_failed', 'Credential save worker failed'); });
  await assert.rejects(api.credentialSave('tavily', 'k'), error => {
    assert.ok(error instanceof IpcError);
    assert.equal(error.code, 'credential_save_failed');
    assert.equal(error.message, '凭据保存失败，请检查凭据库访问后重试。');
    assert.equal(error.detail, 'Credential save worker failed');
    return true;
  });
});

test('backend commands use the {code,message} contract and localize every worker code', () => {
  const window = read('../src-tauri/src/window.rs');
  const errors = read('../src-tauri/src/errors.rs');
  assert.match(errors, /pub struct CommandError\s*\{[^}]*pub code: String,[^}]*pub message: String,/s);
  assert.match(errors, /serde_json::to_string\(&error\)/, 'CommandError serializes to JSON');
  const used = [...window.matchAll(/offload(?:_value)?\([\s\S]{0,600}?, "([a-z_]+)"\)/g)].map(m => m[1]);
  assert.ok(used.length >= 20, `expected every command to use a coded worker error, found ${used.length}`);
  const mapped = new Set([...errors.matchAll(/^\s*"([a-z_]+)" => /gm)].map(m => m[1]));
  for (const code of new Set(used)) assert.ok(mapped.has(code), `errors.rs has no Chinese message for ${code}`);
  for (const [, message] of errors.matchAll(/^\s*"[a-z_]+" => "([^"]+)"/gm)) {
    assert.match(message, /[\u4e00-\u9fff]/, 'each mapping is Chinese');
  }
  assert.doesNotMatch(window, /map_err\(\|_\| "[A-Za-z][^"]*failed"/, 'no English worker message is returned directly');
  assert.doesNotMatch(window, /map_err\(\|_\| "[A-Za-z][^"]*"/, 'no raw English worker message remains');
});

test('diagnostics shows a visible Chinese error when detection fails', async () => {
  const { window, root } = setup();
  await mountDiagnostics(root, { detect: async () => { throw coded('cli_detect_failed', 'CLI detection worker failed'); } });
  const error = root.querySelector('[data-info="error"]');
  assert.match(error.textContent, /CLI 检测失败/);
  assert.doesNotMatch(error.textContent, /worker/);
  window.close();
});

test('install shows a visible error when the plan cannot be read and never a raw enum', async () => {
  const { window, root } = setup();
  await mountInstall(root, {
    installPlan: async () => { throw coded('install_plan_failed', 'Install planning failed'); },
    userPathPlan: async () => ({ directory: 'C:/ms/bin', reason: '', can_add: false, can_remove: false }),
  });
  assert.match(root.querySelector('[data-info="reason"]').textContent, /安装计划检查失败/);
  assert.equal(root.querySelector('[data-status="plan"]').textContent, '不可用');
  window.close();
});

test('skill page reports check/update IPC failures instead of swallowing them', async () => {
  const { window, root } = setup();
  await mountSkill(root, {
    skillPlan: async () => ({ scope: 'global', target: 'C:/x', files: [], status: 'ready', reason: '可以安装', can_install: true }),
    skillStatus: async () => { throw coded('skill_status_failed', 'Skill status worker failed'); },
  });
  root.querySelector('[data-action="check"]').click();
  await flush();
  const error = root.querySelector('[data-info="manage-error"]');
  assert.match(error.textContent, /Skill 状态检查失败/);
  assert.doesNotMatch(error.textContent, /worker/);
  window.close();
});

test('credentials page reports read/append/remove IPC failures and keeps outcomes out of the test area', async () => {
  const { window, root } = setup();
  let statusCalls = 0;
  const overview = { source: 'tavily', store: { state: 'present', saved_at: 1, error: '' }, effective_source: 'sqlite', key_application_available: false };
  let appendFails = true;
  await mountCredentials(root, {
    credentialStatus: async () => { statusCalls += 1; return overview; },
    credentialRead: async () => ({ value: 'masked-0001', snapshot: 'r1' }),
    credentialAppend: async () => { if (appendFails) throw coded('credential_append_failed', 'Credential append worker failed'); return overview; },
    credentialRemove: async () => { throw coded('credential_remove_failed', 'Credential remove worker failed'); },
  });
  assert.equal(statusCalls, 1);
  const field = root.querySelector('[data-field="key"]');
  field.value = 'synthetic-error-key';
  root.querySelector('[data-save-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush(); await flush();
  const error = root.querySelector('[data-info="error"]');
  assert.match(error.textContent, /凭据保存失败/);
  assert.doesNotMatch(error.textContent, /worker/);
  assert.equal(root.querySelector('[data-status="test"]').textContent, '尚未测试', 'the test result area is untouched');
  assert.equal(root.querySelector('[data-info="test"]').textContent, '', 'a failed save is not written into the outcome area');

  appendFails = false;
  root.querySelector('[data-field="key"]').value = 'synthetic-error-key-2';
  root.querySelector('[data-save-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush(); await flush();
  assert.match(root.querySelector('[data-info="test"]').textContent, /已保存。尚未测试。/);
  assert.equal(root.querySelector('[data-status="test"]').textContent, '尚未测试', 'save outcome does not masquerade as a test result');

  root.querySelector('[data-action="remove"]').click();
  root.querySelector('[data-action="confirm-remove"]').click();
  await flush(); await flush();
  assert.match(root.querySelector('[data-info="error"]').textContent, /凭据删除失败/);
  window.close();
});

test('settings view failure disables saving, shows the reason and offers a retry that recovers', async () => {
  const { window, root } = setup();
  let fail = true;
  const routes = { default: { label: '默认', sources: ['brave'], timeout: null } };
  const view = { config_path: 'C:/cfg.sqlite', path_source: 'user', file_present: true, read_source: 'sqlite', route: 'default', timeout: 60, timeout_configured: true, effective_timeout: 60, timeout_min: 1, timeout_max: 90, timeout_out_of_range: false, effective_timeouts: { default: 60 }, routes, builtin_routes: routes, disabled_sources: [], unknown_disabled_sources: [], twitter_cookies_path: null, scrape_backends: ['jina'], scrape_backends_invalid: false, builtin_scrape_backends: ['jina'], scrape_backend_options: [{ name: 'jina', label: 'Jina Reader' }], active_sources: ['brave'], status: 'ok', message: '' };
  await mountSettings(root, { settingsView: async () => { if (fail) throw coded('settings_view_failed', 'Settings view worker failed'); return view; } });
  assert.equal(root.querySelector('[data-action="save"]').disabled, true);
  assert.match(root.querySelector('[data-info="error"]').textContent, /设置读取失败/);
  const retry = root.querySelector('[data-action="retry"]');
  assert.equal(retry.hidden, false);
  fail = false;
  retry.click();
  await flush(); await flush();
  assert.equal(root.querySelector('[data-action="save"]').disabled, false);
  assert.equal(retry.hidden, true);
  assert.equal(root.querySelector('[data-info="error"]').textContent, '');
  window.close();
});

test('sources settings failure shows a retry button that reloads the overview', async () => {
  const { window, root } = setup();
  let fail = true;
  const view = { route: 'default', timeout: 60, disabled_sources: [], twitter_cookies_path: null };
  const mounted = await mountSources(root, {
    settingsView: async () => { if (fail) throw coded('settings_view_failed', 'Settings view worker failed'); return view; },
    credentialStatus: async () => ({ source: '', store: { state: 'absent', saved_at: null, error: '' }, effective_source: 'none', key_application_available: false }),
  });
  const error = root.querySelector('[data-list-error]');
  const retry = root.querySelector('[data-action="retry-settings"]');
  assert.match(error.textContent, /设置读取失败/);
  assert.equal(retry.hidden, false);
  assert.ok([...root.querySelectorAll('[data-toggle]')].every(toggle => toggle.disabled));
  fail = false;
  retry.click();
  await flush();
  assert.equal(retry.hidden, true);
  assert.equal(error.textContent, '');
  assert.ok([...root.querySelectorAll('[data-toggle]')].every(toggle => !toggle.disabled));
  mounted.dispose();
  window.close();
});

test('migration IPC failures show the backend reason and hostile provider names cannot break selectors', async () => {
  const { window, root } = setup();
  let applyArgs = null;
  const hostile = 'evil"]';
  const plan = {
    plan_token: 'token',
    items: [
      { provider: hostile, action: 'conflict', preview: 'x…1' },
      { provider: 'tavily', action: 'migrate', preview: 'x…2' },
    ],
    migratable: [hostile, 'tavily'],
    skipped: [],
  };
  const mounted = await mountMigration(root, {
    migrationPlan: async () => plan,
    migrationApply: async (...args) => { applyArgs = args; throw coded('migration_apply_failed', 'Migration apply worker failed'); },
  });
  root.querySelector('[data-action="preview"]').click();
  await flush();
  const hostileBox = [...root.querySelectorAll('[data-approve]')].find(box => box.dataset.approve === hostile);
  hostileBox.checked = true;
  hostileBox.closest('li').querySelector('select[data-choice]').value = 'keep';
  root.querySelector('[data-approve="tavily"]').checked = true;
  root.querySelector('[data-action="apply"]').click();
  await flush();
  assert.equal(applyArgs[1][0], hostile, 'the hostile provider name is passed through unchanged');
  assert.match(root.querySelector('[data-info="result"]').textContent, /迁移执行失败|迁移未完成/);
  assert.doesNotMatch(root.querySelector('[data-info="result"]').textContent, /worker/);
  assert.equal(root.querySelector('[data-info="error"]').textContent, '', 'a failed apply is not reported as a preview error');
  mounted.dispose();
  window.close();
});

test('search results render as a readable list, keep raw JSON collapsed and never inject HTML', async () => {
  const { window, root } = setup();
  const api = {
    detect: async () => readyDetect(),
    start: async () => 1,
    poll: async () => ({
      status: 'partial',
      payload: {
        results: [
          { title: '<img src=x onerror=attack()>', url: 'https://example.invalid/a', snippet: '摘要 <b>不加粗</b>', source: 'brave' },
          { title: 'no link', url: 'javascript:alert(1)', snippet: 'plain', source: 'exa' },
        ],
        errors: [{ source: 'hackernews', error: 'unavailable [REDACTED]' }],
      },
      error: '',
    }),
  };
  const page = await mountDiagnostics(root, api);
  root.querySelector('[data-field="query"]').value = 'fixture';
  root.querySelector('[data-action="search"]').click();
  await flush();
  const results = root.querySelector('[data-results]');
  const items = results.querySelectorAll('.search-result-list li');
  assert.equal(items.length, 2);
  assert.equal(items[0].querySelector('strong').textContent, '<img src=x onerror=attack()>');
  assert.equal(results.querySelector('img'), null);
  assert.equal(results.querySelector('b'), null);
  assert.equal(items[0].querySelector('a').getAttribute('href'), 'https://example.invalid/a');
  assert.equal(items[1].querySelector('a'), null, 'non-http links are shown as text only');
  assert.match(results.querySelector('.search-error-list').textContent, /hackernews：unavailable \[REDACTED\]/);
  const raw = results.querySelector('details');
  assert.ok(raw && !raw.open, 'raw JSON is collapsed by default');
  assert.match(raw.querySelector('pre').textContent, /"results"/);
  assert.equal(root.querySelector('[data-status="execution"]').textContent, '部分来源失败');
  page.dispose();
  window.close();
});

test('unknown status enums are labelled instead of leaking', async () => {
  const { window, root } = setup();
  await mountInstall(root, {
    installPlan: async () => ({ status: 'brand_new_state', reason: 'reason from backend' }),
    userPathPlan: async () => ({ directory: '', reason: '', can_add: false, can_remove: false }),
  });
  assert.equal(root.querySelector('[data-status="plan"]').textContent, '未知状态（brand_new_state）');
  window.close();
});
