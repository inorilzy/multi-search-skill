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

test('settings page lists all 12 CLI sources, each with an enable toggle', async () => {
  const { window, root } = setup();
  await mountSettings(root, { settingsView: async () => view() });
  const names = [...root.querySelectorAll('[data-source-toggle]')].map(node => node.dataset.sourceToggle);
  assert.equal(names.length, 12);
  assert.deepEqual(names, SETTINGS_SOURCES.map(s => s.source));
  assert.ok(names.every(name => !name.includes('-')), 'CLI source names use underscores');
  window.close();
});

test('saving writes disabled_sources from unchecked toggles, plus route and timeout', async () => {
  const { window, root } = setup();
  let sent = null;
  const api = {
    settingsView: async () => view({ disabled_sources: ['exa'] }),
    settingsSave: async input => { sent = input; return view({ route: input.route, timeout: input.timeout, disabled_sources: input.disabled_sources }); },
  };
  await mountSettings(root, api);
  assert.equal(root.querySelector('[data-source-toggle="exa"]').checked, false);
  root.querySelector('[data-source-toggle="exa"]').checked = true;
  root.querySelector('[data-source-toggle="brave"]').checked = false;
  root.querySelector('[data-field="route"]').value = 'fast';
  root.querySelector('[data-field="timeout"]').value = '30';
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.deepEqual(sent, {
    route: 'fast',
    timeout: 30,
    disabled_sources: ['brave'],
    twitter_cookies_path: '',
  });
  assert.equal(root.querySelector('[data-status="save"]').textContent, '已保存。');
  window.close();
});

test('no-active-source status is shown explicitly and never re-enables a source', async () => {
  const { window, root } = setup();
  await mountSettings(root, {
    settingsView: async () => view({
      active_sources: [],
      status: 'no_active_source',
      disabled_sources: ['twitter'],
    }),
  });
  assert.match(root.querySelector('[data-info="active-warning"]').textContent, /没有可用的搜索源/);
  assert.equal(root.querySelector('[data-source-toggle="twitter"]').checked, false, 'disabled stays disabled');
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
