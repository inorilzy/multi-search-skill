import { pageRoot, confirmInline, disposePage } from './dom.js';
import { showError } from './api.js';
// 搜索默认设置与可编辑路由分组。Rust SettingsView 是路由定义的唯一来源；
// 本页面不复制内置表，并始终保存完整草稿。

import { SOURCES } from './credentials.js';
import { ROUTES as CATALOG_ROUTES } from './catalog.js';

// 搜索源与路由的名字来自同一份生成目录（catalog.py），因此这里不再通过 IPC 另取一份清单。
export const SETTINGS_SOURCES = SOURCES.map(({ source, label }) => ({ source, label }));
export const ROUTES = CATALOG_ROUTES.map(({ name, label }) => ({ value: name, label }));
const SOURCE_LABELS = new Map(SETTINGS_SOURCES.map(entry => [entry.source, entry.label]));
const ID_PATTERN = /^[a-z0-9_-]{1,64}$/;

const cloneRoute = route => ({
  label: String(route.label),
  sources: [...route.sources],
  timeout: route.timeout == null ? null : Number(route.timeout),
});
const cloneRoutes = routes => new Map(Object.entries(routes || {}).map(([id, route]) => [id, cloneRoute(route)]));
// Object.fromEntries 即使遇到 "__proto__" 也会创建自有数据属性；直接给普通对象赋值会改写原型。
// 这样 Rust 收到的常规 JSON 对象能完整保留每个 ID。
const routesObject = routes => Object.fromEntries([...routes].map(([id, route]) => [id, cloneRoute(route)]));
const charLength = value => Array.from(value).length;

// core 的出厂 ranking 块；SettingsView 缺失字段时的兜底展示值。
const RANKING_FACTORY = { mode: 'rrf', base_url: '', model: '', candidate_limit: 50, batch_size: 20, rerank_timeout: 10 };
const RANKING_BOUNDS = {
  candidate_limit: [10, 200],
  batch_size: [1, 50],
  rerank_timeout: [1, 60],
};
const RANKING_FIELD_NAMES = { candidate_limit: '候选数', batch_size: '重排批量', rerank_timeout: '重排超时（秒）' };
const RERANK_KEY_SOURCE_LABELS = {
  env: '已由环境变量提供（优先于这里保存的密钥）',
  keys_file: '已保存',
  none: '未设置',
  unreadable: '密钥文件无法读取，请检查 ~/.search-keys.json',
};
// 与 core 的 _valid_base_url 同义：http(s)、有主机、无 ? 与 #。
const baseUrlError = value => {
  if (!value) return '';
  let url;
  try { url = new URL(value); } catch { return 'Base URL 必须是完整的 http(s) 地址，例如 http://127.0.0.1:3425/v1。'; }
  if (!['http:', 'https:'].includes(url.protocol) || !url.hostname) return 'Base URL 必须是 http(s) 地址。';
  if (value.includes('?') || value.includes('#')) return 'Base URL 不能带 ? 或 #。';
  return '';
};

const cloneRanking = ranking => ({
  mode: String(ranking?.mode ?? RANKING_FACTORY.mode),
  base_url: String(ranking?.base_url ?? RANKING_FACTORY.base_url),
  model: String(ranking?.model ?? RANKING_FACTORY.model),
  candidate_limit: Number(ranking?.candidate_limit ?? RANKING_FACTORY.candidate_limit),
  batch_size: Number(ranking?.batch_size ?? RANKING_FACTORY.batch_size),
  rerank_timeout: Number(ranking?.rerank_timeout ?? RANKING_FACTORY.rerank_timeout),
});

function validateRoute(id, route, routes, originalId = null) {
  if (!ID_PATTERN.test(id) || id === 'web') return '标识需为 1–64 个 ASCII 小写字母、数字、下划线或连字符，且不能使用 web。';
  if (id !== originalId && routes.has(id)) return '该路由标识已存在。';
  const label = route.label.trim();
  if (charLength(label) < 1 || charLength(label) > 80) return '名称需为 1–80 个字符。';
  if (!route.sources.length) return '请至少选择一个搜索源。';
  if (route.timeout != null && (!Number.isInteger(route.timeout) || route.timeout < 1 || route.timeout > 60)) return '独立超时需为 1–60 秒，留空则继承全局。';
  return '';
}

