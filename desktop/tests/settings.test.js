import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountSettings, SETTINGS_SOURCES } from '../ui/settings.js';

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root };
}

function view(overrides = {}) {
  return {
    config_path: 'C:/Users/test/.multi-search/multi-search-config.json',
    path_source: 'user',
    file_present: true,
    route: 'default',
    timeout: 60,
    disabled_sources: [],
    twitter_cookies_path: null,
    twitter_env_overrides: false,
    active_sources: ['baidu', 'brave'],
    status: 'ok',
    message: '',
    ...overrides,
  };
}

test('the CLI source list uses underscore names, so settings and the sources page agree', async () => {
  const { window, root } = setup();
  await mountSettings(root, { settingsView: async () => view() });
  const names = SETTINGS_SOURCES.map(s => s.source);
  assert.equal(names.length, 12);
  assert.ok(names.every(name => !name.includes('-')), 'CLI source names use underscores');
  assert.ok(names.includes('github_repos'), 'github uses the underscore name shared with the sources page');
  window.close();
});

test('saving route and timeout preserves disabled_sources owned by the sources page', async () => {
  const { window, root } = setup();
  let sent = null;
  const api = {
    settingsView: async () => view({ disabled_sources: ['exa'] }),
    settingsSave: async input => { sent = input; return view({ route: input.route, timeout: input.timeout, disabled_sources: input.disabled_sources }); },
  };
  await mountSettings(root, api);
  assert.equal(root.querySelector('[data-source-toggle]'), null, 'source toggles live on the sources page now');
  root.querySelector('[data-field="route"]').value = 'fast';
  root.querySelector('[data-field="timeout"]').value = '30';
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.deepEqual(sent, {
    route: 'fast',
    timeout: 30,
    disabled_sources: ['exa'],
    twitter_cookies_path: '',
  }, 'settings must not clear sources disabled elsewhere');
  assert.equal(root.querySelector('[data-status="save"]').textContent, '已保存。');
  window.close();
});

test('no-active-source status is shown explicitly and a save never re-enables a source', async () => {
  const { window, root } = setup();
  let sent = null;
  await mountSettings(root, {
    settingsView: async () => view({
      active_sources: [],
      status: 'no_active_source',
      disabled_sources: ['twitter'],
    }),
    settingsSave: async input => { sent = input; return view({ ...input, active_sources: [] }); },
  });
  assert.match(root.querySelector('[data-info="active-warning"]').textContent, /没有可用的搜索源/);
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.deepEqual(sent.disabled_sources, ['twitter'], 'a disabled source stays disabled through a settings save');
  window.close();
});

test('env override of the config path and of the Twitter path is shown, values are not', async () => {
  const { window, root } = setup();
  await mountSettings(root, {
    settingsView: async () => view({
      config_path: 'D:/env/cfg.json',
      path_source: 'env',
      twitter_cookies_path: 'C:/cookies/saved.json',
      twitter_env_overrides: true,
    }),
  });
  const env = root.querySelector('[data-info="env"]').textContent;
  assert.match(env, /MULTI_SEARCH_CONFIG/);
  assert.match(env, /TWITTER_COOKIES_PATH/);
  assert.equal(root.querySelector('[data-field="twitter"]').value, 'C:/cookies/saved.json');
  window.close();
});

test('dev-fallback values show the save-creates-override notice before the user file exists', async () => {
  const { window, root } = setup();
  await mountSettings(root, {
    settingsView: async () => view({
      file_present: false,
      read_source: 'dev_fallback',
      save_creates_override: true,
    }),
  });
  const info = root.querySelector('[data-info="env"]').textContent;
  assert.match(info, /开发目录/);
  assert.match(info, /保存会创建用户配置文件/);
  window.close();
});

test('once the user file is read, no override notice is shown', async () => {
  const { window, root } = setup();
  await mountSettings(root, { settingsView: async () => view({ read_source: 'user', save_creates_override: false }) });
  assert.equal(root.querySelector('[data-info="env"]').textContent, '');
  window.close();
});

test('a rejected save keeps the form and shows the error without writing a status as saved', async () => {
  const { window, root } = setup();
  const api = {
    settingsView: async () => view(),
    settingsSave: async () => { throw '超时时间必须在 1 到 90 秒之间'; },
  };
  await mountSettings(root, api);
  root.querySelector('[data-field="timeout"]').value = '45';
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(root.querySelector('[data-info="error"]').textContent, '超时时间必须在 1 到 90 秒之间');
  assert.equal(root.querySelector('[data-status="save"]').textContent, '');
  assert.equal(root.querySelector('[data-field="timeout"]').value, '45');
  window.close();
});

