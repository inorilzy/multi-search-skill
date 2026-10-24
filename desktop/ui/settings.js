// Search defaults: route, timeout and the Twitter cookie file path reference. Everything here is
// non-secret and is written by the Rust settings command. Per-source enable/disable lives on the
// sources page now, beside each source's key and test controls; this page only reports which
// sources the current route would run. It never sends or displays a key, and never reads a cookie.

import { SOURCES } from './credentials.js';
import { ROUTES as CATALOG_ROUTES } from './catalog.js';

// Both lists come from the catalog generated from Python core metadata; Rust
// reads the same `desktop/source-catalog.json` at compile time.
export const SETTINGS_SOURCES = SOURCES.map(({ source, label }) => ({ source, label }));

export const ROUTES = CATALOG_ROUTES.map(({ name, label }) => ({ value: name, label }));

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

export async function mountSettings(root, api, { number = '05' } = {}) {
  root.innerHTML = `<section class="heading"><p class="eyebrow">${number} / SETTINGS</p><h1 tabindex="-1">搜索默认设置。</h1>`
    + '<p>路由、超时和 Twitter Cookie 文件路径保存在 CLI 的配置文件中。API Key 不写入该文件。</p></section>'
    + '<section class="panel"><div class="section-title"><h2>配置文件</h2><button type="button" data-action="refresh">刷新</button></div>'
    + '<dl class="cred-status"><dt>配置文件</dt><dd data-status="path"></dd><dt>路径来源</dt><dd data-status="path-source"></dd>'
    + '<dt>当前路由会运行</dt><dd data-status="active"></dd></dl>'
    + '<p class="note" data-info="env" role="status"></p><p data-info="active-warning" role="alert"></p><p data-info="error" role="alert"></p></section>'
    + '<section class="panel"><div class="section-title"><h2>默认路由与超时</h2></div>'
    + '<form data-settings-form><label>默认路由<select data-field="route">'
    + ROUTES.map(r => `<option value="${r.value}">${r.label}</option>`).join('')
    + '</select></label><label><span data-label="timeout">超时（秒）</span><input data-field="timeout" type="number" min="1" max="90" step="1"></label>'
    + '<p class="note" data-info="timeout" role="status"></p>'
    + '<label>Twitter Cookie 文件路径（可选，仅保存路径）<input data-field="twitter" type="text" autocomplete="off" spellcheck="false" maxlength="1024" placeholder="例如 D:/secure/twitter-cookies.json"></label>'
    + '<div class="run-controls"><button type="submit" class="primary" data-action="save">保存设置</button><strong data-status="save" aria-live="polite"></strong></div>'
    + '</form></section>';

  const q = selector => root.querySelector(selector);
  const text = (selector, value) => { q(selector).textContent = value; };
  let disabled = new Set();
  let saved = null;
  let saving = false;
  // The timeout exactly as loaded. Saving sends `timeout: null` unless the user changed it, so the
  // stored value (or its absence, which means the route default) is never silently rewritten.
  let loadedTimeout = '';
  const saveButton = q('[data-action="save"]');
  const refreshButton = q('[data-action="refresh"]');
  function syncControls() {
    // Without a successfully read view there is nothing safe to save: never submit placeholders.
    saveButton.disabled = saving || saved === null || saved.status === 'config_unreadable';
    refreshButton.disabled = saving;
    saveButton.setAttribute('aria-busy', String(saving));
    saveButton.textContent = saving ? '保存中…' : '保存设置';
  }

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
    const min = view.timeout_min ?? 1;
    const max = view.timeout_max ?? 90;
    const timeoutField = q('[data-field="timeout"]');
    timeoutField.min = String(min);
    timeoutField.max = String(max);
    text('[data-label="timeout"]', `超时（秒，${min} 到 ${max}）`);
    timeoutField.value = String(view.timeout);
    loadedTimeout = timeoutField.value;
    const timeoutNotes = [];
    if (view.timeout_configured === false) timeoutNotes.push('配置文件未设置超时，当前显示的是该路由的 CLI 默认值；不修改则保存时不会写入。');
    if (view.timeout_out_of_range) timeoutNotes.push(`已保存的超时 ${view.timeout} 秒超出 ${min} 到 ${max} 秒；不修改则原样保留。`);
    text('[data-info="timeout"]', timeoutNotes.join(' '));
    // Enable/disable moved to the sources page; keep the value here so a save never clears it.
    disabled = new Set(view.disabled_sources);
    q('[data-field="twitter"]').value = view.twitter_cookies_path || '';
    text('[data-info="error"]', '');
    if (view.unknown_disabled_sources?.length) {
      text('[data-info="env"]', `${q('[data-info="env"]').textContent} 配置中还有无法识别的禁用项（${view.unknown_disabled_sources.join('、')}），保存时会原样保留。`.trim());
    }
    if (view.twitter_env_overrides) {
      text('[data-info="env"]', `${q('[data-info="env"]').textContent} 检测到 TWITTER_COOKIES_PATH，它优先于这里保存的路径。`.trim());
    }
  }

  async function refresh() {
    if (saving) return;
    refreshButton.disabled = true;
    try { fill(await api.settingsView()); }
    catch (error) {
      saved = null;
      text('[data-info="error"]', `无法读取搜索设置，保存已暂停。请点击“刷新”重试。${typeof error === 'string' ? `（${error}）` : ''}`);
    } finally { syncControls(); }
  }

  q('[data-action="refresh"]').addEventListener('click', refresh);

  q('[data-settings-form]').addEventListener('submit', async event => {
    event.preventDefault();
    if (saving || saved === null || saved.status === 'config_unreadable') return;
    const rawTimeout = q('[data-field="timeout"]').value.trim();
    let timeout = null;
    if (rawTimeout !== loadedTimeout) {
      const min = saved.timeout_min ?? 1;
      const max = saved.timeout_max ?? 90;
      const value = Number(rawTimeout);
      if (!rawTimeout || !Number.isInteger(value) || value < min || value > max) {
        text('[data-status="save"]', '');
        text('[data-info="error"]', `超时时间必须是 ${min} 到 ${max} 之间的整数秒。`);
        return;
      }
      timeout = value;
    }
    const input = {
      route: q('[data-field="route"]').value,
      timeout,
      // Unknown entries are kept by the backend from the file itself; only known names are sent.
      disabled_sources: [...disabled],
      twitter_cookies_path: q('[data-field="twitter"]').value,
    };
    saving = true;
    syncControls();
    text('[data-status="save"]', '保存中…');
    text('[data-info="error"]', '');
    try {
      fill(await api.settingsSave(input));
      text('[data-status="save"]', '已保存。');
    } catch (error) {
      text('[data-status="save"]', '');
      text('[data-info="error"]', typeof error === 'string' ? error : '保存失败，原配置未改变。');
    } finally {
      saving = false;
      syncControls();
    }
  });

  await refresh();
  return {
    dispose() {},
    get saved() { return saved; },
  };
}
