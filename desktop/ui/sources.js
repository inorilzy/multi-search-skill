import { SOURCES, mountCredentialBody } from './credentials.js';

const DESCRIPTIONS = Object.fromEntries(SOURCES.map(({ source, description }) => [source, description]));
const MARKS = Object.fromEntries(SOURCES.map(({ source, mark }) => [source, mark]));
const FILTERS = [['all', '全部'], ['enabled', '已启用'], ['unconfigured', '未配置']];
const TOTAL = SOURCES.length;
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
    chevron: '<path d="m7 9 5 5 5-5"/>',
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]}</svg>`;
};
function statCard(key, label, symbol) {
  return `<div class="stat stat-${key}"><span class="stat-symbol">${icon(symbol)}</span><div><span>${label}</span><strong><b data-stat="${key}">—</b><small> / ${TOTAL}</small></strong></div></div>`;
}

export async function mountSources(root, api) {
  const doc = root.ownerDocument;
  root.classList.add('sources-page');
  root.innerHTML = `<section class="heading sources-head"><div><p class="eyebrow">SOURCES</p><h1>搜索源与凭据</h1><p>管理各搜索源的 API Key 和启用状态，并可快速测试连接，确保服务可用。</p></div>
    <aside class="key-hint"><span>${icon('lock')}</span><div><strong>凭据保存在本地</strong><p>测试时仅向对应服务商发送认证请求，不回显已保存的 Key。</p></div></aside></section>
    <div class="sources-overview"><section class="stats" aria-label="搜索源概览">${statCard('enabled', '已启用', 'toggle')}${statCard('configured', '已配置', 'key')}${statCard('error', '异常', 'alert')}${statCard('absent', '未配置', 'box')}</section>
    <div class="toolbar"><label class="source-search">${icon('search')}<input type="search" data-search aria-label="搜索搜索源" placeholder="搜索搜索源名称、描述…"><kbd>Ctrl K</kbd></label><div class="filters" role="group" aria-label="筛选">${FILTERS.map(([key, label]) => `<button type="button" data-filter="${key}" aria-pressed="${key === 'all'}">${label}</button>`).join('')}</div></div></div>
    <p class="source-test-warning">测试会向对应服务发送外部请求，可能消耗额度。已配置不代表连接已验证；无需凭据的服务不计入已配置数量。</p>
    <p class="row-error" data-list-error role="alert"></p><div class="source-list" data-source-list aria-label="搜索源列表"></div><p class="sources-empty" data-empty hidden>没有匹配的搜索源，请调整关键词或筛选条件。</p>`;

  const list = root.querySelector('[data-source-list]');
  const search = root.querySelector('[data-search]');
  const rows = new Map();
  let settingsState = null;
  let expanded = null;
  let detailMount = null;
  let activeTicket = 0;
  let filter = 'all';
  let disposed = false;
  let settingsQueue = Promise.resolve();
  const onKey = event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); search.focus(); }
  };
  doc.addEventListener('keydown', onKey);

  function applyFilter() {
    const query = search.value.trim().toLowerCase();
    let visible = 0;
    for (const rec of rows.values()) {
      const text = `${rec.entry.label} ${rec.entry.source} ${DESCRIPTIONS[rec.entry.source]}`.toLowerCase();
      const match = (!query || text.includes(query)) && (filter === 'all' || (filter === 'enabled' ? settingsState && rec.box.checked : rec.kind === 'absent'));
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
      enabled: settingsState ? count(rec => rec.box.checked) : '—',
      configured: count(rec => rec.kind === 'configured'),
      error: count(rec => rec.kind === 'error' || rec.test.kind === 'error'),
      absent: count(rec => rec.kind === 'absent'),
    };
    for (const [key, n] of Object.entries(values)) root.querySelector(`[data-stat="${key}"]`).textContent = n;
    for (const [key, label] of FILTERS) root.querySelector(`[data-filter="${key}"]`).textContent = `${label}（${key === 'all' ? TOTAL : key === 'enabled' ? values.enabled : values.absent}）`;
    applyFilter();
  }
  function renderToggle(rec) {
    rec.row.querySelector('[data-toggle-label]').textContent = settingsState ? rec.box.checked ? '已启用' : '未启用' : '状态未知';
  }
  function applySettings(view) {
    settingsState = view;
    const disabled = new Set(view.disabled_sources || []);
    for (const rec of rows.values()) {
      rec.box.checked = !disabled.has(rec.entry.source);
      rec.box.disabled = false;
      renderToggle(rec);
      if (rec.entry.cookie) {
        const configured = Boolean(view.twitter_cookies_path || view.twitter_env_overrides);
        setRow(rec, configured ? 'configured' : 'absent', configured ? 'Cookie 路径已配置' : '未配置 Cookie 路径');
      }
    }
    refreshStats();
  }
  async function toggleEnabled(rec, enabled) {
    if (disposed) return;
    for (const item of rows.values()) item.box.disabled = true;
    rec.error.textContent = '';
    try {
      const view = await api.settingsView();
      if (disposed) return;
      const disabled = new Set(view.disabled_sources || []);
      if (enabled) disabled.delete(rec.entry.source); else disabled.add(rec.entry.source);
      const saved = await api.settingsSave({ route: view.route, timeout: view.timeout, disabled_sources: [...disabled], twitter_cookies_path: view.twitter_cookies_path ?? '' });
      if (!disposed) applySettings(saved);
    } catch (err) {
      if (disposed) return;
      rec.error.textContent = typeof err === 'string' ? err : '保存失败，开关未更改。';
      if (settingsState) applySettings(settingsState);
    }
  }
  function setRow(rec, kind, text) {
    if (disposed) return;
    rec.kind = kind;
    rec.state.dataset.kind = kind;
    rec.state.textContent = text;
    rec.summary.textContent = kind === 'configured' ? rec.entry.cookie ? 'Cookie 文件' : '••••••••••••••••••' : rec.entry.cookie ? 'Cookie 路径' : rec.entry.keyed ? '—' : '无需配置';
    refreshStats();
  }
  function updateRow(rec, view) {
    const provenance = JSON.stringify([view.effective_source, view.env_var, view.file_key_count, view.store?.state, view.store?.saved_at]);
    if (rec.provenance && rec.provenance !== provenance) updateTest(rec, IDLE);
    rec.provenance = provenance;
    if (view.effective_source === 'unavailable' || ['unavailable', 'unreadable'].includes(view.store?.state)) return setRow(rec, 'error', '凭据库异常');
    if (view.effective_source === 'none') return setRow(rec, 'absent', '未配置');
    const labels = { env: '环境变量生效', credential_store: '已配置', file: '文件 Key 生效' };
    setRow(rec, 'configured', labels[view.effective_source] || '状态未知');
  }
  function updateTest(rec, result) {
    if (disposed) return;
    rec.test = { ...result };
    rec.result.dataset.kind = result.kind;
    rec.result.querySelector('strong').textContent = ({ idle: '未测试', running: '正在测试', success: '连接成功', error: '测试失败' })[result.kind];
    rec.result.querySelector('small').textContent = result.kind === 'success' ? '本次连接已验证' : result.kind === 'error' ? result.title : rec.entry.cookie ? '使用本机 Cookie' : !rec.entry.keyed ? '无需 API Key' : '点击测试验证';
    rec.result.title = [result.title, result.message].filter(Boolean).join('\n');
    rec.testButton.disabled = result.kind === 'running';
    refreshStats();
  }
  function buildRow(entry) {
    const row = doc.createElement('article');
    row.className = 'source-row';
    row.dataset.expanded = 'false';
    row.setAttribute('data-source-row', entry.source);
    row.innerHTML = `<div class="source-line"><span class="source-icon icon-${entry.source}" aria-hidden="true">${MARKS[entry.source]}</span>
      <button type="button" class="source-pick" data-pick="${entry.source}" aria-expanded="false" aria-controls="detail-${entry.source}"><span class="source-name">${entry.label}</span><small class="source-desc">${DESCRIPTIONS[entry.source]}</small></button>
      <label class="source-toggle"><input type="checkbox" role="switch" data-toggle="${entry.source}" aria-label="启用 ${entry.label}" disabled><span class="toggle-track" aria-hidden="true"></span><span data-toggle-label>状态未知</span></label>
      <div class="source-key" data-key-summary aria-label="凭据摘要">—</div><span class="source-state" data-row-status data-kind="unknown">读取中</span>
      <div class="source-test-state" data-row-result data-kind="idle"><span class="test-state-symbol" aria-hidden="true"></span><div><strong>未测试</strong><small>${entry.cookie ? '需要 Cookie 文件' : entry.keyed ? '点击测试验证' : '无需 API Key'}</small></div></div>
      <button type="button" class="source-test-button" data-row-test aria-label="测试 ${entry.label}">${icon('play')}<span>测试</span></button><button type="button" class="source-expand" data-expand aria-label="展开 ${entry.label}" aria-expanded="false" aria-controls="detail-${entry.source}">${icon('chevron')}</button></div>
      <p class="row-error" data-row-error role="alert"></p><div id="detail-${entry.source}" class="source-detail" data-source-detail hidden></div>`;
    const rec = { entry, row, pick: row.querySelector('[data-pick]'), box: row.querySelector('[data-toggle]'), state: row.querySelector('[data-row-status]'), summary: row.querySelector('[data-key-summary]'), result: row.querySelector('[data-row-result]'), testButton: row.querySelector('[data-row-test]'), error: row.querySelector('[data-row-error]'), detail: row.querySelector('[data-source-detail]'), kind: entry.keyed || entry.cookie ? 'unknown' : 'keyless', test: { ...IDLE } };
    rows.set(entry.source, rec);
    list.append(row);
    if (!entry.keyed && !entry.cookie) setRow(rec, 'keyless', '无需凭据');
    rec.pick.addEventListener('click', () => { void toggleRow(entry.source); });
    row.querySelector('[data-expand]').addEventListener('click', () => { void toggleRow(entry.source); });
    rec.box.addEventListener('change', event => {
      const enabled = event.target.checked;
      for (const item of rows.values()) item.box.disabled = true;
      settingsQueue = settingsQueue.then(() => toggleEnabled(rec, enabled));
    });
    rec.testButton.addEventListener('click', async () => {
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
    if (!rec.entry.keyed) { detailMount = mountKeylessDetail(rec); return; }
    const body = doc.createElement('div');
    rec.detail.append(body);
    const previous = { ...rec.test };
    const previousProvenance = rec.provenance;
    const mounted = await mountCredentialBody(body, api, {
      source,
      onStatus: view => { if (!disposed && ticket === activeTicket) updateRow(rec, view); },
      onTest: result => { if (!disposed && ticket === activeTicket) updateTest(rec, result); },
    });
    if (disposed || ticket !== activeTicket) { mounted.dispose(); return; }
    // 凭据来源未变才恢复本页面内的上次结果，不持久化验证承诺。
    if (previousProvenance === rec.provenance && previous.kind !== 'running') {
      updateTest(rec, previous);
      body.querySelector('[data-status="test"]').textContent = previous.title;
      body.querySelector('[data-info="test"]').textContent = previous.message;
      body.querySelector('[data-test-result]').dataset.kind = previous.kind;
    }
    detailMount = mounted;
  }
  function mountKeylessDetail(rec) {
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
        const outcome = await api.credentialTest(rec.entry.source, null);
        show({ kind: outcome.result === 'success' ? 'success' : 'error', title: outcome.result === 'success' ? '测试成功' : '测试失败', message: outcome.message || outcome.result });
      } catch { show({ kind: 'error', title: '测试失败', message: '测试启动失败，请检查 CLI 后重试。' }); }
      finally { if (!stale && !disposed) button.disabled = false; }
    });
    return { dispose() { stale = true; } };
  }

  for (const entry of SOURCES) buildRow(entry);
  for (const button of root.querySelectorAll('[data-filter]')) button.addEventListener('click', () => {
    filter = button.dataset.filter;
    for (const other of root.querySelectorAll('[data-filter]')) other.setAttribute('aria-pressed', String(other === button));
    applyFilter();
  });
  search.addEventListener('input', applyFilter);
  const loads = SOURCES.filter(entry => entry.keyed).map(entry => api.credentialStatus(entry.source).then(view => updateRow(rows.get(entry.source), view), () => setRow(rows.get(entry.source), 'error', '状态读取失败')));
  try { applySettings(await api.settingsView()); }
  catch { root.querySelector('[data-list-error]').textContent = '无法读取搜索设置，开关状态未知。请重新进入本页重试。'; }
  await Promise.all(loads);
  await toggleRow(SOURCES[0].source);
  refreshStats();
  return { dispose() { disposed = true; activeTicket += 1; detailMount?.dispose(); doc.removeEventListener('keydown', onKey); root.classList.remove('sources-page'); } };
}