test('save shows a loading state and a double submit writes exactly once', async () => {
  const { window, root } = setup();
  let release;
  const sent = [];
  await mountSettings(root, {
    settingsView: async () => view(),
    settingsSave: input => { sent.push(input); return new Promise(resolve => { release = resolve; }); },
  });
  const form = root.querySelector('[data-settings-form]');
  form.dispatchEvent(new window.Event('submit', { cancelable: true }));
  form.dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(sent.length, 1);
  const button = root.querySelector('[data-action="save"]');
  assert.equal(button.disabled, true);
  assert.equal(button.getAttribute('aria-busy'), 'true');
  assert.equal(root.querySelector('[data-action="refresh"]').disabled, true);
  release(view());
  await flush();
  assert.equal(button.disabled, false);
  assert.equal(root.querySelector('[data-status="save"]').textContent, '已保存。');
  window.close();
});

test('a failed settings read blocks saving and never submits timeout 0 or defaults', async () => {
  const { window, root } = setup();
  let ok = false;
  const sent = [];
  await mountSettings(root, {
    settingsView: async () => { if (!ok) throw 'offline'; return view({ timeout: 42 }); },
    settingsSave: async input => { sent.push(input); return view(input); },
  });
  const button = root.querySelector('[data-action="save"]');
  assert.equal(button.disabled, true);
  assert.match(root.querySelector('[data-info="error"]').textContent, /无法读取搜索设置/);
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(sent.length, 0, 'nothing is written from placeholder values');

  ok = true;
  root.querySelector('[data-action="refresh"]').click();
  await flush();
  assert.equal(button.disabled, false);
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].timeout, null, 'an unedited timeout is not rewritten');

  ok = false;
  root.querySelector('[data-action="refresh"]').click();
  await flush();
  assert.equal(button.disabled, true, 'a later failed refresh blocks saving again');
  window.close();
});

test('an unreadable config disables saving', async () => {
  const { window, root } = setup();
  await mountSettings(root, { settingsView: async () => view({ status: 'config_unreadable', timeout: 60 }) });
  assert.equal(root.querySelector('[data-action="save"]').disabled, true);
  window.close();
});

test('timeout range follows the backend (90 for the all route) and an edited value is validated', async () => {
  const { window, root } = setup();
  const sent = [];
  await mountSettings(root, {
    settingsView: async () => view({ route: 'all', timeout: 90, timeout_configured: false, timeout_min: 1, timeout_max: 90 }),
    settingsSave: async input => { sent.push(input); return view({ ...input, timeout: input.timeout ?? 90, timeout_max: 90 }); },
  });
  const field = root.querySelector('[data-field="timeout"]');
  assert.equal(field.max, '90');
  assert.equal(field.value, '90');
  assert.match(root.querySelector('[data-label="timeout"]').textContent, /1 到 90/);
  assert.match(root.querySelector('[data-info="timeout"]').textContent, /CLI 默认值/);
  const form = root.querySelector('[data-settings-form]');
  field.value = '91';
  form.dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(sent.length, 0);
  assert.match(root.querySelector('[data-info="error"]').textContent, /1 到 90/);
  field.value = '75';
  form.dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(sent[0].timeout, 75);
  window.close();
});

test('an out-of-range stored timeout and unknown disabled entries are shown and not rewritten', async () => {
  const { window, root } = setup();
  const sent = [];
  await mountSettings(root, {
    settingsView: async () => view({ timeout: 120, timeout_configured: true, timeout_out_of_range: true, timeout_max: 90, disabled_sources: ['exa'], unknown_disabled_sources: ['future_source'] }),
    settingsSave: async input => { sent.push(input); return view(); },
  });
  assert.equal(root.querySelector('[data-field="timeout"]').value, '120');
  assert.match(root.querySelector('[data-info="timeout"]').textContent, /原样保留/);
  assert.match(root.querySelector('[data-info="env"]').textContent, /future_source/);
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].timeout, null);
  assert.deepEqual(sent[0].disabled_sources, ['exa']);
  window.close();
});
