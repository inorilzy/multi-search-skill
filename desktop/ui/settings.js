// 搜索默认设置与可编辑路由分组。Rust SettingsView 是路由定义的唯一来源；
// 本页面不复制内置表，并始终保存完整草稿。

import { initProviders, providerList } from './credentials.js';

// Provider catalog is resolved at mount time. SETTINGS_SOURCES is filled in by
// `mountSettings` after `initProviders(api)` resolves, then remains stable for
// the life of the page. Never mutate it.
export let SETTINGS_SOURCES = [];
let SOURCE_LABELS = new Map();
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

function validateRoute(id, route, routes, originalId = null) {
  if (!ID_PATTERN.test(id) || id === 'web') return '标识需为 1–64 个 ASCII 小写字母、数字、下划线或连字符，且不能使用 web。';
  if (id !== originalId && routes.has(id)) return '该路由标识已存在。';
  const label = route.label.trim();
  if (charLength(label) < 1 || charLength(label) > 80) return '名称需为 1–80 个字符。';
  if (!route.sources.length) return '请至少选择一个搜索源。';
  if (route.timeout != null && (!Number.isInteger(route.timeout) || route.timeout < 1 || route.timeout > 60)) return '独立超时需为 1–60 秒，留空则继承全局。';
  return '';
}

