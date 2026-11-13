import { SOURCES, mountCredentialBody, mountProviderAccounts, providerIdForSource } from './credentials.js';
import { createMeter, createAlertBadge } from './meter.js';
import { showError } from './api.js';
import { SOURCE_CATALOG } from './source-catalog.js';
import { oauthMethodForSource } from './oauth-login.js';

const ENTRIES = [...SOURCES, ...SOURCE_CATALOG.sources
  .filter(entry => !entry.searchable && entry.keyed)
  .map(({ name, label, keyed, key_optional, cookie, description, mark }) => ({ source: name, label, keyed, keyOptional: key_optional, cookie, description, mark, search: false }))]
  .filter((entry, index, entries) => entries.findIndex(other => providerIdForSource(other.source) === providerIdForSource(entry.source)) === index)
  .map(entry => {
    const plugin = SOURCE_CATALOG.plugins.find(item => item.id === providerIdForSource(entry.source));
    return { search: true, ...entry, label: plugin?.search_sources.length > 1 ? plugin.label : entry.label,
      searchSources: plugin?.search_sources || [entry.source] };
  });

// Catalog values are local constants, but escape them anyway: the template below is HTML.
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);

const DESCRIPTIONS = Object.fromEntries(ENTRIES.map(({ source, description }) => [source, description]));
const MARKS = Object.fromEntries(ENTRIES.map(({ source, mark }) => [source, mark]));
const FILTERS = [['all', '全部'], ['enabled', '已启用'], ['unconfigured', '未配置']];
const TOTAL = ENTRIES.length;
const IDLE = { kind: 'idle', title: '尚未测试', message: '' };
const icon = name => {
  const paths = {
    lock: '<rect x="6" y="10" width="12" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
    search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
    key: '<circle cx="15" cy="8" r="5"/><path d="m11 12-8 8v-4l3-3h3"/>',
    toggle: '<rect x="2" y="6" width="20" height="12" rx="6"/><circle cx="15" cy="12" r="3"/>',
    alert: '<path d="M12 3 2 21h20L12 3ZM12 9v5M12 17v1"/>',
    box: '<path d="m12 2 9 5v10l-9 5-9-5V7l9-5ZM3 7l9 5 9-5M12 12v10"/>',
    play: '<path d="m7 4 13 8-13 8V4Z"/>',
    chevron: '<path d="m9 6 6 6-6 6"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]}</svg>`;
};
/// "⌘ K" on Apple platforms, "Ctrl K" elsewhere. The handler already accepts both modifiers.
/** @param {any} [nav] Navigator-like; `userAgentData` is not in every DOM lib yet. */
export function shortcutLabel(nav = globalThis.navigator) {
  const platform = `${nav?.userAgentData?.platform || nav?.platform || nav?.userAgent || ''}`;
  return /mac|iphone|ipad|ipod/i.test(platform) ? '⌘ K' : 'Ctrl K';
}
// One compact line of counts (magpie keeps the providers page to the list itself).
function statCard(key, label) {
  return `<span class="stat stat-${key}">${label} <b data-stat="${key}">—</b><small>/${key === 'enabled' ? ENTRIES.filter(entry => entry.search !== false).length : TOTAL}</small></span>`;
}

/** @param {any} root page container (untyped DOM queries, as in the other pages) @param {any} api @param {{ signal?: AbortSignal, number?: string }} [options] */
export async function mountSources(root, api, { signal, number = '04' } = {}) {
  const doc = root.ownerDocument;
  const shortcut = shortcutLabel(doc.defaultView?.navigator);
  root.classList.add('sources-page');
  root.innerHTML = `<section class="heading sources-head"><div><p class="eyebrow">${number} / PROVIDERS</p><h1 tabindex="-1">服务商</h1></div></section>
    <div class="sources-overview"><section class="stats" aria-label="服务商概览">${statCard('enabled', '已启用')}${statCard('configured', '已配置')}${statCard('error', '异常')}${statCard('absent', '未配置')}</section>
    <div class="toolbar"><div class="filters" role="group" aria-label="筛选">${FILTERS.map(([key, label]) => `<button type="button" data-filter="${key}" aria-pressed="${key === 'all'}">${label}</button>`).join('')}</div><label class="source-search">${icon('search')}<input type="search" data-search aria-label="查找服务商" placeholder="查找服务商" aria-keyshortcuts="${shortcut === '⌘ K' ? 'Meta+K' : 'Control+K'}"><kbd>${shortcut}</kbd></label></div></div>
    <p class="row-error" data-list-error role="alert"></p><p class="row-error" data-cache-error role="alert"></p><button type="button" data-action="retry-settings" hidden>重试读取设置</button><div class="provider-list" data-source-list role="list" aria-label="服务商列表"></div><p class="sources-empty" data-empty hidden>没有匹配的搜索源，请调整关键词或筛选条件。</p>`;

  const list = root.querySelector('[data-source-list]');
  const search = root.querySelector('[data-search]');
  const rows = new Map();
  let settingsState = null;
  let accountGroups = null;
  let usageProviders = new Map();
  let cacheGeneration = 0;
  async function loadCache() {
    const generation = ++cacheGeneration;
    const results = await Promise.allSettled([
      api.accountsView?.(),
      api.usageView?.(),
    ]);
    if (disposed || generation !== cacheGeneration) return;
    const [accounts, usage] = results;
    root.querySelector('[data-cache-error]').textContent = '';
    if (accounts.status === 'fulfilled' && accounts.value) {
      accountGroups = accounts.value.accounts;
      if (accounts.value.status !== 'ready') root.querySelector('[data-cache-error]').textContent = accounts.value.message;
    } else if (accounts.status === 'rejected') showError(root.querySelector('[data-cache-error]'), accounts.reason, '账号读取失败，请重新进入本页重试。');
    if (usage.status === 'fulfilled' && usage.value) {
      usageProviders = new Map(usage.value.providers.map(provider => [provider.id, provider]));
      if (usage.value.status && usage.value.status !== 'ready') root.querySelector('[data-cache-error]').textContent = usage.value.message;
    } else if (usage.status === 'rejected') showError(root.querySelector('[data-cache-error]'), usage.reason, '缓存用量读取失败，请重新进入本页重试。');
    for (const rec of rows.values()) renderCache(rec);
  }
  function renderCache(rec) {
    const providerId = providerIdForSource(rec.entry.source);
    const provider = usageProviders.get(providerId);
    const accounts = accountGroups?.[providerId] || provider?.accounts;
    if (accounts) {
      const shown = accounts.filter(account => account.id !== 'default' || account.keys.length || Object.keys(account.balance_credentials || {}).length || accounts.length === 1);
      rec.keyCount.textContent = `${shown.length} 个账号 · ${accounts.reduce((sum, account) => sum + account.keys.length, 0)} 个 Key`;
    }
    const meter = rec.row.querySelector('[data-provider-meter]');
    if (provider?.balance_supported === false) {
      const { search, scrape } = provider.calls?.today || {};
      const today = typeof search === 'number' && typeof scrape === 'number' ? search + scrape : '未知';
      meter.textContent = `无余额接口 · 今天调用 ${today} 次`;
    } else meter.replaceChildren(createMeter(doc, provider?.total, { thin: true, label: `${rec.entry.label} 合计余额` }));
    const badge = createAlertBadge(doc, provider?.alert);
    if (badge) meter.querySelector('.meter-state')?.remove();
    rec.state.hidden = Boolean(badge);
    const status = rec.row.querySelector('[data-provider-alert]');
    status.replaceChildren(...(badge ? [badge] : []));
  }
  let settingsRevision = 0;
  let expanded = null;
  let detailMount = null;
  let activeTicket = 0;
  let filter = 'all';
  let disposed = false;
  let settingsQueue = Promise.resolve();
  const onKey = event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); search.focus(); }
    if (event.key === 'Escape' && expanded) { event.preventDefault(); const pick = rows.get(expanded)?.pick; collapse(); pick?.focus(); }
  };
  doc.addEventListener('keydown', onKey);
  function teardown() {
    if (disposed) return;
    disposed = true;
    activeTicket += 1;
    detailMount?.dispose();
    doc.removeEventListener('keydown', onKey);
    root.classList.remove('sources-page');
  }
  // Navigation aborts the signal even if this mount throws before it can return its disposer.
  signal?.addEventListener('abort', teardown, { once: true });

  function applyFilter() {
    const query = search.value.trim().toLowerCase();
    let visible = 0;
    for (const rec of rows.values()) {
      const text = `${rec.entry.label} ${rec.entry.source} ${DESCRIPTIONS[rec.entry.source]}`.toLowerCase();
      const match = (!query || text.includes(query)) && (filter === 'all' || (filter === 'enabled' ? settingsState && rec.box?.checked : rec.kind === 'absent'));
      rec.row.hidden = !match;
      if (match) visible += 1;
    }
    root.querySelector('[data-empty]').hidden = visible !== 0;
  }
  function refreshStats() {
    if (disposed) return;
    const all = [...rows.values()];
    const count = predicate => all.filter(predicate).length;
    const values = {
      enabled: settingsState ? count(rec => rec.box?.checked) : '—',
      configured: count(rec => rec.kind === 'configured'),
      error: count(rec => rec.kind === 'error' || rec.test.kind === 'error'),
      absent: count(rec => rec.kind === 'absent'),
    };
    for (const [key, n] of Object.entries(values)) root.querySelector(`[data-stat="${key}"]`).textContent = n;
    for (const [key, label] of FILTERS) root.querySelector(`[data-filter="${key}"]`).textContent = `${label}（${key === 'all' ? TOTAL : key === 'enabled' ? values.enabled : values.absent}）`;
    applyFilter();
  }
  function renderToggle(rec) {
    if (!rec.box) return;
    rec.row.querySelector('[data-toggle-label]').textContent = settingsState ? rec.box?.checked ? '已启用' : '未启用' : '状态未知';
    rec.row.classList.toggle('is-off', Boolean(settingsState) && !rec.box.checked);
  }
  function applySettings(view) {
    const stamp = value => JSON.stringify([value?.route, value?.timeout, value?.disabled_sources, value?.twitter_cookies_path]);
    if (settingsState && stamp(settingsState) !== stamp(view)) {
      // The credentials a row would test may have changed; never keep a stale verdict.
      settingsRevision += 1;
      for (const rec of rows.values()) updateTest(rec, IDLE);
    }
    settingsState = view;
    const disabled = new Set(view.disabled_sources || []);
    for (const rec of rows.values()) {
      if (rec.box) rec.box.checked = rec.entry.searchSources.every(source => !disabled.has(source));
      if (rec.box) rec.box.disabled = false;
      renderToggle(rec);
      if (rec.entry.cookie) {
        const configured = Boolean(view.twitter_cookies_path || rec.cookieConfigured);
        setRow(rec, configured ? 'configured' : 'absent', configured ? 'Cookie 路径已配置' : '未配置 Cookie 路径');
      }
    }
    refreshStats();
  }
  async function toggleEnabled(rec, enabled) {
    if (disposed) return;
    for (const item of rows.values()) if (item.box) item.box.disabled = true;
    rec.error.textContent = '';
    try {
      const view = await api.settingsView();
      if (disposed) return;
      const disabled = new Set(view.disabled_sources || []);
      for (const source of rec.entry.searchSources) {
        if (enabled) disabled.delete(source); else disabled.add(source);
      }
      // timeout: null keeps the stored timeout untouched; a toggle never rewrites it.
      const saved = await api.settingsSave({ route: view.route, timeout: null, disabled_sources: [...disabled], twitter_cookies_path: view.twitter_cookies_path ?? '' });
      if (!disposed) applySettings(saved);
    } catch (error) {
      if (disposed) return;
      showError(rec.error, error, '保存失败，开关未更改。');
      if (settingsState) applySettings(settingsState);
    }
  }
  function setRow(rec, kind, text) {
    if (disposed) return;
    rec.kind = kind;
    rec.state.dataset.kind = kind;
    rec.state.textContent = text;
    rec.summary.textContent = kind === 'configured' ? rec.entry.cookie ? 'Cookie 文件' : '••••••••••••••••••' : rec.entry.cookie ? 'Cookie 路径' : rec.entry.keyOptional ? '可选' : rec.entry.keyed ? '—' : '无需配置';
    rec.summaryText.textContent = kind === 'configured' ? rec.entry.cookie ? 'Cookie 路径已配置' : 'API Key 已配置（不显示）' : rec.entry.keyOptional ? '未配置（可选，无 Key 也能用）' : rec.entry.keyed || rec.entry.cookie ? '未配置' : '无需配置';
    refreshStats();
  }
  function updateRow(rec, view) {
    if (disposed) return;
    if (rec.entry.keyed) {
      const fileCount = Number.isInteger(view.file_key_count) && view.file_key_count >= 0 ? view.file_key_count : view.store?.state === 'absent' ? 0 : null;
      const envCount = view.effective_source === 'env' || Boolean(view.env_var) ? 1 : 0;
      rec.keyCount.textContent = fileCount === null ? '账号数未知 · Key 数未知' : `账号数未知 · ${fileCount + envCount} 个 Key`;
      renderCache(rec);
    }
    if (rec.oauth?.credential === rec.entry.source) {
      const configured = ['env', 'file'].includes(view.effective_source);
      rec.login.textContent = configured ? '浏览器登录：凭据已配置' : view.effective_source === 'none' && view.store?.state === 'absent' ? '浏览器登录：未登录' : '浏览器登录：状态未知';
    }
    const provenance = JSON.stringify([view.effective_source, view.store?.state, view.store?.saved_at]);
    if (rec.provenance && rec.provenance !== provenance) updateTest(rec, IDLE);
    rec.provenance = provenance;
    // Core's effective_source is the truth for how the CLI authenticates: env wins over the
    // keys file. A keys file that cannot be read is an error unless env already supplies the key.
    // Unknown future values stay readable.
    if (rec.entry.cookie) {
      rec.cookieConfigured = view.effective_source !== 'none';
      const configured = rec.cookieConfigured || Boolean(settingsState?.twitter_cookies_path);
      return setRow(rec, configured ? 'configured' : 'absent', configured ? 'Cookie 路径已配置' : '未配置 Cookie 路径');
    }
    if (view.effective_source !== 'env' && view.store?.state === 'unavailable') return setRow(rec, 'error', 'Key 文件无法读取');
    if (view.effective_source === 'none') return setRow(rec, 'absent', '未配置');
    const labels = { env: '环境变量生效', file: 'Key 文件生效' };
    setRow(rec, 'configured', labels[view.effective_source] || '状态未知');
  }
  function updateTest(rec, result) {
    if (disposed) return;
    rec.test = { ...result };
    rec.result.dataset.kind = result.kind;
    if (rec.entry.search === false) return;
    rec.result.querySelector('strong').textContent = ({ idle: '未测试', running: '正在测试', success: '连接成功', error: '测试失败' })[result.kind];
    rec.result.querySelector('small').textContent = result.kind === 'success' ? '本次连接已验证' : result.kind === 'error' ? result.title : rec.entry.cookie ? '使用本机 Cookie' : !rec.entry.keyed ? '无需 API Key' : rec.entry.keyOptional ? '无需 API Key，可选填 Key 提高额度' : '点击测试验证';
    rec.result.title = [result.title, result.message].filter(Boolean).join('\n');
    rec.testButton.disabled = result.kind === 'running';
    refreshStats();
  }
  function buildRow(entry) {
    const oauth = oauthMethodForSource(entry.source);
    const row = doc.createElement('article');
    row.className = 'provider-row';
    row.setAttribute('role', 'listitem');
    row.dataset.expanded = 'false';
    row.setAttribute('data-source-row', entry.source);
    const id = esc(entry.source);
    row.innerHTML = `<div class="provider-summary" data-row-click><span class="provider-icon" aria-hidden="true">${esc(MARKS[entry.source])}</span>
      <div class="provider-identity"><button type="button" class="provider-name" data-pick="${id}" aria-expanded="false" aria-controls="detail-${id}">${esc(entry.label)}</button>
      <p class="provider-sub"><span class="provider-counts" data-key-count>${entry.keyed ? '读取中' : '0 个账号 · 0 个 Key'}</span><span class="provider-sep" aria-hidden="true">·</span><span data-row-status data-kind="unknown">读取中</span></p></div>
      <div class="provider-meter" data-provider-meter></div><div class="provider-status"><span data-provider-alert></span></div>
      ${entry.search === false ? '<span class="provider-toggle provider-note">仅抓取</span>' : `<label class="provider-toggle source-toggle"><input type="checkbox" role="switch" data-toggle="${id}" aria-label="启用 ${esc(entry.label)}" disabled><span class="toggle-track" aria-hidden="true"></span><span class="visually-hidden" data-toggle-label>状态未知</span></label>`}
      <button type="button" class="provider-expand" data-expand aria-label="展开 ${esc(entry.label)}" aria-expanded="false" aria-controls="detail-${id}">${icon('chevron')}</button></div>
      <p class="row-error" data-row-error role="alert"></p>
      <div id="detail-${id}" class="provider-details provider-dialog" data-provider-details hidden>
      <div class="provider-dialog-backdrop" data-dialog-close></div>
      <section class="provider-dialog-panel" role="dialog" aria-modal="true" aria-labelledby="dialog-title-${id}">
      <header class="provider-dialog-head"><span class="provider-icon" aria-hidden="true">${esc(MARKS[entry.source])}</span><h2 id="dialog-title-${id}">${esc(entry.label)}</h2><button type="button" class="dialog-close" data-dialog-close aria-label="关闭">${icon('close')}</button></header>
      <div class="provider-dialog-body">
      <div class="dialog-field"><span class="dialog-label">说明</span><div><p class="provider-note">${esc(DESCRIPTIONS[entry.source])}</p><p class="provider-note"><span data-key-summary aria-hidden="true">—</span> <span data-key-summary-text>未配置</span>${oauth ? ' · <span data-login-status>浏览器登录：状态未知</span>' : ''}</p></div></div>
      <div class="dialog-field"><span class="dialog-label">连接</span><div class="provider-actions"><div data-row-result data-kind="idle"><strong>${entry.search === false ? '仅用于抓取' : '未测试'}</strong><small>${entry.search === false ? '不提供搜索连接测试' : '点击测试验证'}</small></div>${entry.search === false ? '' : `<button type="button" data-row-test aria-label="测试 ${esc(entry.label)}">测试连接</button>`}</div></div>
      <div class="dialog-field"><span class="dialog-label">${entry.keyed ? '账号' : '凭据'}</span><div data-source-detail></div></div></div>
      <footer class="provider-dialog-foot"><p class="provider-note">凭据只保存在本机；测试会向服务商发请求，可能消耗额度。</p><button type="button" class="primary" data-dialog-close>完成</button></footer>
      </section></div>`;
    const rec = { entry, row, pick: row.querySelector('[data-pick]'), box: row.querySelector('[data-toggle]'), state: row.querySelector('[data-row-status]'), summary: row.querySelector('[data-key-summary]'), summaryText: row.querySelector('[data-key-summary-text]'), result: row.querySelector('[data-row-result]'), testButton: row.querySelector('[data-row-test]'), error: row.querySelector('[data-row-error]'), detail: row.querySelector('[data-source-detail]'), kind: entry.keyed || entry.cookie ? 'unknown' : 'keyless', test: { ...IDLE } };
    // Account-only OAuth credentials are not exposed by credential_status. Their login
    // state stays unknown until this page observes a completed browser login.
    Object.assign(rec, { oauth, login: row.querySelector('[data-login-status]'), keyCount: row.querySelector('[data-key-count]') });
    rows.set(entry.source, rec);
    list.append(row);
    if (!entry.keyed && !entry.cookie) setRow(rec, 'keyless', '无需凭据');
    rec.pick.addEventListener('click', () => { void toggleRow(entry.source); });
    row.querySelector('[data-expand]').addEventListener('click', () => { void toggleRow(entry.source); });
    // Like magpie, the whole row opens the provider; its own controls keep their meaning.
    row.querySelector('[data-row-click]').addEventListener('click', event => {
      if (event.target.closest('button, input, label, a')) return;
      void toggleRow(entry.source);
    });
    for (const close of row.querySelectorAll('[data-dialog-close]')) close.addEventListener('click', () => {
      if (expanded !== entry.source) return;
      collapse(); rec.pick.focus();
    });
    rec.box?.addEventListener('change', event => {
      const enabled = event.target.checked;
      for (const item of rows.values()) if (item.box) item.box.disabled = true;
      settingsQueue = settingsQueue.then(() => toggleEnabled(rec, enabled));
    });
    rec.testButton?.addEventListener('click', async () => {
      rec.testButton.disabled = true;
      try {
        if (expanded !== entry.source) await toggleRow(entry.source);
        if (!disposed && expanded === entry.source) rec.detail.querySelector('[data-action="test"]')?.click();
      } finally { if (!disposed) rec.testButton.disabled = rec.test.kind === 'running'; }
    });
  }
  function collapse() {
    activeTicket += 1;
    detailMount?.dispose();
    detailMount = null;
    if (!expanded) return;
    const rec = rows.get(expanded);
    if (rec.test.kind === 'running') updateTest(rec, IDLE);
    rec.row.dataset.expanded = 'false';
    for (const button of [rec.pick, rec.row.querySelector('[data-expand]')]) button.setAttribute('aria-expanded', 'false');
    rec.row.querySelector('[data-expand]').setAttribute('aria-label', `展开 ${rec.entry.label}`);
    rec.detail.hidden = true;
    rec.row.querySelector('[data-provider-details]').hidden = true;
    rec.detail.innerHTML = '';
    expanded = null;
  }
  async function toggleRow(source) {
    if (disposed) return;
    if (expanded === source) { collapse(); return; }
    collapse();
    const rec = rows.get(source);
    const ticket = ++activeTicket;
    expanded = source;
    rec.row.dataset.expanded = 'true';
    for (const button of [rec.pick, rec.row.querySelector('[data-expand]')]) button.setAttribute('aria-expanded', 'true');
    rec.row.querySelector('[data-expand]').setAttribute('aria-label', `收起 ${rec.entry.label}`);
    rec.detail.hidden = false;
    rec.row.querySelector('[data-provider-details]').hidden = false;
    rec.row.querySelector('.dialog-close')?.focus();
    if (!rec.entry.keyed) {
      const mounted = await mountKeylessDetail(rec);
      if (disposed || ticket !== activeTicket) { mounted.dispose(); return; }
      detailMount = mounted;
      return;
    }
    const body = doc.createElement('div');
    rec.detail.append(body);
    const previous = { ...rec.test };
    const previousProvenance = rec.provenance;
    const mount = /** @type {any} */ (typeof api.accountsView === 'function' ? mountProviderAccounts : mountCredentialBody);
    const mounted = await mount(body, api, {
      source,
      onChange: loadCache,
      onStatus: view => { if (!disposed && ticket === activeTicket) updateRow(rec, view); },
      onTest: result => { if (!disposed && ticket === activeTicket) updateTest(rec, result); },
      onLogin: () => { if (!disposed && ticket === activeTicket && rec.login) rec.login.textContent = '浏览器登录：已登录'; },
    });
    if (disposed || ticket !== activeTicket) { mounted.dispose(); return; }
    // 凭据来源未变才恢复本页面内的上次结果，不持久化验证承诺。
    if (mount === mountCredentialBody && previousProvenance === rec.provenance && previous.kind !== 'running') {
      updateTest(rec, previous);
      body.querySelector('[data-status="test"]').textContent = previous.title;
      body.querySelector('[data-info="test"]').textContent = previous.message;
      body.querySelector('[data-test-result]').dataset.kind = previous.kind;
    }
    detailMount = mounted;
  }
  async function mountKeylessDetail(rec) {
    const panel = doc.createElement('section');
    panel.className = 'keyless-detail';
    panel.innerHTML = `<div><p>${rec.entry.cookie ? '在搜索设置页配置 Cookie 文件路径；此处不读取或显示 Cookie 正文。' : '该服务无需 API Key，可直接测试连接。'}</p><p class="credential-note">测试会发送外部搜索请求，请只在需要时测试。</p><button type="button" data-action="test">测试连接</button></div><div class="test-result" data-kind="idle"><div><strong data-status="test" aria-live="polite"></strong><p data-info="test" role="status"></p></div></div>`;
    rec.detail.append(panel);
    let stale = false;
    const button = panel.querySelector('button');
    const show = result => {
      if (stale || disposed) return;
      updateTest(rec, result);
      panel.querySelector('[data-status="test"]').textContent = result.title;
      panel.querySelector('[data-info="test"]').textContent = result.message;
      panel.querySelector('.test-result').dataset.kind = result.kind;
    };
    show(rec.test);
    button.addEventListener('click', async () => {
      button.disabled = true;
      show({ kind: 'running', title: '正在测试', message: '' });
      try {
        const outcome = await api.credentialTest(rec.entry.source);
        show({ kind: outcome.result === 'success' ? 'success' : 'error', title: outcome.result === 'success' ? '测试成功' : '测试失败', message: outcome.message || outcome.result });
      } catch (error) { show({ kind: 'error', title: '测试失败', message: showError(panel.querySelector('[data-info="test"]'), error, '测试启动失败，请检查 CLI 后重试。').message }); }
      finally { if (!stale && !disposed) button.disabled = false; }
    });
    return { dispose() { stale = true; } };
  }

  for (const entry of ENTRIES) buildRow(entry);
  for (const button of root.querySelectorAll('[data-filter]')) button.addEventListener('click', () => {
    filter = button.dataset.filter;
    for (const other of root.querySelectorAll('[data-filter]')) other.setAttribute('aria-pressed', String(other === button));
    applyFilter();
  });
  search.addEventListener('input', applyFilter);
  const loads = ENTRIES.filter(entry => entry.keyed || entry.cookie).map(entry => api.credentialStatus(entry.source).then(view => updateRow(rows.get(entry.source), view), error => {
    if (disposed) return;
    const rec = rows.get(entry.source);
    setRow(rec, 'error', '状态读取失败');
    rec.keyCount.textContent = '账号数未知 · Key 数未知';
    renderCache(rec);
    showError(rec.error, error, '状态读取失败，请重新进入本页重试。');
  }));
  const retrySettings = root.querySelector('[data-action="retry-settings"]');
  async function loadSettings() {
    try {
      applySettings(await api.settingsView());
      root.querySelector('[data-list-error]').textContent = '';
      retrySettings.hidden = true;
    } catch (error) {
      retrySettings.hidden = false;
      showError(root.querySelector('[data-list-error]'), error, '无法读取搜索设置，开关状态未知。');
    }
  }
  retrySettings.addEventListener('click', () => { retrySettings.disabled = true; void loadSettings().finally(() => { retrySettings.disabled = false; }); });
  await Promise.all([loadSettings(), loadCache(), ...loads]);
  // No row is expanded on entry: opening a detail re-reads its status, and the overview above
  // already has every row's status, so an automatic expansion only cost an extra request.
  refreshStats();
  return { dispose() { signal?.removeEventListener('abort', teardown); teardown(); } };
}
