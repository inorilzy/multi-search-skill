import { pageRoot, disposePage } from './dom.js';
import { showError } from './api.js';
import { toMessage } from './errors.js';
// 抓取设置：持久化 fallback 链（settings JSON 的 scrape_backends）与站点记忆只读/写操作。
// 后端列表由 SettingsView.scrape_backend_options 提供，页面不复制后端表。

const cloneChain = chain => (chain || []).map(String);
// Mirrors Python ScrapeBackendSpec.key_required, NOT search-provider key requirements.
// Jina and Firecrawl can scrape anonymously. Runtime cooldown is not a config error.
const REQUIRED_KEY_BACKENDS = ['exa', 'tavily'];

export async function mountScrape(root, api, { number = '06' } = {}) {
  root = pageRoot(root);
  const doc = root.ownerDocument;
  root.classList.add('settings-page', 'scrape-page');
  root.innerHTML = `<section class="heading settings-head"><div><p class="eyebrow">${number} / SETTINGS / SCRAPE</p><h1 tabindex="-1">抓取设置</h1><p>配置通用网页抓取的 fallback 顺序，并查看本机站点记忆。设置保存在 SQLite；抓取仍由独立 CLI 按需执行。</p></div><button type="button" data-action="refresh-chain">刷新</button></section>
    <form data-scrape-form>
      <section class="panel scrape-chain-panel"><div class="section-title"><div><p class="eyebrow">SCRAPE CHAIN</p><h2>抓取链路</h2></div><span class="draft-badge" data-dirty hidden>有未保存修改</span></div>
        <details class="config-details"><summary>说明</summary><p class="route-help">按顺序尝试，第一个失败才用下一个；最后一个也失败时返回错误。这份顺序只对通用网页抓取生效；Reddit / Twitter 按域名固定使用专用抓取器，不受影响。</p></details>
        <p class="error-message settings-warning" data-info="chain-warning" ></p>
        <p class="error-message settings-warning" data-info="saved-chain-warning" ></p>
        <p data-info="error" class="error-message"></p>
        <div class="scrape-chain-head"><span>顺序</span><span>后端</span><span>标识</span><span>操作</span></div>
        <div data-chain-list class="route-list" aria-label="抓取后端顺序"></div>
        <div class="scrape-disabled"><p class="route-help">未启用（点击加入链尾）：</p><div class="route-chips" data-chain-inactive></div></div>
        <p class="route-help" data-info="chain-empty" hidden>全部后端已停用，至少保留一个后端才能保存。</p>
        <div class="run-controls scrape-chain-actions"><button type="button" data-action="restore-chain">恢复默认顺序</button><div data-restore-confirm></div></div>
      </section>
      <div class="settings-savebar"><div><strong class="status-text" data-status="save" aria-live="polite"></strong><small class="status-text" data-status="draft">尚未读取设置</small></div><button type="submit" class="primary" data-action="save" disabled>保存抓取设置</button></div>
    </form>

    <section class="panel scrape-memory-panel"><div class="section-title"><div><p class="eyebrow">SITE MEMORY</p><h2>站点记忆</h2></div><div class="route-actions"><button type="button" data-action="refresh-memory">刷新</button></div></div>
      <p class="route-help">记录每个站点上各后端的成功/失败、冷却与手动偏好。手动固定的后端会排到该站点最前；自动冷却只会让失败后端靠后。</p>
      <p data-info="memory-error" class="error-message"></p>
      <div class="scrape-memory-toolbar"><label>筛选站点<input data-field="site-filter" type="search" autocomplete="off" spellcheck="false" placeholder="输入域名子串，例如 github"></label></div>
      <div data-memory-table class="scrape-table" aria-label="站点抓取记忆"></div>
      <p class="sources-empty" data-memory-empty hidden>还没有抓取记录，执行几次搜索或抓取后这里会出现数据。</p>
    </section>`;

  const q = selector => root.querySelector(selector);
  const text = (selector, value) => { const node = q(selector); if (node) node.textContent = value; };
  let loadedView = null;
  let credentialStates = new Map();
  let chain = [];
  let builtinChain = [];
  let options = new Map();
  let optionOrder = [];
  let dirty = false;
  let chainReadOnly = true;
  let saving = false;
  let refreshing = false;
  let refreshTicket = 0;
  let disposed = false;
  let memory = { available: false, path: null, reason: '', rows: [] };
  let memoryBusy = false;
  let memoryError = '';
  let filter = '';
  let confirmState = null; // { kind: 'pin'|'reset', site, scraper, token }

  const labelOf = name => options.get(name) || name;

  function setEnabled(enabled) {
    // 链内行与加入链尾按钮的禁用由 chainReadOnly 通过 renderChain 派生；
    // 这里只处理不随链重建的控件。
    for (const node of root.querySelectorAll('[data-action="restore-chain"], [data-action="save"], [data-action="refresh-chain"]')) {
      node.disabled = !enabled || saving;
    }
  }

  // 只读状态由 fillChain 写入 chainReadOnly，所有链内按钮的禁用状态都在
  // renderChain 里从它派生，避免重建按钮后丢失禁用。
  function chainDisabled() {
    return chainReadOnly || saving;
  }

  // 以“已保存的链”为准（而不是草稿）：pin 只会重排当前链内的后端。
  function savedChainMembers() {
    return new Set((loadedView?.scrape_backends || []).map(String));
  }

  function pinBlockedReason(name) {
    if (!savedChainMembers().has(String(name))) return '该后端未在抓取链中，先加入链并保存';
    return '';
  }

  function updateDraftIndicator(message) {
    q('[data-dirty]').hidden = !dirty;
    text('[data-status="draft"]', message || (dirty ? '草稿尚未保存' : '当前显示已保存设置'));
    text('[data-status="save"]', '');
  }

  function setDirty(message = '抓取顺序尚未保存') {
    dirty = true;
    updateDraftIndicator(message);
  }

  function inactive() {
    return optionOrder.filter(name => !chain.includes(name));
  }

  function renderChain() {
    const list = q('[data-chain-list]');
    list.replaceChildren();
    const disabled = chainDisabled();
    chain.forEach((name, index) => {
      const row = doc.createElement('article');
      row.className = 'route-row scrape-chain-row';
      row.setAttribute('data-chain-row', name);
      const order = doc.createElement('span');
      order.className = 'scrape-order';
      order.textContent = String(index + 1).padStart(2, '0');
      const body = doc.createElement('div');
      body.className = 'route-main';
      const title = doc.createElement('div');
      title.className = 'route-title';
      const heading = doc.createElement('strong');
      heading.textContent = labelOf(name);
      const code = doc.createElement('code');
      code.textContent = name;
      title.append(heading, code);
      if (index === 0) {
        const badge = doc.createElement('span');
        badge.className = 'current-badge';
        badge.textContent = '首选';
        title.append(badge);
      }
      body.append(title);
      const actions = doc.createElement('div');
      actions.className = 'route-row-actions';
      const up = doc.createElement('button');
      up.type = 'button'; up.textContent = '上移'; up.setAttribute('data-chain-action', 'up');
      up.disabled = disabled || index === 0;
      up.addEventListener('click', () => move(index, -1));
      const down = doc.createElement('button');
      down.type = 'button'; down.textContent = '下移'; down.setAttribute('data-chain-action', 'down');
      down.disabled = disabled || index === chain.length - 1;
      down.addEventListener('click', () => move(index, 1));
      const off = doc.createElement('button');
      off.type = 'button'; off.textContent = '停用'; off.setAttribute('data-chain-action', 'disable');
      off.disabled = disabled;
      off.addEventListener('click', () => disable(name));
      actions.append(up, down, off);
      row.append(order, body, actions);
      list.append(row);
    });
    const holder = q('[data-chain-inactive]');
    holder.replaceChildren();
    const rest = inactive();
    for (const name of rest) {
      const chip = doc.createElement('button');
      chip.type = 'button';
      chip.className = 'route-chip scrape-add-chip';
      chip.setAttribute('data-add-backend', name);
      chip.textContent = `${labelOf(name)} · 加入链尾`;
      chip.disabled = disabled;
      chip.addEventListener('click', () => {
        if (chainDisabled()) return;
        chain.push(name);
        setDirty(`${labelOf(name)} 已加入链尾，尚未保存`);
        renderChain();
        validateChain();
      });
      holder.append(chip);
    }
    if (!rest.length) {
      const note = doc.createElement('span');
      note.className = 'route-help';
      note.textContent = '全部后端都已在链中。';
      holder.append(note);
    }
    q('[data-info="chain-empty"]').hidden = chain.length > 0;
    validateChain();
  }

  async function readCredentialStates() {
    return new Map(await Promise.all(REQUIRED_KEY_BACKENDS.map(async name => {
      try {
        const view = await api.credentialStatus(name);
        return /** @type {[string, string]} */ ([name, view.store.state]);
      } catch {
        return /** @type {[string, string]} */ ([name, 'unknown']);
      }
    })));
  }

  function chainAvailability(names) {
    const required = names.filter(name => REQUIRED_KEY_BACKENDS.includes(name));
    const missing = required.filter(name => ['absent', 'unreadable'].includes(credentialStates.get(name)));
    const unknown = required.filter(name => !['present', 'absent', 'unreadable'].includes(credentialStates.get(name)));
    const blocked = names.length > 0 && missing.length === names.length;
    let warning = missing.length
      ? `${missing.map(labelOf).join('、')} 缺少可用 Key（未配置或无法解密）。${blocked ? '整条链无法运行，不能保存；请在数据源配置 Key，或加入可匿名抓取的 Jina / Firecrawl。' : '这些后端将无法抓取，请配置 Key 或使用链中其他后端。'}`
      : '';
    if (unknown.length) warning += `${unknown.map(labelOf).join('、')} 的凭据状态暂时无法确认，请刷新重试；这不代表永久配置错误。`;
    return { blocked, warning };
  }

  function validateChain() {
    const empty = chain.length === 0;
    const availability = chainAvailability(chain);
    text('[data-info="chain-warning"]', empty ? '全部抓取后端都已停用，抓取不会运行。请至少启用一个后端后再保存。' : availability.warning);
    const savedWarning = chainAvailability(cloneChain(loadedView?.scrape_backends)).warning;
    text('[data-info="saved-chain-warning"]', loadedView?.scrape_backends_invalid
      ? '已保存的抓取链无效，CLI 抓取将报配置错误；请调整后重新保存。'
      : savedWarning ? `已保存的抓取链：${savedWarning}` : '');
    const save = q('[data-action="save"]');
    save.disabled = saving || refreshing || empty || availability.blocked || !loadedView || loadedView.status === 'config_unreadable';
    return !empty && !availability.blocked;
  }

  function move(index, delta) {
    if (chainDisabled()) return;
    const target = index + delta;
    if (target < 0 || target >= chain.length) return;
    [chain[index], chain[target]] = [chain[target], chain[index]];
    setDirty('抓取顺序已在草稿中调整');
    renderChain();
  }

  function disable(name) {
    if (chainDisabled()) return;
    chain = chain.filter(entry => entry !== name);
    setDirty(`${labelOf(name)} 已从链路停用，尚未保存`);
    renderChain();
  }

  function openRestoreConfirm() {
    if (chainDisabled()) return;
    const holder = q('[data-restore-confirm]');
    holder.replaceChildren();
    const panel = doc.createElement('div');
    panel.className = 'inline-confirm restore-confirm';
    panel.innerHTML = '<p>恢复会把抓取顺序重置为出厂链并填入草稿；仍需保存才会写入配置。</p><div class="run-controls"><button type="button" class="primary" data-action="confirm-restore-chain">确认恢复</button><button type="button" data-action="cancel-restore-chain">取消</button></div>';
    holder.append(panel);
    panel.querySelector('[data-action="cancel-restore-chain"]').addEventListener('click', () => holder.replaceChildren());
    panel.querySelector('[data-action="confirm-restore-chain"]').addEventListener('click', () => {
      if (chainDisabled()) return;
      chain = cloneChain(builtinChain);
      holder.replaceChildren();
      setDirty('已恢复默认抓取顺序，尚未保存');
      renderChain();
    });
  }

  function fillChain(view) {
    loadedView = view;
    options = new Map((view.scrape_backend_options || []).map(option => [option.name, option.label]));
    optionOrder = (view.scrape_backend_options || []).map(option => option.name);
    chain = cloneChain(view.scrape_backends).filter(name => options.has(name));
    builtinChain = cloneChain(view.builtin_scrape_backends).filter(name => options.has(name));
    if (!chain.length && options.size) chain = cloneChain(builtinChain);
    if (!optionOrder.length) {
      optionOrder = [...options.keys()];
    }
    dirty = false;
    chainReadOnly = view.status === 'config_unreadable';
    updateDraftIndicator(view.status === 'config_unreadable' ? '配置不可读，保存已禁用' : undefined);
    text('[data-info="error"]', view.status === 'config_unreadable' ? view.message || '现有配置无法读取，保存已被阻止。' : '');
    renderChain();
    setEnabled(!chainReadOnly);
    // pin 资格取决于已保存的链；链刷新后同步重绘记忆表。
    if (memory.rows.length) renderMemory();
    validateChain();
  }

  async function refreshChain(force = false) {
    if (saving) { text('[data-info="error"]', '正在保存设置，完成后再刷新。'); return; }
    if (refreshing) return;
    // 用户确认丢弃后清掉草稿标记，迟到的响应也不会被草稿挡回。
    if (force) dirty = false;
    if (dirty) {
      const holder = q('[data-restore-confirm]');
      holder.replaceChildren();
      const panel = doc.createElement('div');
      panel.className = 'inline-confirm';
      panel.innerHTML = '<p>刷新会丢弃未保存的抓取顺序草稿。确定继续吗？</p><div class="run-controls"><button type="button" class="danger" data-action="confirm-refresh-chain">丢弃并刷新</button><button type="button" data-action="cancel-refresh-chain">取消</button></div>';
      holder.append(panel);
      panel.querySelector('[data-action="cancel-refresh-chain"]').addEventListener('click', () => holder.replaceChildren());
      panel.querySelector('[data-action="confirm-refresh-chain"]').addEventListener('click', () => { holder.replaceChildren(); void refreshChain(true); });
      return;
    }
    const ticket = ++refreshTicket;
    refreshing = true;
    q('[data-action="refresh-chain"]').disabled = true;
    validateChain();
    try {
      const [view, states] = await Promise.all([api.settingsView(), readCredentialStates()]);
      // force 路径已由用户确认丢弃草稿；否则迟到的响应不能覆盖更新的草稿。
      if (!disposed && ticket === refreshTicket && (force || !dirty)) {
        credentialStates = states;
        fillChain(view);
      }
    } catch (error) {
      if (!disposed && ticket === refreshTicket) {
        if (loadedView) showError(q('[data-info="error"]'), error, '刷新失败，当前草稿和已加载设置保持不变，请重试。');
        else {
          showError(q('[data-info="error"]'), error, '无法读取抓取设置，请重试。');
          chain = [];
          chainReadOnly = true;
          q('[data-chain-list]').replaceChildren();
          q('[data-chain-inactive]').replaceChildren();
          setEnabled(false);
          validateChain();
        }
      }
    } finally {
      if (!disposed && ticket === refreshTicket) {
        refreshing = false;
        q('[data-action="refresh-chain"]').disabled = false;
        validateChain();
      }
    }
  }

  async function saveDraft() {
    if (saving || refreshing || !loadedView || loadedView.status === 'config_unreadable') return;
    if (!chain.length) { text('[data-info="error"]', '抓取顺序至少要保留一个后端。'); return; }
    const backends = [...chain];
    saving = true;
    q('[data-restore-confirm]').replaceChildren();
    renderChain();
    setEnabled(!chainReadOnly);
    validateChain();
    q('[data-action="refresh-chain"]').disabled = true;
    text('[data-status="save"]', '保存中…');
    text('[data-info="error"]', '');
    try {
      // Recheck metadata immediately before saving: a key may have been removed
      // since mount. Never retrieve secret values or probe a paid provider here.
      credentialStates = await readCredentialStates();
      if (disposed) return;
      const valid = validateChain();
      const submitted = chainAvailability(backends);
      if (!valid || submitted.blocked) {
        text('[data-status="save"]', '未保存。');
        text('[data-info="error"]', submitted.warning || '请修正抓取链后再保存。');
        return;
      }
      const saved = await api.scrapeSettingsSave(backends);
      if (disposed) return;
      fillChain(saved);
      text('[data-status="save"]', '已保存。');
    } catch (error) {
      if (!disposed) {
        text('[data-status="save"]', '');
        showError(q('[data-info="error"]'), error, '保存失败，原配置未改变。');
        validateChain();
      }
    } finally {
      saving = false;
      if (!disposed) {
        renderChain();
        setEnabled(!chainReadOnly);
        q('[data-action="refresh-chain"]').disabled = false;
        validateChain();
      }
    }
  }

  // ---- 站点记忆 ------------------------------------------------------
  function visibleRows() {
    const needle = filter.trim().toLowerCase();
    return memory.rows.filter(row => !needle || row.site.toLowerCase().includes(needle));
  }

  function removeConfirm() {
    confirmState = null;
    q('[data-memory-confirm]')?.remove();
  }

  function memoryWritable() {
    return memory.available && !memoryBusy;
  }

  function renderMemory() {
    const table = q('[data-memory-table]');
    table.replaceChildren();
    const error = q('[data-info="memory-error"]');
    error.textContent = memoryError || (memory.available ? '' : memory.reason || '尚无抓取状态数据');
    const rows = visibleRows();
    q('[data-memory-empty]').hidden = !memory.available || rows.length > 0;
    if (!memory.available) {
      text('[data-memory-empty]', '');
    } else if (!rows.length) {
      text('[data-memory-empty]', memory.rows.length
        ? '没有匹配该站点的抓取记录，请调整筛选条件。'
        : '还没有抓取记录，执行几次搜索或抓取后这里会出现数据。');
    }
    if (!rows.length) {
      removeConfirm();
      return;
    }
    const head = doc.createElement('div');
    head.className = 'scrape-table-head';
    for (const label of ['站点', '后端', '成功 / 失败 / 拦截 / 超时', '平均正文长度', '最近成功', '冷却', '固定', '操作']) {
      const cell = doc.createElement('span');
      cell.textContent = label;
      head.append(cell);
    }
    table.append(head);
    for (const row of rows) {
      const line = doc.createElement('article');
      line.className = 'scrape-table-row';
      line.setAttribute('data-memory-row', `${row.site}|${row.scraper}`);
      const add = (className, value) => {
        const cell = doc.createElement('span');
        if (className) cell.className = className;
        cell.textContent = value;
        line.append(cell);
        return cell;
      };
      add('scrape-site', row.site);
      add('scrape-backend', labelOf(row.scraper));
      add('scrape-counts', `${row.success_count} / ${row.failure_count} / ${row.blocked_count} / ${row.timeout_count}`);
      add('scrape-muted', row.avg_content_length == null ? '—' : `${row.avg_content_length} 字符`);
      add('scrape-muted', row.last_success_at || '—');
      add('scrape-muted', row.in_cooldown
        ? `冷却至 ${row.cooldown_until || '未知时间'}`
        : row.cooldown_until ? `已到期（${row.cooldown_until}）` : '正常');
      add('scrape-muted', row.manually_pinned
        ? `手动固定${row.manual_priority == null ? '' : ` · ${row.manual_priority}`}`
        : '自动排序');
      const actions = doc.createElement('div');
      actions.className = 'route-row-actions';
      if (!options.has(row.scraper)) {
        // 平台专用抓取器（reddit/twitter 等）按域名分派，不参与通用链重排。
        const note = doc.createElement('span');
        note.className = 'scrape-muted';
        note.setAttribute('data-memory-pin-note', row.scraper);
        note.textContent = '平台抓取，按域名分派';
        actions.append(note);
      } else {
        const blocked = pinBlockedReason(row.scraper);
        const pin = doc.createElement('button');
        pin.type = 'button'; pin.textContent = '优先使用此后端';
        pin.setAttribute('data-memory-action', 'pin');
        pin.disabled = !memoryWritable() || Boolean(blocked);
        if (blocked) pin.title = blocked;
        pin.addEventListener('click', () => openConfirm(line, 'pin', row));
        actions.append(pin);
        if (blocked) {
          const hint = doc.createElement('span');
          hint.className = 'scrape-muted';
          hint.setAttribute('data-memory-pin-hint', row.scraper);
          hint.textContent = blocked;
          actions.append(hint);
        }
      }
      const reset = doc.createElement('button');
      reset.type = 'button'; reset.textContent = '清除此站点记忆';
      reset.setAttribute('data-memory-action', 'reset');
      reset.disabled = !memoryWritable();
      reset.addEventListener('click', () => openConfirm(line, 'reset', row));
      actions.append(reset);
      line.append(actions);
      table.append(line);
    }
    if (confirmState && !rows.some(row => row.site === confirmState.site && row.scraper === confirmState.scraper)) {
      removeConfirm();
    }
  }

  function openConfirm(line, kind, row) {
    removeConfirm();
    const token = (confirmState?.token || 0) + 1;
    confirmState = { kind, site: row.site, scraper: row.scraper, token };
    const confirm = doc.createElement('div');
    confirm.className = 'inline-confirm';
    confirm.setAttribute('data-memory-confirm', kind);
    const message = doc.createElement('p');
    message.textContent = kind === 'pin'
      ? `将 ${labelOf(row.scraper)} 固定为 ${row.site} 的首选后端。该写入会立即保存到本机抓取记忆。`
      : `清除 ${row.site} 的全部抓取记忆（含所有后端与尝试记录）。该操作不可撤销。`;
    const actions = doc.createElement('div');
    actions.className = 'run-controls';
    const yes = doc.createElement('button');
    yes.type = 'button'; yes.className = kind === 'reset' ? 'danger' : 'primary';
    yes.textContent = kind === 'pin' ? '确认优先' : '确认清除';
    yes.setAttribute('data-action', 'confirm-memory');
    const no = doc.createElement('button');
    no.type = 'button'; no.textContent = '取消'; no.setAttribute('data-action', 'cancel-memory');
    actions.append(yes, no);
    confirm.append(message, actions);
    line.append(confirm);
    no.addEventListener('click', removeConfirm);
    yes.addEventListener('click', () => {
      if (!confirmState || confirmState.token !== token) return;
      void runMemory(kind, row);
    });
  }

  async function runMemory(kind, row) {
    if (!memoryWritable()) return;
    memoryBusy = true;
    memoryError = '';
    text('[data-info="memory-error"]', kind === 'pin' ? '正在固定后端…' : '正在清除站点记忆…');
    try {
      const view = kind === 'pin'
        ? await api.scrapeMemoryPin(row.site, row.scraper)
        : await api.scrapeMemoryReset(row.site);
      if (disposed) return;
      memory = view;
      removeConfirm();
      renderMemory();
      text('[data-info="memory-error"]', view.available ? '' : view.reason || '尚无抓取状态数据');
    } catch (error) {
      if (!disposed) {
        memoryError = toMessage(error, kind === 'pin' ? '固定后端失败，请重试。' : '清除站点记忆失败，请重试。');
        removeConfirm();
      }
    } finally {
      memoryBusy = false;
      if (!disposed) renderMemory();
    }
  }

  async function refreshMemory() {
    if (memoryBusy) return;
    memoryBusy = true;
    memoryError = '';
    removeConfirm();
    q('[data-action="refresh-memory"]').disabled = true;
    text('[data-info="memory-error"]', '正在读取站点记忆…');
    try {
      const view = await api.scrapeMemoryView(null);
      if (!disposed) {
        memory = view;
        renderMemory();
      }
    } catch (error) {
      if (!disposed) {
        memory = { available: false, path: null, reason: '', rows: [] };
        renderMemory();
        showError(q('[data-info="memory-error"]'), error, '无法读取站点抓取记忆，请重试。');
      }
    } finally {
      memoryBusy = false;
      if (!disposed) {
        q('[data-action="refresh-memory"]').disabled = false;
        renderMemory();
      }
    }
  }

  q('[data-action="restore-chain"]').addEventListener('click', openRestoreConfirm);
  q('[data-action="refresh-chain"]').addEventListener('click', () => { void refreshChain(); });
  q('[data-action="refresh-memory"]').addEventListener('click', () => { void refreshMemory(); });
  q('[data-field="site-filter"]').addEventListener('input', event => {
    filter = event.target.value;
    renderMemory();
  });
  q('[data-scrape-form]').addEventListener('submit', event => { event.preventDefault(); void saveDraft(); });

  await Promise.all([refreshChain(true), refreshMemory()]);
  return {
    dispose() { disposePage(root);
      disposed = true;
      refreshTicket += 1;
      root.classList.remove('settings-page', 'scrape-page');
    },
    get saved() { return loadedView; },
    get dirty() { return dirty; },
    get memory() { return memory; },
  };
}
