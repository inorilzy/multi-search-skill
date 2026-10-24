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

// Source labels come from the CLI's `doctor --format json`, so this page shows the path the CLI
// actually reads instead of re-deriving it.
const pathSourceText = {
  env: '环境变量 MULTI_SEARCH_CONFIG',
  user: '用户配置',
  dev_fallback: '开发目录回退',
  defaults: '内置默认值',
};

export async function mountSettings(root, api) {
  root.innerHTML = '<section class="heading"><p class="eyebrow">SETTINGS</p><h1>搜索默认设置。</h1>'
    + '<p>路由、超时和 Twitter cookie 文件路径保存在 CLI 的配置文件中。key 不写入该文件。</p></section>'
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
    const sourceLabel = pathSourceText[view.path_source] || '未知来源';
    text('[data-status="path-source"]', `${sourceLabel}（${view.file_present ? '文件已存在' : '文件尚未创建'}）`);
    const notes = [];
    if (view.path_source === 'env') notes.push('检测到 MULTI_SEARCH_CONFIG，保存会写入该路径，而不是用户配置文件。');
    if (view.read_source === 'dev_fallback') notes.push('当前显示的是开发目录中的配置（用户配置尚不存在）。');
    if (view.save_creates_override) notes.push('保存会创建用户配置文件，之后 CLI 将使用它，不再读取开发目录配置。');
    text('[data-info="env"]', notes.join(' '));
    text('[data-status="active"]', view.active_sources.length ? view.active_sources.join('、') : '无');
    text('[data-info="active-warning"]', statusText[view.status] ?? view.message ?? '');
    q('[data-field="route"]').value = view.route;
    q('[data-field="timeout"]').value = String(view.timeout);
    // Enable/disable moved to the sources page; keep the value here so a save never clears it.
    disabled = new Set(view.disabled_sources);
    q('[data-field="twitter"]').value = view.twitter_cookies_path || '';
    text('[data-info="error"]', '');
    if (view.twitter_env_overrides) {
      text('[data-info="env"]', `${q('[data-info="env"]').textContent} 检测到 TWITTER_COOKIES_PATH，它优先于这里保存的路径。`.trim());
    }
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
