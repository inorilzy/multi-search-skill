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

test('the displayed config path and source are exactly what the CLI doctor payload reported', async () => {
  const { window, root } = setup();
  await mountSettings(root, {
    settingsView: async () => view({
      config_path: 'D:/cli/dev/multi-search-config.json',
      path_source: 'dev_fallback',
      file_present: true,
      read_source: 'dev_fallback',
      save_creates_override: true,
    }),
  });
  assert.equal(root.querySelector('[data-status="path"]').textContent, 'D:/cli/dev/multi-search-config.json');
  const source = root.querySelector('[data-status="path-source"]').textContent;
  assert.match(source, /开发目录回退/);
  assert.match(source, /文件已存在/);
  assert.match(root.querySelector('[data-info="env"]').textContent, /保存会创建用户配置文件/);
  window.close();
});

test('a missing config file is labeled as built-in defaults rather than a user file', async () => {
  const { window, root } = setup();
  await mountSettings(root, {
    settingsView: async () => view({
      config_path: 'C:/Users/test/.multi-search/multi-search-config.json',
      path_source: 'defaults',
      file_present: false,
      read_source: 'defaults',
    }),
  });
  const source = root.querySelector('[data-status="path-source"]').textContent;
  assert.match(source, /内置默认值/);
  assert.match(source, /文件尚未创建/);
  window.close();
});

test('a rejected save keeps the form and shows the error without writing a status as saved', async () => {
  const { window, root } = setup();
  const api = {
    settingsView: async () => view(),
    settingsSave: async () => { throw '超时时间必须在 1 到 60 秒之间'; },
  };
  await mountSettings(root, api);
  root.querySelector('[data-field="timeout"]').value = '99';
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(root.querySelector('[data-info="error"]').textContent, '超时时间必须在 1 到 60 秒之间');
  assert.equal(root.querySelector('[data-status="save"]').textContent, '');
  assert.equal(root.querySelector('[data-field="timeout"]').value, '99');
  window.close();
});