export async function mountSettings(root, api) {
  const doc = root.ownerDocument;
  root.classList.add('settings-page');
  // Provider manifest drives the source pickers; fail closed if it cannot load
  // so an empty list never looks like a saved configuration.
  try {
    const rows = await initProviders(api);
    SETTINGS_SOURCES = rows.map(({ source, label }) => ({ source, label }));
    SOURCE_LABELS = new Map(SETTINGS_SOURCES.map(entry => [entry.source, entry.label]));
  } catch (error) {
    root.innerHTML = `<section class="heading"><p class="eyebrow">SETTINGS</p><h1>搜索设置</h1><p>无法读取搜索源清单：${typeof error === 'string' ? error : '请重试或重启桌面应用。'}</p></section>`;
    return { dispose() { root.classList.remove('settings-page'); } };
  }
  root.innerHTML = `<section class="heading settings-head"><div><p class="eyebrow">SETTINGS / ROUTES</p><h1>搜索设置</h1><p>配置默认分组、全局超时和每组搜索源。设置保存在 SQLite；搜索仍由独立 CLI 按需执行。</p></div><button type="button" data-action="refresh">刷新</button></section>
    <form data-settings-form>
      <section class="settings-summary" aria-label="当前搜索设置摘要">
        <article><span>当前默认路由</span><strong data-summary="route">—</strong><small data-summary="route-id">—</small></article>
        <article><span>实际超时</span><strong><b data-summary="effective-timeout">—</b> 秒</strong><small data-summary="timeout-kind">—</small></article>
        <article><span>实际搜索源</span><strong data-summary="active-count">—</strong><small data-summary="active">状态未知</small></article>
      </section>
      <p class="settings-warning" data-info="active-warning" role="alert"></p>
      <p data-info="error" role="alert"></p>

      <section class="panel settings-defaults"><div class="section-title"><div><p class="eyebrow">DEFAULTS</p><h2>默认路由与全局超时</h2></div><span class="draft-badge" data-dirty hidden>有未保存修改</span></div>
        <div class="settings-default-grid"><label>默认路由<select data-field="route" disabled></select></label><label>全局超时（秒）<input data-field="timeout" type="number" min="1" max="60" step="1" disabled></label></div>
      </section>

      <section class="panel route-panel"><div class="section-title"><div><p class="eyebrow">ROUTE GROUPS</p><h2>搜索分组</h2></div><div class="route-actions"><button type="button" data-action="new-route" disabled>新建分组</button><button type="button" data-action="restore" disabled>恢复内置五组</button></div></div>
        <p class="route-help">分组标识创建后不可修改。全局禁用的搜索源仍保留为分组成员，但执行时会跳过。</p>
        <div data-route-list class="route-list"></div><div data-route-editor></div><div data-restore-confirm></div>
      </section>

      <section class="panel settings-other"><div class="section-title"><div><p class="eyebrow">OTHER</p><h2>其他设置</h2></div></div>
        <label>Twitter cookie 文件路径（可选，仅保存路径）<input data-field="twitter" type="text" autocomplete="off" spellcheck="false" maxlength="1024" placeholder="例如 D:/secure/twitter-cookies.json" disabled></label>
        <details class="config-details"><summary>配置数据库信息</summary><dl class="cred-status"><dt>配置数据库</dt><dd data-status="path"></dd><dt>路径来源</dt><dd data-status="path-source"></dd></dl><p class="note" data-info="env" role="status"></p></details>
      </section>

      <div class="settings-savebar"><div><strong data-status="save" aria-live="polite"></strong><small data-status="draft">尚未读取设置</small></div><button type="submit" class="primary" data-action="save" disabled>保存全部设置</button></div>
    </form>
    <div data-refresh-confirm></div>`;

  const q = selector => root.querySelector(selector);
  const text = (selector, value) => { const node = q(selector); if (node) node.textContent = value; };
  let routes = new Map();
  let builtinRoutes = new Map();
  let selectedRoute = '';
  let globalTimeout = 60;
  let timeoutConfigured = true;
  let effectiveTimeouts = new Map();
  let disabledSources = new Set();
  let twitterPath = '';
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
    for (const selector of ['[data-field="route"]', '[data-field="timeout"]', '[data-field="twitter"]', '[data-action="new-route"]', '[data-action="restore"]', '[data-action="save"]']) {
      const node = q(selector);
      if (node) node.disabled = !enabled || (selector === '[data-action="save"]' && saving);
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

  function closeEditor(quiet = false) {
    editor = null;
    editorDirty = false;
    q('[data-route-editor]').replaceChildren();
    if (!quiet) updateDraftIndicator();
  }

  function requestEditorAction(action) {
    if (!editor || !editorDirty) { action(); return; }
    const panel = q('[data-route-editor] .route-editor');
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
    const holder = q('[data-route-editor]');
    holder.replaceChildren();
    editorDirty = false;
    const panel = doc.createElement('section');
    panel.className = 'route-editor';
    panel.dataset.mode = mode;
    panel.innerHTML = `<div class="section-title"><div><p class="eyebrow">${editing ? 'EDIT' : copy ? 'COPY' : 'NEW'}</p><h3>${editing ? '编辑分组' : copy ? '复制为新分组' : '新建分组'}</h3></div><button type="button" data-action="close-editor">取消</button></div>
      <div class="route-editor-grid"><label>标识<input data-edit="id" maxlength="64" spellcheck="false" autocomplete="off"></label><label>名称<input data-edit="label" maxlength="80"></label><label>独立超时（留空继承全局）<input data-edit="timeout" type="number" min="1" max="60" step="1"></label></div>
      <fieldset><legend>搜索源（至少一个）</legend><div class="route-source-grid" data-edit="sources"></div></fieldset>
      <p class="route-form-error" data-edit-error role="alert"></p><div class="run-controls"><button type="button" class="primary" data-action="apply-route">应用到草稿</button><small>应用后仍需点击“保存全部设置”写入配置。</small></div>`;
    holder.append(panel);
    const idField = panel.querySelector('[data-edit="id"]');
    idField.value = editing ? routeId : '';
    idField.readOnly = editing;
    idField.title = editing ? '标识创建后不可修改' : '';
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
        note.textContent = '全局停用，执行时跳过';
        label.append(note);
      }
      sourceGrid.append(label);
    }
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
    editor = { mode, routeId };
    panel.scrollIntoView?.({ block: 'nearest' });
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
      meta.textContent = route.timeout != null
        ? `独立超时 · ${route.timeout} 秒`
        : !dirty && !timeoutConfigured && effectiveTimeouts.has(id)
          ? `当前配置 · ${effectiveTimeouts.get(id)} 秒（未显式全局值）`
          : `继承全局 · ${globalTimeout} 秒`;
      const chips = doc.createElement('div'); chips.className = 'route-chips';
      route.sources.forEach(source => chips.append(chip(source)));
      body.append(title, meta, chips);
      const actions = doc.createElement('div'); actions.className = 'route-row-actions';
      const edit = doc.createElement('button'); edit.type = 'button'; edit.textContent = '编辑'; edit.addEventListener('click', () => requestOpenEditor('edit', id));
      const copy = doc.createElement('button'); copy.type = 'button'; copy.textContent = '复制'; copy.addEventListener('click', () => requestOpenEditor('copy', id));
      const remove = doc.createElement('button'); remove.type = 'button'; remove.textContent = '删除';
      const blocked = id === selectedRoute || routes.size === 1;
      remove.disabled = blocked;
      remove.title = id === selectedRoute ? '正在使用：请先在上方切换默认路由' : routes.size === 1 ? '至少保留一个分组' : '';
      remove.addEventListener('click', () => requestEditorAction(() => openDelete(row, id)));
      actions.append(edit, copy, remove); row.append(body, actions);
      if (blocked) { const note = doc.createElement('small'); note.className = 'delete-note'; note.textContent = id === selectedRoute ? '正在使用，先切换默认路由后才能删除。' : '至少保留一个分组。'; row.append(note); }
      list.append(row);
    }
  }

  function renderAll() {
    renderRouteSelect();
    q('[data-field="route"]').value = selectedRoute;
    renderRoutes();
    renderSummary();
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
    loadedView = view;
    routes = cloneRoutes(view.routes);
    builtinRoutes = cloneRoutes(view.builtin_routes);
    selectedRoute = String(view.route || '');
    globalTimeout = Number(view.timeout ?? 60);
    timeoutConfigured = view.timeout_configured !== false;
    effectiveTimeouts = new Map(Object.entries(view.effective_timeouts || { [view.route]: view.effective_timeout }));
    disabledSources = new Set(view.disabled_sources || []);
    twitterPath = view.twitter_cookies_path || '';
    q('[data-field="timeout"]').value = String(globalTimeout);
    q('[data-field="twitter"]').value = twitterPath;
    text('[data-status="path"]', view.config_path || '无法确定配置文件位置');
    text('[data-status="path-source"]', view.path_source === 'env' ? `隔离数据库 MULTI_SEARCH_CONFIG_DB（${view.file_present ? '已存在' : '尚未创建'}）` : `用户 SQLite 配置（${view.file_present ? '已存在' : '尚未创建'}）`);
    text('[data-info="env"]', 'SQLite 是唯一生效配置来源；旧 JSON、环境变量和旧凭据文件不会自动生效。');
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
    if (!Number.isInteger(globalTimeout) || globalTimeout < 1 || globalTimeout > 60) return '全局超时需为 1–60 秒。';
    for (const [id, route] of routes) {
      const error = validateRoute(id, route, new Map([...routes].filter(([other]) => other !== id)), id);
      if (error) return `${route.label || id}：${error}`;
    }
    return '';
  }

  function draftPayload() {
    globalTimeout = Number(q('[data-field="timeout"]').value);
    twitterPath = q('[data-field="twitter"]').value;
    const error = validateDraft();
    if (error) throw new Error(error);
    return {
      route: selectedRoute,
      timeout: globalTimeout,
      disabled_sources: [...disabledSources],
      routes: routesObject(routes),
      twitter_cookies_path: twitterPath,
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
        text('[data-info="error"]', typeof error === 'string' ? error : error?.message || '保存失败，原配置未改变。');
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
    } catch {
      if (!disposed && ticket === refreshTicket) {
        if (loadedView) {
          text('[data-info="error"]', '刷新失败，当前草稿和已加载设置保持不变，请重试。');
        } else {
          routes = new Map();
          effectiveTimeouts = new Map();
          setEnabled(false);
          text('[data-info="error"]', '无法读取搜索设置，请重试。');
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
  q('[data-action="new-route"]').addEventListener('click', () => requestOpenEditor('new'));
  q('[data-action="restore"]').addEventListener('click', openRestoreConfirm);
  q('[data-action="refresh"]').addEventListener('click', () => { void refresh(); });
  q('[data-settings-form]').addEventListener('submit', event => { event.preventDefault(); void saveDraft(); });

  await refresh(true);
  return {
    dispose() { disposed = true; refreshTicket += 1; root.classList.remove('settings-page'); },
    get saved() { return loadedView; },
    get dirty() { return dirty; },
  };
}
