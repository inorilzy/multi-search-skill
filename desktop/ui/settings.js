// Search defaults: route, timeout and the Twitter cookie file path reference. Everything here is
// non-secret and is written by the Rust settings command. Per-source enable/disable lives on the
// sources page now, beside each source's key and test controls; this page only reports which
// sources the current route would run. It never sends or displays a key, and never reads a cookie.

import { SOURCES } from './credentials.js';

// Mirrors ALL_SOURCE_NAMES in search_runner.py and SOURCES in desktop/src-tauri/src/settings.rs.
export const SETTINGS_SOURCES = SOURCES.map(({ source, label }) => ({ source, label }));

export const ROUTES = [
  { value: 'default', label: '默认（网页综合）' },
  { value: 'fast', label: '快速' },
  { value: 'all', label: '全部' },
  { value: 'social', label: '社交（Twitter）' },
  { value: 'dev', label: '开发者（Stack Overflow / GitHub / Hacker News）' },
];

const statusText = {
  ok: '',
  no_active_source: '当前路由没有可用的搜索源，搜索不会运行。请至少启用一个搜索源。',
  config_unreadable: '现有配置文件无法读取，保存已被阻止。',
};

export async function mountSettings(root, api) {
  root.innerHTML = '<section class="heading"><p class="eyebrow">SETTINGS</p><h1>搜索默认设置。</h1>'
    + '<p>路由、超时和 Twitter cookie 文件路径保存在 SQLite 中。API Key 在同一数据库中由 DPAPI 加密保存。</p></section>'
    + '<section class="panel"><div class="section-title"><h2>配置文件</h2><button type="button" data-action="refresh">刷新</button></div>'
    + '<dl class="cred-status"><dt>配置文件</dt><dd data-status="path"></dd><dt>路径来源</dt><dd data-status="path-source"></dd>'
    + '<dt>当前路由会运行</dt><dd data-status="active"></dd></dl>'
    + '<p class="note" data-info="env" role="status"></p><p data-info="active-warning" role="alert"></p><p data-info="error" role="alert"></p></section>'
    + '<section class="panel"><div class="section-title"><h2>默认路由与超时</h2></div>'
    + '<form data-settings-form><label>默认路由<select data-field="route">'
    + ROUTES.map(r => `<option value="${r.value}">${r.label}</option>`).join('')
    + '</select></label><label>超时（秒，1 到 60）<input data-field="timeout" type="number" min="1" max="60" step="1"></label>'
    + '<label>Twitter cookie 文件路径（可选，仅保存路径）<input data-field="twitter" type="text" autocomplete="off" spellcheck="false" maxlength="1024" placeholder="例如 D:/secure/twitter-cookies.json"></label>'
    + '<div class="run-controls"><button type="submit" class="primary" data-action="save">保存设置</button><strong data-status="save" aria-live="polite"></strong></div>'
    + '</form></section>';

  const q = selector => root.querySelector(selector);
  const text = (selector, value) => { q(selector).textContent = value; };
  let disabled = new Set();
  let saved = null;

  function fill(view) {
    saved = view;
    text('[data-status="path"]', view.config_path || '无法确定配置文件位置');
    text('[data-status="path-source"]', view.path_source === 'env' ? `隔离数据库 MULTI_SEARCH_CONFIG_DB（${view.file_present ? '已存在' : '尚未创建'}）` : `用户 SQLite 配置（${view.file_present ? '已存在' : '尚未创建'}）`);
    text('[data-info="env"]', 'SQLite 是唯一生效来源；旧 JSON、凭据库和环境变量须在迁移页显式导入。');
    text('[data-status="active"]', view.active_sources.length ? view.active_sources.join('、') : '无');
    text('[data-info="active-warning"]', statusText[view.status] ?? view.message ?? '');
    q('[data-field="route"]').value = view.route;
    q('[data-field="timeout"]').value = String(view.timeout);
    // Enable/disable moved to the sources page; keep the value here so a save never clears it.
    disabled = new Set(view.disabled_sources);
    q('[data-field="twitter"]').value = view.twitter_cookies_path || '';
    text('[data-info="error"]', '');
  }

  async function refresh() {
    try { fill(await api.settingsView()); }
    catch { text('[data-info="error"]', '无法读取搜索设置，请重试。'); }
  }

  q('[data-action="refresh"]').addEventListener('click', refresh);

  q('[data-settings-form]').addEventListener('submit', async event => {
    event.preventDefault();
    const input = {
      route: q('[data-field="route"]').value,
      timeout: Number(q('[data-field="timeout"]').value),
      disabled_sources: [...disabled],
      twitter_cookies_path: q('[data-field="twitter"]').value,
    };
    text('[data-status="save"]', '保存中…');
    try {
      fill(await api.settingsSave(input));
      text('[data-status="save"]', '已保存。');
    } catch (error) {
      text('[data-status="save"]', '');
      text('[data-info="error"]', typeof error === 'string' ? error : '保存失败，原配置未改变。');
    }
  });

  await refresh();
  return {
    dispose() {},
    get saved() { return saved; },
  };
}