export async function mountSettings(root, api, { number = '05' } = {}) {
  root = pageRoot(root);
  const doc = root.ownerDocument;
  root.classList.add('settings-page');
  root.innerHTML = `<section class="heading settings-head"><div><p class="eyebrow">${number} / SETTINGS / ROUTES</p><h1 tabindex="-1">搜索设置</h1><p>配置默认分组、全局超时和每组搜索源。设置保存在本机 SQLite；搜索仍由独立 CLI 按需执行。</p></div><button type="button" data-action="refresh">刷新</button></section>
    <form data-settings-form>
      <section class="settings-summary" aria-label="当前搜索设置摘要">
        <article><span>当前默认路由</span><strong data-summary="route">—</strong><small data-summary="route-id">—</small></article>
        <article><span>实际超时</span><strong><b data-summary="effective-timeout">—</b> 秒</strong><small data-summary="timeout-kind">—</small></article>
        <article><span>实际搜索源</span><strong data-summary="active-count">—</strong><small data-summary="active">状态未知</small></article>
      </section>
      <p class="error-message settings-warning" data-info="active-warning" ></p>
      <p data-info="error" class="error-message" role="alert"></p><button type="button" data-action="retry" hidden>重试读取</button>

      <section class="panel settings-defaults"><div class="section-title"><div><p class="eyebrow">DEFAULTS</p><h2>默认路由与全局超时</h2></div><span class="draft-badge" data-dirty hidden>有未保存修改</span></div>
        <div class="settings-default-grid"><label>默认路由<select data-field="route" disabled></select></label><label>全局超时（秒）<input data-field="timeout" type="number" min="1" max="60" step="1" disabled></label></div>
      </section>

      <section class="panel route-panel"><div class="section-title"><div><p class="eyebrow">ROUTE GROUPS</p><h2>搜索分组</h2></div><div class="route-actions"><button type="button" data-action="new-route" disabled>新建分组</button><button type="button" data-action="restore" disabled>恢复内置五组</button></div></div>
        <p class="route-help">分组标识创建后不可修改。全局禁用的搜索源仍保留为分组成员，但执行时会跳过。</p>
        <div data-route-list class="route-list"></div><div data-restore-confirm></div>
      </section>

      <section class="panel ranking-panel"><div class="section-title"><div><p class="eyebrow">RANKING</p><h2>模型重排</h2></div></div>
        <label class="ranking-toggle"><input type="checkbox" data-field="ranking-enabled" disabled><span>启用模型重排<small>开启后会把你的搜索问题与结果摘要发送给第三方模型服务；关闭时完全不调用模型。</small></span></label>
        <p class="error-message" data-info="ranking-warning" role="alert"></p>
        <div class="ranking-advanced" data-ranking-advanced hidden>
          <p class="note">走 System One 协议：请求发往 <code>{Base URL}/systemone</code>。</p>
          <label>Base URL<input data-field="rerank-base-url" type="url" autocomplete="off" spellcheck="false" maxlength="2048" placeholder="http://127.0.0.1:3425/v1" disabled></label>
          <label>模型<input data-field="rerank-model" type="text" autocomplete="off" spellcheck="false" maxlength="200" placeholder="例如 group/jev" disabled></label>
          <div class="rerank-key">
            <label>API 密钥<input data-field="rerank-api-key" type="password" autocomplete="off" spellcheck="false" maxlength="4096" placeholder="粘贴 API 密钥" disabled></label>
            <div class="run-controls"><button type="button" data-action="rerank-key-save" disabled>保存密钥</button><button type="button" data-action="rerank-key-clear" disabled>清除密钥</button></div>
            <p class="note" data-status="rerank-key" role="status"></p>
          </div>
          <div class="settings-default-grid"><label>候选数<input data-field="candidate-limit" type="number" step="1" disabled></label><label>重排批量<input data-field="batch-size" type="number" step="1" disabled></label><label>重排超时（秒）<input data-field="rerank-timeout" type="number" step="1" disabled></label></div>
        </div>
      </section>

      <section class="panel settings-other"><div class="section-title"><div><p class="eyebrow">OTHER</p><h2>其他设置</h2></div></div>
        <label>Twitter Cookie 文件兼容路径（仅 file 模式读取明文）<input data-field="twitter" type="text" autocomplete="off" spellcheck="false" maxlength="1024" placeholder="例如 D:/secure/twitter-cookies.json" disabled></label>
        <details class="config-details"><summary>配置数据库信息</summary><dl class="cred-status"><dt>配置数据库</dt><dd class="status-text" data-status="path"></dd><dt>路径来源</dt><dd class="status-text" data-status="path-source"></dd></dl><p class="note" data-info="env" role="status"></p></details>
      </section>

      <div class="settings-savebar"><div><strong class="status-text" data-status="save" aria-live="polite"></strong><small class="status-text" data-status="draft">尚未读取设置</small></div><button type="submit" class="primary" data-action="save" disabled>保存全部设置</button></div>
    </form>
    <div data-refresh-confirm></div>`;

  const q = selector => root.querySelector(selector);
  const text = (selector, value) => { const node = q(selector); if (node) node.textContent = value; };
  let routes = new Map();
  let builtinRoutes = new Map();
  let selectedRoute = '';
  let globalTimeout = 60;
  let timeoutConfigured = true;
  let timeoutMin = 1;
  let timeoutMax = 90;
  // The timeout exactly as loaded: saving sends `timeout: null` unless the user changed it, so the
  // stored value (or its absence) is never silently rewritten.
  let loadedTimeout = '';
  let effectiveTimeouts = new Map();
  let disabledSources = new Set();
  let twitterPath = '';
  let rankingEnabled = false;
  let ranking = cloneRanking(null);
  let rankingInvalid = false;
  let rankingBounds = JSON.parse(JSON.stringify(RANKING_BOUNDS));
  let rerankKey = { source: 'none', keys_file: null, env_var: 'SYSTEMONE_API_KEY' };
  let keySaving = false;
  let loadedView = null;
  let dirty = false;
  let editorDirty = false;
  let revision = 0;
  let saving = false;
  let refreshing = false;
  let disposed = false;
  let editor = null;
  let refreshTicket = 0;

  function setEnabled(enabled) {
    for (const selector of ['[data-field="route"]', '[data-field="timeout"]', '[data-field="twitter"]', '[data-field="ranking-enabled"]', '[data-action="new-route"]', '[data-action="restore"]', '[data-action="save"]']) {
      const node = q(selector);
      if (node) node.disabled = !enabled || (selector === '[data-action="save"]' && saving);
    }
    for (const selector of ['[data-field="rerank-base-url"]', '[data-field="rerank-model"]', '[data-field="rerank-api-key"]', '[data-action="rerank-key-save"]', '[data-action="rerank-key-clear"]', '[data-field="candidate-limit"]', '[data-field="batch-size"]', '[data-field="rerank-timeout"]']) {
      const node = q(selector);
      if (node) node.disabled = !enabled || !rankingEnabled;
    }
  }

  function updateDraftIndicator(message) {
    q('[data-dirty]').hidden = !(dirty || editorDirty);
    text('[data-status="draft"]', message || (dirty ? '草稿尚未保存' : editorDirty ? '编辑器有未应用输入' : '当前显示已保存设置'));
    text('[data-status="save"]', '');
  }

  function setDirty(message = '草稿尚未保存') {
    dirty = true;
    revision += 1;
    updateDraftIndicator(message);
  }

  function markEditorDirty() {
    if (editorDirty) return;
    editorDirty = true;
    revision += 1;
    updateDraftIndicator('编辑器有未应用输入，请先应用或取消');
  }

  function sourceState(route) {
    const active = route ? route.sources.filter(source => !disabledSources.has(source)) : [];
    const savedPreview = !dirty && loadedView && effectiveTimeouts.has(selectedRoute);
    return { active, timeout: savedPreview ? effectiveTimeouts.get(selectedRoute) : route?.timeout ?? globalTimeout, savedPreview };
  }

  function renderSummary() {
    const route = routes.get(selectedRoute);
    const state = sourceState(route);
    text('[data-summary="route"]', route?.label || '—');
    text('[data-summary="route-id"]', route ? selectedRoute : '未选择');
    text('[data-summary="effective-timeout"]', route ? String(state.timeout) : '—');
    text('[data-summary="timeout-kind"]', route ? route.timeout != null ? '分组独立超时' : state.savedPreview && !timeoutConfigured ? '当前 CLI 内置值；保存后使用全局设置' : `继承全局 ${globalTimeout} 秒` : '状态未知');
    text('[data-summary="active-count"]', route ? `${state.active.length} / ${route.sources.length}` : '—');
    text('[data-summary="active"]', route ? state.active.map(source => SOURCE_LABELS.get(source) || source).join('、') || '无可执行搜索源' : '状态未知');
    text('[data-info="active-warning"]', route && state.active.length === 0 ? '当前分组的所有成员都被全局禁用，搜索不会运行。请到“搜索源”页启用至少一个。' : '');
  }

  function renderRouteSelect() {
    const select = q('[data-field="route"]');
    select.replaceChildren();
    for (const [id, route] of routes) {
      const option = doc.createElement('option');
      option.value = id;
      option.textContent = `${route.label} / ${id}`;
      option.selected = id === selectedRoute;
      select.append(option);
    }
  }

  // 一张分组卡只展示前几个搜索源，其余折叠成 +N：列表高度稳定，鼠标悬停仍能看到全部成员。
  const CHIP_LIMIT = 8;

  function chip(source) {
    const node = doc.createElement('span');
    node.className = 'route-chip';
    node.textContent = SOURCE_LABELS.get(source) || source;
    if (disabledSources.has(source)) {
      node.classList.add('is-disabled');
      node.title = '已在搜索源页全局禁用；分组成员资格仍保留';
      const note = doc.createElement('small');
      note.textContent = '全局停用';
      node.append(note);
    }
    return node;
  }

  function renderChips(container, sources) {
    for (const source of sources.slice(0, CHIP_LIMIT)) container.append(chip(source));
    const folded = sources.slice(CHIP_LIMIT);
    if (!folded.length) return;
    const more = doc.createElement('span');
    more.className = 'route-chip route-chip-more';
    more.textContent = `+${folded.length}`;
    more.title = `另有 ${folded.map(source => SOURCE_LABELS.get(source) || source).join('、')}`;
    container.append(more);
  }

  // 编辑器就地插入被编辑的卡片下方；列表重建时把同一个面板节点搬回去，输入内容不会丢。
  function mountEditor(panel) {
    const list = q('[data-route-list]');
    if (editor?.routeId) {
      const target = [...list.querySelectorAll('[data-route-row]')].find(node => node.getAttribute('data-route-row') === editor.routeId);
      if (target) { target.after(panel); return; }
    }
    list.prepend(panel);
  }

  function closeEditor(quiet = false) {
    editor?.panel.remove();
    editor = null;
    editorDirty = false;
    if (!quiet) updateDraftIndicator();
  }

  function requestEditorAction(action) {
    if (!editor || !editorDirty) { action(); return; }
    const panel = editor.panel;
    if (panel.querySelector('[data-editor-discard]')) return;
    const confirm = doc.createElement('div');
    confirm.className = 'inline-confirm';
    confirm.setAttribute('data-editor-discard', '');
    confirm.innerHTML = '<p>当前编辑器有尚未应用的输入。丢弃后才能继续。</p><div class="run-controls"><button type="button" class="danger" data-action="discard-editor">丢弃输入</button><button type="button" data-action="keep-editor">继续编辑</button></div>';
    panel.append(confirm);
    confirm.querySelector('[data-action="keep-editor"]').addEventListener('click', () => confirm.remove());
    confirm.querySelector('[data-action="discard-editor"]').addEventListener('click', () => { closeEditor(); action(); });
  }

  function requestOpenEditor(mode, routeId = null) {
    requestEditorAction(() => { if (editor) closeEditor(true); openEditor(mode, routeId); });
  }

  function openEditor(mode, routeId = null) {
    const source = routeId == null ? null : routes.get(routeId);
    const copy = mode === 'copy';
    const editing = mode === 'edit';
    const initial = source ? cloneRoute(source) : { label: '', sources: [], timeout: null };
    editorDirty = false;
    const panel = doc.createElement('section');
    panel.className = 'route-editor';
    panel.dataset.mode = mode;
    panel.innerHTML = `<div class="route-editor-head"><div><p class="eyebrow">${editing ? 'EDIT' : copy ? 'COPY' : 'NEW'}</p><h3>${editing ? '编辑分组' : copy ? '复制为新分组' : '新建分组'}</h3></div></div>
      <div class="route-editor-grid"><label>标识<input data-edit="id" maxlength="64" spellcheck="false" autocomplete="off"><small data-edit-id-hint></small></label><label>名称<input data-edit="label" maxlength="80"></label><label>独立超时（秒）<input data-edit="timeout" type="number" min="1" max="60" step="1"><small>留空继承全局 ${globalTimeout} 秒</small></label></div>
      <fieldset class="route-sources"><legend class="visually-hidden">搜索源（至少一个）</legend><div class="route-sources-head"><span class="route-sources-label">搜索源（至少一个）</span><span class="route-sources-count" data-source-count aria-live="polite"></span><div class="route-source-tools"><button type="button" data-source-action="all">全选</button><button type="button" data-source-action="none">全不选</button><button type="button" data-source-action="invert">反选</button></div></div><div class="route-source-grid" data-edit="sources"></div></fieldset>
      <p class="error-message route-form-error" data-edit-error ></p>
      <div class="route-editor-foot"><small>应用后仍需点击“保存全部设置”写入配置。</small><div class="run-controls"><button type="button" data-action="close-editor">取消</button><button type="button" class="primary" data-action="apply-route">应用到草稿</button></div></div>`;
    const idField = panel.querySelector('[data-edit="id"]');
    idField.value = editing ? routeId : '';
    idField.readOnly = editing;
    idField.title = editing ? '标识创建后不可修改' : '';
    panel.querySelector('[data-edit-id-hint]').textContent = editing
      ? '创建后不可修改'
      : '小写字母、数字、下划线或连字符';
    panel.querySelector('[data-edit="label"]').value = copy ? `${initial.label} 副本` : initial.label;
    panel.querySelector('[data-edit="timeout"]').value = initial.timeout == null ? '' : String(initial.timeout);
    const sourceGrid = panel.querySelector('[data-edit="sources"]');
    for (const entry of SETTINGS_SOURCES) {
      const label = doc.createElement('label');
      label.className = 'route-source-option';
      if (disabledSources.has(entry.source)) label.classList.add('is-disabled');
      const box = doc.createElement('input');
      box.type = 'checkbox';
      box.value = entry.source;
      box.checked = initial.sources.includes(entry.source);
      box.setAttribute('data-route-source', entry.source);
      const name = doc.createElement('span');
      name.textContent = entry.label;
      label.append(box, name);
      if (disabledSources.has(entry.source)) {
        const note = doc.createElement('small');
        note.textContent = '全局停用';
        note.title = '已在搜索源页全局禁用；分组成员资格仍保留，执行时跳过';
        label.append(note);
      }
      sourceGrid.append(label);
    }
    const count = panel.querySelector('[data-source-count]');
    const sourceBoxes = () => [...panel.querySelectorAll('[data-route-source]')];
    const syncSourcePicker = () => {
      const boxes = sourceBoxes();
      const checked = boxes.filter(box => box.checked).length;
      count.textContent = `已选 ${checked} / ${boxes.length}`;
      panel.querySelector('[data-source-action="all"]').disabled = checked === boxes.length;
      panel.querySelector('[data-source-action="none"]').disabled = checked === 0;
    };
    for (const tool of panel.querySelectorAll('[data-source-action]')) {
      tool.addEventListener('click', () => {
        const select = tool.dataset.sourceAction;
        for (const box of sourceBoxes()) box.checked = select === 'all' ? true : select === 'none' ? false : !box.checked;
        markEditorDirty();
        syncSourcePicker();
      });
    }
    for (const box of sourceBoxes()) box.addEventListener('change', syncSourcePicker);
    syncSourcePicker();
    panel.querySelector('[data-action="close-editor"]').addEventListener('click', () => requestEditorAction(() => closeEditor()));
    for (const field of panel.querySelectorAll('input')) {
      field.addEventListener(field.type === 'checkbox' ? 'change' : 'input', markEditorDirty);
    }
    panel.querySelector('[data-action="apply-route"]').addEventListener('click', () => {
      const id = idField.value.trim();
      const timeoutText = panel.querySelector('[data-edit="timeout"]').value.trim();
      const candidate = {
        label: panel.querySelector('[data-edit="label"]').value.trim(),
        sources: [...panel.querySelectorAll('[data-route-source]:checked')].map(box => box.value),
        timeout: timeoutText === '' ? null : Number(timeoutText),
      };
      const error = validateRoute(id, candidate, routes, editing ? routeId : null);
      panel.querySelector('[data-edit-error]').textContent = error;
      if (error) return;
      routes.set(id, candidate);
      if (!selectedRoute) selectedRoute = id;
      editorDirty = false;
      setDirty(`${editing ? '分组修改' : '新分组'}已应用到草稿，尚未保存`);
      closeEditor(true);
      renderAll();
    });
    editor = { mode, routeId, panel };
    mountEditor(panel);
    const focusTarget = panel.querySelector(editing ? '[data-edit="label"]' : '[data-edit="id"]');
    // 聚焦不能顺手把页面滚走：只有编辑器完全不在视野里时才主动滚动。
    focusTarget?.focus({ preventScroll: true });
    const rect = typeof panel.getBoundingClientRect === 'function' ? panel.getBoundingClientRect() : null;
    const viewport = panel.ownerDocument.defaultView?.innerHeight ?? 0;
    if (rect && viewport && (rect.top < 0 || rect.top > viewport - 160)) panel.scrollIntoView?.({ block: 'start' });
  }

  function openDelete(row, id) {
    row.querySelector('[data-inline-confirm]')?.remove();
    const confirm = doc.createElement('div');
    confirm.className = 'inline-confirm';
    confirm.setAttribute('data-inline-confirm', 'delete');
    const message = doc.createElement('p');
    message.textContent = `删除“${routes.get(id).label}”后，仍需保存全部设置才会写入配置。`;
    const actions = doc.createElement('div');
    actions.className = 'run-controls';
    const yes = doc.createElement('button');
    yes.type = 'button'; yes.className = 'danger'; yes.textContent = '确认删除'; yes.setAttribute('data-action', 'confirm-delete');
    const no = doc.createElement('button');
    no.type = 'button'; no.textContent = '取消'; no.setAttribute('data-action', 'cancel-delete');
    actions.append(yes, no); confirm.append(message, actions); row.append(confirm);
    no.addEventListener('click', () => confirm.remove());
    yes.addEventListener('click', () => {
      routes.delete(id);
      if (editor?.routeId === id) closeEditor();
      setDirty('分组删除已应用到草稿，尚未保存');
      renderAll();
    });
  }

  function renderRoutes() {
    const list = q('[data-route-list]');
    list.replaceChildren();
    for (const [id, route] of routes) {
      const row = doc.createElement('article');
      row.className = 'route-row';
      row.setAttribute('data-route-row', id);
      if (id === selectedRoute) row.classList.add('is-current');
      const body = doc.createElement('div');
      body.className = 'route-main';
      const title = doc.createElement('div');
      title.className = 'route-title';
      const heading = doc.createElement('strong'); heading.textContent = route.label;
      const code = doc.createElement('code'); code.textContent = id;
      title.append(heading, code);
      if (id === selectedRoute) { const current = doc.createElement('span'); current.textContent = '当前默认'; current.className = 'current-badge'; title.append(current); }
      const meta = doc.createElement('span');
      meta.className = 'route-timeout';
      const timeoutText = route.timeout != null
        ? `独立超时 · ${route.timeout} 秒`
        : !dirty && !timeoutConfigured && effectiveTimeouts.has(id)
          ? `当前配置 · ${effectiveTimeouts.get(id)} 秒（未显式全局值）`
          : `继承全局 · ${globalTimeout} 秒`;
      meta.textContent = `${timeoutText} · 共 ${route.sources.length} 个搜索源`;
      const chips = doc.createElement('div'); chips.className = 'route-chips';
      renderChips(chips, route.sources);
      body.append(title, meta, chips);
      const actions = doc.createElement('div'); actions.className = 'route-row-actions';
      const edit = doc.createElement('button'); edit.type = 'button'; edit.textContent = '编辑'; edit.addEventListener('click', () => requestOpenEditor('edit', id));
      const copy = doc.createElement('button'); copy.type = 'button'; copy.textContent = '复制'; copy.addEventListener('click', () => requestOpenEditor('copy', id));
      const remove = doc.createElement('button'); remove.type = 'button'; remove.textContent = '删除';
      const blocked = id === selectedRoute || routes.size === 1;
      remove.disabled = blocked;
      // 禁用的按钮不接收鼠标事件，悬停提示挂在外层，原因仍然看得到。
      const reason = id === selectedRoute ? '正在使用：请先在上方切换默认分组' : routes.size === 1 ? '至少保留一个分组' : '';
      remove.title = reason;
      remove.addEventListener('click', () => requestEditorAction(() => openDelete(row, id)));
      if (blocked) {
        const host = doc.createElement('span');
        host.className = 'route-remove-blocked';
        host.title = reason;
        host.append(remove);
        actions.append(edit, copy, host);
      } else {
        actions.append(edit, copy, remove);
      }
      row.append(body, actions);
      list.append(row);
    }
    if (editor) mountEditor(editor.panel);
  }

  function renderRerankKey() {
    const path = rerankKey.keys_file || '~/.search-keys.json';
    const label = RERANK_KEY_SOURCE_LABELS[rerankKey.source] ?? rerankKey.source;
    text('[data-status="rerank-key"]', `密钥状态：${label}。保存在 ${path}（仅你本人可读），不写入设置；环境变量 ${rerankKey.env_var} 优先。`);
  }

  function renderRanking() {
    const toggle = q('[data-field="ranking-enabled"]');
    toggle.checked = rankingEnabled;
    q('[data-ranking-advanced]').hidden = !rankingEnabled;
    const off = toggle.disabled || !rankingEnabled;
    for (const [key, selector] of [['base_url', '[data-field="rerank-base-url"]'], ['model', '[data-field="rerank-model"]']]) {
      const node = q(selector);
      node.value = ranking[key];
      node.disabled = off;
    }
    q('[data-field="rerank-api-key"]').disabled = off || keySaving;
    q('[data-action="rerank-key-save"]').disabled = off || keySaving;
    q('[data-action="rerank-key-clear"]').disabled = off || keySaving || rerankKey.source !== 'keys_file';
    const fields = { candidate_limit: '[data-field="candidate-limit"]', batch_size: '[data-field="batch-size"]', rerank_timeout: '[data-field="rerank-timeout"]' };
    for (const [key, selector] of Object.entries(fields)) {
      const node = q(selector);
      const [min, max] = rankingBounds[key];
      node.min = String(min);
      node.max = String(max);
      node.value = String(ranking[key]);
      node.disabled = off;
    }
    renderRerankKey();
    const boundsText = Object.entries(fields).map(([key]) => `${RANKING_FIELD_NAMES[key]} ${rankingBounds[key][0]}–${rankingBounds[key][1]}`).join('，');
    text('[data-info="ranking-warning"]', rankingInvalid ? `已保存的重排配置非法（开启时需要 Base URL 与模型名；${boundsText}），当前显示默认值；重新保存可修复。` : '');
  }

  // null = 合法；否则返回中文错误。关闭时只有「已保存值非法」本身会阻止保存。
  function rankingError() {
    ranking.base_url = q('[data-field="rerank-base-url"]').value.trim().replace(/\/+$/, '');
    ranking.model = q('[data-field="rerank-model"]').value.trim();
    if (!rankingEnabled) return rankingInvalid ? '已保存的重排配置非法，请先开启模型重排并修正后再保存。' : null;
    if (!ranking.base_url) return '开启模型重排需要填写 Base URL。';
    const urlProblem = baseUrlError(ranking.base_url);
    if (urlProblem) return urlProblem;
    if (!ranking.model) return '开启模型重排需要填写模型名。';
    const fields = { candidate_limit: '[data-field="candidate-limit"]', batch_size: '[data-field="batch-size"]', rerank_timeout: '[data-field="rerank-timeout"]' };
    for (const [key, selector] of Object.entries(fields)) {
      const raw = q(selector).value.trim();
      const value = Number(raw);
      const [min, max] = rankingBounds[key];
      if (!raw || !Number.isInteger(value) || value < min || value > max) {
        return `${RANKING_FIELD_NAMES[key]}必须是 ${min} 到 ${max} 之间的整数。`;
      }
      ranking[key] = value;
    }
    return null;
  }

  // 密钥单独保存：直接写进 ~/.search-keys.json，不随设置草稿提交，也从不回显。
  async function saveRerankKey(clear) {
    if (keySaving) return;
    const field = q('[data-field="rerank-api-key"]');
    const key = clear ? '' : field.value.trim();
    if (!clear && !key) { text('[data-info="error"]', '请先粘贴 API 密钥。'); return; }
    keySaving = true;
    renderRanking();
    text('[data-info="error"]', '');
    try {
      const view = await api.rerankKeySave(key);
      if (disposed) return;
      field.value = '';
      rerankKey = view.rerank_key ?? rerankKey;
      text('[data-status="save"]', clear ? '密钥已清除。' : '密钥已保存。');
    } catch (error) {
      if (!disposed) showError(q('[data-info="error"]'), error, '重排 API 密钥保存失败，原密钥文件未改变。');
    } finally {
      keySaving = false;
      if (!disposed) renderRanking();
    }
  }

  function renderAll() {
    renderRouteSelect();
    q('[data-field="route"]').value = selectedRoute;
    renderRoutes();
    renderSummary();
    renderRanking();
  }

  function openRestoreConfirm() {
    const holder = q('[data-restore-confirm]');
    holder.replaceChildren();
    const panel = doc.createElement('div');
    panel.className = 'inline-confirm restore-confirm';
    panel.innerHTML = '<p>恢复会把五个内置标识重置为工厂名称、搜索源和继承超时；其他自定义分组不会改变。</p><div class="run-controls"><button type="button" class="primary" data-action="confirm-restore">确认恢复</button><button type="button" data-action="cancel-restore">取消</button></div>';
    holder.append(panel);
    panel.querySelector('[data-action="cancel-restore"]').addEventListener('click', () => holder.replaceChildren());
    panel.querySelector('[data-action="confirm-restore"]').addEventListener('click', () => {
      for (const [id, route] of builtinRoutes) routes.set(id, cloneRoute(route));
      if (!routes.has(selectedRoute)) selectedRoute = routes.keys().next().value || '';
      holder.replaceChildren();
      setDirty('内置五组已恢复到草稿，自定义分组保持不变');
      renderAll();
    });
  }

  function fill(view) {
    q('[data-action="retry"]').hidden = true;
    loadedView = view;
    routes = cloneRoutes(view.routes);
    builtinRoutes = cloneRoutes(view.builtin_routes);
    selectedRoute = String(view.route || '');
    globalTimeout = Number(view.timeout ?? 60);
    timeoutConfigured = view.timeout_configured !== false;
    timeoutMin = Number(view.timeout_min ?? 1);
    timeoutMax = Number(view.timeout_max ?? 90);
    effectiveTimeouts = new Map(Object.entries(view.effective_timeouts || { [view.route]: view.effective_timeout }));
    disabledSources = new Set(view.disabled_sources || []);
    twitterPath = view.twitter_cookies_path || '';
    ranking = cloneRanking(view.ranking);
    rankingEnabled = ranking.mode === 'rrf_model';
    rankingInvalid = view.ranking_invalid === true;
    rerankKey = view.rerank_key ?? { source: 'none', keys_file: null, env_var: 'SYSTEMONE_API_KEY' };
    rankingBounds = {
      candidate_limit: [Number(view.ranking_candidate_limit_min ?? RANKING_BOUNDS.candidate_limit[0]), Number(view.ranking_candidate_limit_max ?? RANKING_BOUNDS.candidate_limit[1])],
      batch_size: [Number(view.ranking_batch_size_min ?? RANKING_BOUNDS.batch_size[0]), Number(view.ranking_batch_size_max ?? RANKING_BOUNDS.batch_size[1])],
      rerank_timeout: [Number(view.ranking_rerank_timeout_min ?? RANKING_BOUNDS.rerank_timeout[0]), Number(view.ranking_rerank_timeout_max ?? RANKING_BOUNDS.rerank_timeout[1])],
    };
    const timeoutField = q('[data-field="timeout"]');
    timeoutField.min = String(timeoutMin);
    timeoutField.max = String(timeoutMax);
    timeoutField.value = String(globalTimeout);
    loadedTimeout = timeoutField.value;
    q('[data-field="twitter"]').value = twitterPath;
    text('[data-status="path"]', view.config_path || '无法确定配置文件位置');
    text('[data-status="path-source"]', view.path_source === 'env' ? `隔离数据库 MULTI_SEARCH_CONFIG_DB（${view.file_present ? '已存在' : '尚未创建'}）` : `用户 SQLite 配置（${view.file_present ? '已存在' : '尚未创建'}）`);
    const notes = ['SQLite 是唯一生效配置来源；旧 JSON、环境变量和旧凭据文件不会自动生效。'];
    if (view.timeout_configured === false) notes.push('配置中没有显式的全局超时，当前显示的是 CLI 内置值；不修改则保存时不会写入。');
    if (view.timeout_out_of_range) notes.push(`已保存的超时 ${view.timeout} 秒超出 ${timeoutMin} 到 ${timeoutMax} 秒；不修改则原样保留。`);
    if (view.unknown_disabled_sources?.length) notes.push(`配置中还有无法识别的禁用项（${view.unknown_disabled_sources.join('、')}），保存时会原样保留。`);
    if (rankingInvalid) notes.push('已保存的模型重排配置非法，当前按默认值显示；请修正后重新保存。');
    text('[data-info="env"]', notes.join(' '));
    dirty = false;
    editorDirty = false;
    revision += 1;
    q('[data-dirty]').hidden = true;
    text('[data-status="draft"]', view.status === 'config_unreadable' ? '配置不可读，保存已禁用' : '当前显示已保存设置');
    text('[data-status="save"]', '');
    text('[data-info="error"]', view.status === 'config_unreadable' ? view.message || '现有配置无法读取，保存已被阻止。' : '');
    closeEditor(true);
    renderAll();
    setEnabled(view.status !== 'config_unreadable' && routes.size > 0 && routes.has(selectedRoute));
  }

  function validateDraft() {
    if (!routes.size) return '至少需要一个搜索分组。';
    if (!routes.has(selectedRoute)) return '请选择存在的默认路由。';
    // An untouched stored timeout is sent as null and kept verbatim, even when it is out of range;
    // only a value the user typed is checked against the backend bounds.
    const timeoutEdited = q('[data-field="timeout"]').value.trim() !== loadedTimeout;
    if (timeoutEdited && (!Number.isInteger(globalTimeout) || globalTimeout < timeoutMin || globalTimeout > timeoutMax)) {
      return `全局超时需为 ${timeoutMin} 到 ${timeoutMax} 秒之间的整数。`;
    }
    for (const [id, route] of routes) {
      const error = validateRoute(id, route, new Map([...routes].filter(([other]) => other !== id)), id);
      if (error) return `${route.label || id}：${error}`;
    }
    const rankingProblem = rankingError();
    if (rankingProblem) return rankingProblem;
    return '';
  }

  function draftPayload() {
    const rawTimeout = q('[data-field="timeout"]').value.trim();
    // `null` keeps the stored timeout (including "no explicit value") untouched.
    let timeout = null;
    if (rawTimeout !== loadedTimeout) {
      const value = Number(rawTimeout);
      if (!rawTimeout || !Number.isInteger(value) || value < timeoutMin || value > timeoutMax) {
        throw new Error(`全局超时必须是 ${timeoutMin} 到 ${timeoutMax} 秒之间的整数。`);
      }
      globalTimeout = value;
      timeout = value;
    }
    twitterPath = q('[data-field="twitter"]').value;
    const error = validateDraft();
    if (error) throw new Error(error);
    return {
      route: selectedRoute,
      timeout,
      disabled_sources: [...disabledSources],
      routes: routesObject(routes),
      twitter_cookies_path: twitterPath,
      // 关闭时提交 rrf 块（保留已填的端点与数值草稿），core 完全不调用模型。密钥不在这里。
      ranking: { mode: rankingEnabled ? 'rrf_model' : 'rrf', base_url: ranking.base_url, model: ranking.model, candidate_limit: ranking.candidate_limit, batch_size: ranking.batch_size, rerank_timeout: ranking.rerank_timeout },
    };
  }

  async function saveDraft() {
    if (saving || !loadedView || loadedView.status === 'config_unreadable') return;
    if (refreshing) { text('[data-info="error"]', '正在刷新设置，请稍后再保存。'); return; }
    if (editorDirty) { text('[data-info="error"]', '分组编辑器还有未应用输入，请先“应用到草稿”或取消编辑。'); return; }
    let payload;
    try { payload = draftPayload(); }
    catch (error) { text('[data-info="error"]', error.message); return; }
    saving = true;
    const savedRevision = revision;
    q('[data-action="save"]').disabled = true;
    q('[data-action="refresh"]').disabled = true;
    text('[data-status="save"]', '保存中…');
    text('[data-info="error"]', '');
    try {
      const saved = await api.settingsSave(payload);
      if (disposed) return;
      if (revision === savedRevision) {
        fill(saved);
        text('[data-status="save"]', '已保存。');
      } else {
        loadedView = saved;
        text('[data-status="save"]', '先前草稿已保存。');
        text('[data-status="draft"]', '保存期间又有修改，当前草稿仍未保存');
      }
    } catch (error) {
      if (!disposed) {
        text('[data-status="save"]', '');
        showError(q('[data-info="error"]'), error, '保存失败，原配置未改变。');
      }
    } finally {
      saving = false;
      if (!disposed) {
        q('[data-action="save"]').disabled = loadedView?.status === 'config_unreadable';
        q('[data-action="refresh"]').disabled = false;
      }
    }
  }

  async function refresh(force = false) {
    if (saving) { text('[data-info="error"]', '正在保存设置，完成后再刷新。'); return; }
    if (refreshing) return;
    if ((dirty || editorDirty) && !force) {
      const holder = q('[data-refresh-confirm]');
      if (holder.firstChild) return;
      const panel = doc.createElement('div');
      panel.className = 'refresh-confirm';
      panel.innerHTML = '<p>刷新会丢弃未保存草稿。确定继续吗？</p><div class="run-controls"><button type="button" class="danger" data-action="confirm-refresh">丢弃并刷新</button><button type="button" data-action="cancel-refresh">取消</button></div>';
      holder.append(panel);
      panel.querySelector('[data-action="cancel-refresh"]').addEventListener('click', () => holder.replaceChildren());
      panel.querySelector('[data-action="confirm-refresh"]').addEventListener('click', () => { holder.replaceChildren(); void refresh(true); });
      // Wired synchronously so focus moves to the safe choice the moment the panel opens.
      const release = confirmInline(panel, () => { holder.replaceChildren(); release(); });
      panel.querySelector('[data-action="cancel-refresh"]').addEventListener('click', release);
      return;
    }
    const ticket = ++refreshTicket;
    const startedRevision = revision;
    refreshing = true;
    q('[data-action="refresh"]').disabled = true;
    q('[data-action="save"]').disabled = true;
    try {
      const view = await api.settingsView();
      if (!disposed && ticket === refreshTicket && revision === startedRevision) fill(view);
      else if (!disposed && ticket === refreshTicket) text('[data-info="error"]', '刷新期间草稿发生变化，刷新结果未应用。');
    } catch (error) {
      if (!disposed && ticket === refreshTicket) {
        if (loadedView) {
          showError(q('[data-info="error"]'), error, '刷新失败，当前草稿和已加载设置保持不变，请重试。');
        } else {
          routes = new Map();
          effectiveTimeouts = new Map();
          setEnabled(false);
          showError(q('[data-info="error"]'), error, '无法读取搜索设置，保存已暂停。');
          // Error boundary: a failed first read offers an explicit retry next to its reason.
          q('[data-action="retry"]').hidden = false;
          text('[data-status="draft"]', '设置状态未知');
          renderAll();
        }
      }
    } finally {
      if (!disposed && ticket === refreshTicket) {
        refreshing = false;
        q('[data-action="refresh"]').disabled = false;
        q('[data-action="save"]').disabled = !loadedView || loadedView.status === 'config_unreadable';
      }
    }
  }

  q('[data-field="route"]').addEventListener('change', event => {
    selectedRoute = event.target.value;
    setDirty('默认路由已在草稿中切换');
    renderRoutes();
    renderSummary();
  });
  q('[data-field="timeout"]').addEventListener('input', event => {
    globalTimeout = Number(event.target.value);
    setDirty();
    renderRoutes();
    renderSummary();
  });
  q('[data-field="twitter"]').addEventListener('input', event => { twitterPath = event.target.value; setDirty(); });
  q('[data-field="ranking-enabled"]').addEventListener('change', event => {
    rankingEnabled = event.target.checked;
    ranking.mode = rankingEnabled ? 'rrf_model' : 'rrf';
    setDirty();
    renderRanking();
  });
  q('[data-field="rerank-base-url"]').addEventListener('input', event => { ranking.base_url = event.target.value; setDirty(); });
  q('[data-field="rerank-model"]').addEventListener('input', event => { ranking.model = event.target.value; setDirty(); });
  q('[data-action="rerank-key-save"]').addEventListener('click', () => { void saveRerankKey(false); });
  q('[data-action="rerank-key-clear"]').addEventListener('click', () => { void saveRerankKey(true); });
  for (const [key, selector] of Object.entries({ candidate_limit: '[data-field="candidate-limit"]', batch_size: '[data-field="batch-size"]', rerank_timeout: '[data-field="rerank-timeout"]' })) {
    q(selector).addEventListener('input', event => { ranking[key] = Number(event.target.value); setDirty(); });
  }
  q('[data-action="new-route"]').addEventListener('click', () => requestOpenEditor('new'));
  q('[data-action="restore"]').addEventListener('click', openRestoreConfirm);
  q('[data-action="refresh"]').addEventListener('click', () => { void refresh(); });
  q('[data-action="retry"]').addEventListener('click', () => { void refresh(true); });
  q('[data-settings-form]').addEventListener('submit', event => { event.preventDefault(); void saveDraft(); });

  await refresh(true);
  return {
    dispose() { disposePage(root); disposed = true; refreshTicket += 1; root.classList.remove('settings-page'); },
    get saved() { return loadedView; },
    get dirty() { return dirty; },
  };
}
