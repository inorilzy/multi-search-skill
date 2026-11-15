import { pageRoot, confirmInline, disposePage, el } from './dom.js';
import { showError } from './api.js';
import { SEARCH_SOURCES } from './catalog.js';
import { SOURCE_CATALOG } from './source-catalog.js';
import { mountOAuthLogin } from './oauth-login.js';
import { mountDashboardLogin } from './dashboard-login.js';

// Search sources come from the catalog generated from Python core metadata (one source of truth for
// the CLI and this UI). Scraper-only providers also live there: they have credentials but no search
// endpoint, so they get a credential panel without a connectivity test.
export const SOURCES = SEARCH_SOURCES.map(({ name, label, keyed, key_optional: keyOptional, cookie, description, mark }) => ({
  source: name,
  label,
  keyed,
  keyOptional: Boolean(keyOptional),
  cookie,
  description,
  mark,
}));

const SCRAPE_PROVIDERS = SOURCE_CATALOG.sources
  .filter(entry => entry.searchable === false && entry.keyed === true)
  .map(entry => ({ source: entry.name, label: entry.label, keyed: true, cookie: entry.cookie, search: false }));

/// Scraper-only providers that own credentials (no search test).
export function scrapeCredentialProviders() {
  return SCRAPE_PROVIDERS;
}

const DEFAULT_SOURCE = 'tavily';
// Balance-only credentials are not search sources, so they are not in the generated catalog.
// The only such entry the credential editor exposes today is Exa's Team Management service key.
const EXTRA_CREDENTIALS = {
  exa_admin: { source: 'exa_admin', label: 'Exa 管理 Key', keyed: true, search: false, balanceOnly: true },
};
const storeLabels = { present: '已保存', absent: '未保存', unavailable: 'Key 文件无法读取', unreadable: '已保存条目格式无法识别' };
export const KEYS_FILE_NOTE = 'Key 以明文保存在 ~/.multi-search/keys.json（仅当前用户可读写）';

// Effective source as Core reports it (types.d.ts: env | file | none). Unknown future values stay labelled.
function sourceText(overview) {
  if (overview.effective_source === 'env') return overview.env_var ? `环境变量 ${overview.env_var}` : '环境变量';
  if (overview.effective_source === 'file') {
    const count = overview.file_key_count;
    return typeof count === 'number' && count > 0
      ? `Key 文件（~/.multi-search/keys.json）中的 ${count} 个 Key`
      : 'Key 文件（~/.multi-search/keys.json）';
  }
  if (overview.effective_source === 'none') return '未配置';
  return `未知来源（${overview.effective_source ?? '无'}）`;
}

// Localized test outcomes; a raw backend enum is never the visible title.
function testText(result, label, provenance) {
  const labels = {
    success: `测试成功：${label} 本次使用 ${provenance}。`,
    auth_failed: `认证失败：${label} 拒绝了该 Key。`,
    quota: `额度不足：${label} 额度已用尽。`,
    rate_limited: '触发频率限制：请稍后再试。',
    missing_key: '缺少 Key：请先保存。',
    network: `网络错误：无法连接 ${label}。`,
    timeout: '超时：请稍后重试。',
    error: '测试失败：请查看 CLI 输出。',
    cli_failed: 'CLI 未返回有效结果。',
  };
  return labels[result] || '测试失败';
}
/** @typedef {{ source: string, label: string, keyed: boolean, keyOptional?: boolean, cookie?: boolean, search?: boolean, balanceOnly?: boolean }} CredentialEntry */
/** @param {string} source @returns {CredentialEntry} */
const sourceEntry = source => SOURCES.find(item => item.source === source)
  || SCRAPE_PROVIDERS.find(item => item.source === source)
  || EXTRA_CREDENTIALS[source]
  || SOURCES.find(item => item.source === DEFAULT_SOURCE)
  || { source, label: source, keyed: true, search: true };
const provenance = value => JSON.stringify([value.effective_source, value.store?.state, value.store?.saved_at]);
/** @param {HTMLElement} root @param {any} api @param {{ number?: string, source?: string, onStatus?: (view: any) => void, onTest?: (result: any) => void }} [options] */
export async function mountCredentials(root, api, options = {}) {
  root = pageRoot(root);
  const { number = '04', ...pageOptions } = options;
  const entry = sourceEntry(pageOptions.source);
  root.innerHTML = `<section class="heading"><p class="eyebrow">${number} / CREDENTIALS</p><h1 tabindex="-1">凭据</h1><p>Key 默认掩码显示。生效来源按 Core 的优先级判定：环境变量 > Key 文件。</p></section>`;
  root.querySelector('h1').textContent = `${entry.label} 凭据`;
  const holder = root.ownerDocument.createElement('div'); root.append(holder);
  return mountCredentialBody(holder, api, pageOptions);
}
// Exa's Team Management service key is a balance-only credential, not a search source. It is
// edited with the same credential editor so saving/removing uses the shared keys-file commands.
async function mountExaAdminEditor(root, api) {
  const doc = root.ownerDocument;
  const section = doc.createElement('details');
  section.className = 'exa-admin-key';
  section.innerHTML = `<summary>管理 Key（仅用于查余额）</summary><p class="credential-note">也可登录控制台查询余额。已有 Team Management Service Key 时可在此填写，优先使用管理 Key。</p><div data-exa-admin-body></div>`;
  root.append(section);
  return mountCredentialBody(section.querySelector('[data-exa-admin-body]'), api, { source: 'exa_admin' });
}
/** @param {any} root @param {any} api @param {{source?: string, onStatus?: (view: any) => void, onTest?: (result: any) => void, onLogin?: () => void, balanceOnly?: boolean, oauthPollInterval?: number, accountEditor?: boolean}} [options] */
export async function mountCredentialBody(root, api, { source = DEFAULT_SOURCE, onStatus, onTest, onLogin, balanceOnly = false, oauthPollInterval = 150, accountEditor = false } = {}) {
  root = pageRoot(root);
  const { label, search, keyOptional, balanceOnly: entryBalanceOnly } = sourceEntry(source);
  balanceOnly = balanceOnly || Boolean(entryBalanceOnly);
  const searchTest = search !== false && !balanceOnly;
  root.innerHTML = `<div class="credential-editor"><div class="credential-fields">
    <p class="credential-note credential-intro">API Key：每行一条，可保存多条轮换使用。</p>
    <p class="credential-note" data-key-optional hidden>无需 API Key 也能使用；填写 Key 只用于提高每日额度。</p>
    <div data-saved-list class="key-saved-list"></div>
    <p data-saved-empty class="credential-note key-saved-empty" hidden>当前没有已保存的 Key。</p>
    <form data-save-form class="key-draft-form">
      <div data-draft-list class="key-draft-list"></div>
      <div class="draft-controls"><button type="button" class="key-add" data-action="add" aria-label="新增一行 Key 输入">＋ 新增 Key</button>
      <button type="submit" class="primary" data-action="save" hidden>保存新增 Key</button></div>
    </form>
    <div class="run-controls credential-actions"><label data-test-key-label hidden>待测 Key<select data-test-key aria-label="选择待测的单把 Key"></select></label><button type="button" data-action="test">测试连接</button><button type="button" data-action="application" disabled>获取 API Key</button>
      <span class="credential-note" data-info="application">正在确认申请链接与打开能力…</span></div>
    <div class="application-fallback" data-application-fallback hidden><label>固定申请链接（可选择并手动复制）<input type="text" readonly data-application-url spellcheck="false" aria-label="固定申请链接"></label></div>
    <p data-info="error" class="error-message"></p>
    <div class="credential-footer">
      <dl class="cred-status"><dt>已保存</dt><dd class="status-text" data-status="store"></dd><dt>生效来源</dt><dd class="status-text" data-status="source"></dd></dl>
      <div class="credential-tools"><button type="button" data-action="refresh">刷新已保存值</button></div>
    </div>
    <details class="config-details"><summary>说明</summary><p data-keys-file-note class="credential-note" role="note"></p><p class="credential-note">保存不会发起搜索。生效来源按 Core 的优先级判定：环境变量 > Key 文件。未修改的 Key 保留 exhausted 等已有元数据。</p></details></div>
    <div class="credential-feedback"><div class="test-result" data-test-result data-kind="idle"><span class="result-symbol" aria-hidden="true"></span><div><strong class="status-text" data-status="test" aria-live="polite">尚未测试</strong><p data-info="test" role="status"></p></div></div>
    <details class="config-details"><summary>说明</summary><p class="credential-note">${searchTest ? `测试会向对应服务发送外部搜索请求，可能消耗额度。每次只测试所选的一把 Key，默认选中最后一行；环境变量单独列出。新增后请先保存。测试不写入正式状态库。` : '仅用于网页抓取，不提供搜索连接测试。保存 Key 不会发起外部请求。新增 Key 视为新条目，删除一行即移除该条目。'}</p></details></div></div>`;
  if (keyOptional) root.querySelector('[data-key-optional]').hidden = false;
  root.querySelector('.credential-note').prepend(root.ownerDocument.createTextNode(`${label} `));
  if (balanceOnly) {
    root.querySelector('.credential-intro').textContent = '管理 Key：每行一条，仅用于查询余额，不会用于搜索。';
    for (const node of root.querySelectorAll('[data-test-key-label], [data-action="test"], [data-action="application"], [data-info="application"], [data-application-fallback], .credential-feedback')) {
      node.hidden = true;
    }
  }
  const q = selector => /** @type {any} */ (root.querySelector(selector));
  const text = (selector, value) => { q(selector).textContent = value; };
  let current = { store: { state: 'absent', error: '' }, effective_source: 'none' };
  // Application entry state machine. 'pending' = the metadata query is in flight (the
  // button stays disabled, so an unconfirmed entry never flashes as usable); 'failed' =
  // that query itself failed (distinct from "no fixed link" and from "this platform
  // cannot open", which only an answer may claim); 'ok' = the backend answered with the
  // fixed link and the browser-open capability. Only the latest refresh publishes this
  // state, so a slower older response cannot revive a stale entry.
  let application = { phase: 'pending' };
  const appOpens = state =>
    state.phase === 'ok'
    && state.key_application_available === true
    && state.key_application_open_supported !== false;
  // A browser-launch failure keeps the entry usable (retry stays enabled) and shows the
  // same trusted link from `application` for manual copying. The link never comes from
  // the failed call, its error text, or the user, so a failure cannot redirect the entry.
  // `opening` holds the entry for one in-flight launch at a time.
  let openFailed = false, opening = false, openFailureText = '';
  const appNote = state => {
    if (state.phase === 'pending') return '正在确认申请链接与打开能力…';
    if (state.phase === 'failed') return '无法确认申请链接与打开能力，请点击“刷新已保存值”重试。';
    if (state.key_application_available !== true) return '该搜索源暂无固定申请链接，无法打开申请页。';
    if (state.key_application_open_supported === false) {
      return state.key_application_url
        ? `当前平台无法直接打开系统浏览器，请手动复制固定申请链接：${state.key_application_url}`
        : '当前平台无法直接打开系统浏览器，且暂无可复制的固定申请链接。';
    }
    // A launch that the backend reported as failed must not keep describing the
    // browser path as though it had worked.
    if (openFailed) {
      return state.key_application_url
        ? '系统浏览器打开失败，可点击下方固定申请链接手动复制，或重试。'
        : '系统浏览器打开失败，请重试。';
    }
    return '使用系统浏览器打开固定申请链接';
  };
  function renderApplication() {
    text('[data-info="application"]', appNote(application));
    q('[data-action="application"]').disabled = busy || opening || !appOpens(application);
    const fallback = q('[data-application-fallback]');
    const showFallback = openFailed && application.phase === 'ok' && Boolean(application.key_application_url);
    fallback.hidden = !showFallback;
    q('[data-application-url]').value = showFallback ? application.key_application_url : '';
  }
  let generation = 0, disposed = false, busy = false;
  q('[data-keys-file-note]').textContent = KEYS_FILE_NOTE;
  // Monotonic refresh guard: only the latest refresh may publish status or
  // rows. A slower older response must never overwrite a newer outcome.
  let refreshGeneration = 0;
  /** @type {string[]} rows last confirmed by credentialRead */
  let savedRows = [];
  const revealed = new Map();
  /** @type {string|null} snapshot used as remove guard */
  let readSnapshot = null;
  let readHealthy = false;
  /** @type {string[]} draft input values; index aligned with draft rows. Empty until "新增 Key". */
  let drafts = [];
  function reportTest(kind, title, message = '') {
    if (disposed) return;
    text('[data-status="test"]', title); text('[data-info="test"]', message);
    q('[data-test-result]').dataset.kind = kind; onTest?.({ kind, title, message });
  }
  function invalidateTest() { generation += 1; reportTest('idle', '尚未测试'); }
  // Every mutation requires a successful row read so the remove guard has a live snapshot.
  const writesReady = () => readHealthy;
  function setBusy(value) {
    busy = value;
    root.setAttribute('aria-busy', String(value)); root.classList.toggle('is-busy', value);
    for (const button of root.querySelectorAll('button')) button.disabled = value;
    for (const input of root.querySelectorAll('[data-draft-list] input')) input.disabled = value || !writesReady();
    for (const input of root.querySelectorAll('[data-saved-list] input')) input.disabled = value;
    for (const button of root.querySelectorAll('[data-action="copy"]')) button.disabled = value || !revealed.has(Number(button.dataset.rowIndex));
    for (const button of root.querySelectorAll('[data-action="reveal"]')) button.disabled = value || !readHealthy;
    renderApplication();
    q('[data-test-key]').disabled = value;
    q('[data-action="test"]').disabled = value || !searchTest;
    q('[data-action="test"]').hidden = !searchTest;
    // Saved-row delete and draft add/submit are mutations; keep them disabled
    // until a successful read anchors the remove guard.
    for (const button of root.querySelectorAll('[data-action="remove"], [data-action="remove-draft"], [data-action="add"], [data-action="save"]')) button.disabled = value || !writesReady();
  }
  function renderSaved() {
    const list = q('[data-saved-list]');
    list.innerHTML = '';
    q('[data-saved-empty]').hidden = savedRows.length > 0;
    const select = q('[data-test-key]');
    select.replaceChildren();
    const choices = savedRows.map((_, index) => [String(index), `已保存 Key 第 ${index + 1} 行`]);
    if (current.effective_source === 'env') choices.push(['env', '环境变量中的 Key']);
    for (const [value, label] of choices) {
      const option = root.ownerDocument.createElement('option');
      option.value = value; option.textContent = label; select.append(option);
    }
    select.value = savedRows.length ? String(savedRows.length - 1) : current.effective_source === 'env' ? 'env' : '';
    q('[data-test-key-label]').hidden = !searchTest || choices.length === 0;
    savedRows.forEach((value, index) => {
      const row = root.ownerDocument.createElement('div');
      row.className = accountEditor ? 'key-row' : 'key-saved-row'; row.dataset.savedIndex = String(index);
      row.innerHTML = `<span class="key-row-label" aria-hidden="true">Key ${index + 1}</span><input type="password" readonly data-saved-input aria-label="已保存 Key 第 ${index + 1} 行">
        <span class="key-row-actions"><button type="button" data-action="reveal" data-row-index="${index}">显示</button><button type="button" data-action="copy" data-row-index="${index}" disabled>复制</button><button type="button" class="key-remove" data-action="remove" data-remove-index="${index}" aria-label="删除第 ${index + 1} 行 Key">删除</button></span>
        <div data-confirm-slot></div>`;
      // Saved value is assigned via .value, never innerHTML, so raw key text
      // cannot break the markup.
      row.querySelector('input').value = value;
      if (accountEditor) {
        const fingerprint = root.ownerDocument.createElement('span');
        fingerprint.className = 'key-fingerprint';
        fingerprint.textContent = value;
        row.querySelector('.key-row-label').replaceWith(fingerprint);
      }
      list.append(row);
    });
  }
  function renderDrafts() {
    const list = q('[data-draft-list]');
    // Mirror the live inputs back before rebuilding: programmatic value
    // assignment does not fire input events, so capture it here.
    const existing = list.querySelectorAll('input');
    existing.forEach((input, index) => { if (index < drafts.length) drafts[index] = input.value; });
    list.innerHTML = '';
    drafts.forEach((value, index) => {
      const row = root.ownerDocument.createElement('div');
      row.className = 'key-draft-row'; row.dataset.draftIndex = String(index);
      row.innerHTML = `<span class="key-row-label" aria-hidden="true">新增</span><input type="text" data-field="key" data-draft-input autocomplete="off" spellcheck="false" aria-label="新增 Key 第 ${index + 1} 行" placeholder="粘贴一条 Key">
        <span class="key-row-actions"><button type="button" data-action="remove-draft" aria-label="移除该输入行">取消</button></span>`;
      const input = row.querySelector('input');
      input.value = value;
      list.append(row);
    });
    // Save only makes sense while a draft row exists.
    q('[data-action="save"]').hidden = drafts.length === 0;
    setBusy(busy);
  }
  function render(view) {
    if (disposed) return;
    if (provenance(current) !== provenance(view)) invalidateTest();
    current = view; onStatus?.(view);
    setBusy(busy);
    text('[data-status="store"]', storeLabels[view.store.state] || view.store.state);
    text('[data-status="source"]', sourceText(view));
    // A confirmed answer, which may legitimately be "no mapping" or "platform cannot open".
    application = {
      phase: 'ok',
      key_application_available: view.key_application_available,
      key_application_open_supported: view.key_application_open_supported,
      key_application_url: view.key_application_url,
    };
    renderApplication();
  }
  // `requestId` ties a read-back to its owning refresh; non-refresh callers
  // (reveal snapshot re-check, post-save/post-remove read-back) pass the
  // current generation so they always apply.
  async function readBack(requestId = refreshGeneration) {
    const saved = await api.credentialRead(source);
    if (disposed || requestId !== refreshGeneration) return;
    readSnapshot = saved.snapshot;
    revealed.clear();
    savedRows = saved.value.split('\n').filter(line => line.trim() !== '');
    readHealthy = true;
    renderSaved();
  }
  async function refresh() {
    // A newer refresh supersedes this one: only it may publish status or
    // rows, so a slower older response cannot overwrite a newer outcome.
    const requestId = ++refreshGeneration;
    // An in-flight query is not yet an answer, so the application button stays
    // disabled until this request (or a newer one) resolves.
    application = { phase: 'pending' };
    // A new metadata answer supersedes an earlier browser-launch failure.
    openFailed = false; openFailureText = '';
    renderApplication();
    setBusy(true);
    try {
      const view = await api.credentialStatus(source);
      if (disposed || requestId !== refreshGeneration) return;
      render(view);
      try {
        await readBack(requestId);
        if (disposed || requestId !== refreshGeneration) return;
        if (readHealthy) text('[data-info="error"]', current.store.error || '');
      } catch (readError) {
        if (!disposed && requestId === refreshGeneration) {
          readHealthy = false;
          // Rows could not be read: the error slot gets the read reason and
          // writes stay off until a refresh read succeeds again.
          renderSaved();
          showError(q('[data-info="error"]'), readError, '无法读取已保存凭据，请重试。');
        }
      }
    } catch (error) {
      if (!disposed && requestId === refreshGeneration) {
        // A failed lookup is never an empty, writable file: writes stay disabled.
        readHealthy = false;
        // The application metadata came from the same failed query: report it as
        // unconfirmed with the existing retry entry, never as "no link"/"unsupported".
        application = { phase: 'failed' };
        renderApplication();
        // Keep the last saved rows visible so the user can still see state; all
        // writes stay disabled until a refresh succeeds again.
        renderSaved();
        showError(q('[data-info="error"]'), error, '无法读取凭据状态，请重试。');
      }
    }
    finally { if (!disposed && requestId === refreshGeneration) setBusy(false); }
  }
  q('[data-draft-list]').addEventListener('input', event => {
    const input = event.target.closest('input'); if (!input) return;
    drafts[Number(input.closest('[data-draft-index]').dataset.draftIndex)] = input.value; invalidateTest();
  });
  q('[data-draft-list]').addEventListener('paste', event => {
    if (/[\r\n]/.test(event.clipboardData?.getData('text') || '')) { event.preventDefault(); text('[data-info="error"]', '每行一条 Key：多行内容请拆分后逐行粘贴。'); }
  });
  q('[data-draft-list]').addEventListener('click', event => {
    const button = event.target.closest('[data-action="remove-draft"]');
    if (!button || busy || !writesReady() || disposed) return;
    const index = Number(button.closest('[data-draft-index]').dataset.draftIndex);
    drafts.splice(index, 1);
    renderDrafts();
  });
  q('[data-saved-list]').addEventListener('click', async event => {
    const button = event.target.closest('[data-action="reveal"], [data-action="copy"]');
    if (!button || busy || disposed) return;
    if (button.dataset.action === 'reveal' && !readHealthy) return;
    const index = Number(button.dataset.rowIndex);
    const row = button.closest('[data-saved-index]');
    const input = row.querySelector('input');
    if (button.dataset.action === 'copy') {
      try { if (revealed.has(index)) await root.ownerDocument.defaultView.navigator.clipboard.writeText(revealed.get(index)); }
      catch (error) { showError(q('[data-info="error"]'), error, '复制失败，请手动复制。'); }
      return;
    }
    if (revealed.has(index)) {
      revealed.delete(index); input.value = savedRows[index]; input.type = 'password'; button.textContent = '显示'; setBusy(false); return;
    }
    setBusy(true);
    try {
      const value = await api.credentialReveal(source);
      if (disposed) return;
      if (value.snapshot !== readSnapshot) { await readBack(); throw new Error('凭据已变化，请重新显示。'); }
      const key = value.value.split('\n').filter(line => line.trim() !== '')[index];
      if (key === undefined) throw new Error('凭据已变化，请刷新。');
      revealed.set(index, key); input.value = key; input.type = 'text'; button.textContent = '隐藏';
    } catch (error) { if (!disposed) showError(q('[data-info="error"]'), error, '无法显示这一行 Key，请重试。'); }
    finally { if (!disposed) setBusy(false); }
  });
  q('[data-save-form]').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !writesReady() || disposed) return;
    // Collect from the live inputs, not the drafts mirror: programmatic value
    // assignment (and any path that skipped the input event) still submits.
    const keys = [...q('[data-draft-list]').querySelectorAll('input')].map(input => input.value.trim()).filter(value => value !== '');
    if (keys.length === 0) { text('[data-info="error"]', '请先输入至少一条 Key。'); return; }
    invalidateTest(); setBusy(true);
    try {
      render(await api.credentialAppend(source, keys));
      if (disposed) return;
      // Clear submitted drafts before reading back: a failed read must not turn
      // a successful append into a duplicate retry.
      drafts = [];
      q('[data-draft-list]').innerHTML = '';
      renderDrafts();
      try {
        await readBack();
        if (!disposed) text('[data-info="test"]', '已保存。尚未测试。');
      } catch (error) {
        if (!disposed) {
          readHealthy = false;
          renderSaved();
          text('[data-info="error"]', '已保存，但刷新读取失败；请刷新后再继续编辑。');
        }
      }
    } catch (error) { if (!disposed) showError(q('[data-info="error"]'), error, '保存失败，编辑值已保留。'); }
    finally { if (!disposed) setBusy(false); }
  });
  q('[data-action="add"]').addEventListener('click', () => {
    if (busy || !writesReady() || disposed) return;
    drafts.push(''); renderDrafts();
    const inputs = q('[data-draft-list]').querySelectorAll('input');
    inputs[inputs.length - 1]?.focus();
  });
  q('[data-saved-list]').addEventListener('click', event => {
    const button = event.target.closest('[data-action="remove"]');
    if (!button) return;
    if (busy || !writesReady() || disposed) return;
    const index = Number(button.dataset.removeIndex);
    const row = button.closest('[data-saved-index]');
    const slot = row.querySelector('[data-confirm-slot]');
    if (slot.firstElementChild) return;
    const panel = root.ownerDocument.createElement('div');
    panel.className = 'inline-confirm'; panel.dataset.confirm = 'remove';
    panel.innerHTML = `<p class="note">确定删除第 ${index + 1} 行已保存的 Key 吗？该行会从 ~/.multi-search/keys.json 中移除，环境变量不受影响。</p><div class="run-controls"><button type="button" class="danger" data-action="confirm-remove">确认删除</button><button type="button" data-action="cancel-remove">取消</button></div>`;
    slot.append(panel);
    // Shared contract: cancel has focus, Escape cancels, focus returns to this row's delete button.
    const release = confirmInline(panel, () => { panel.remove(); release(); }, button);
    panel.querySelector('[data-action="cancel-remove"]').addEventListener('click', () => { panel.remove(); release(); });
    panel.querySelector('[data-action="confirm-remove"]').addEventListener('click', async () => {
      if (busy || !writesReady() || disposed) return;
      invalidateTest(); setBusy(true);
      try {
        render(await api.credentialRemove(source, index, readSnapshot));
        if (!disposed) {
          // Reread rather than assuming the splice: a concurrent append or a
          // stale snapshot is resolved by the backend's exact-occurrence guard,
          // and the UI reflects whatever the store now holds.
          try {
            await readBack();
            if (!disposed) text('[data-info="test"]', '已删除。');
          } catch {
            if (!disposed) {
              readHealthy = false;
              renderSaved();
              text('[data-info="error"]', '已删除，但刷新读取失败；请刷新后再继续编辑。');
            }
          }
        }
      } catch (error) {
        if (!disposed) { panel.remove(); showError(q('[data-info="error"]'), error, '删除失败，已保存值未变。'); }
      } finally { if (!disposed) setBusy(false); }
    });
  });
  q('[data-action="application"]').addEventListener('click', async () => {
    // Guard the action itself too: a synthesized click on a disabled entry must not
    // open anything before the metadata query has confirmed the link and capability.
    // `opening` keeps repeated clicks from starting parallel browser launches.
    if (busy || disposed || opening || !appOpens(application)) return;
    opening = true; renderApplication();
    try {
      await api.credentialApplicationOpen(source);
      if (disposed) return;
      // A confirmed launch clears the earlier failure. The error slot is emptied only
      // while it still carries that failure text, so an unrelated message survives.
      if (openFailed) {
        const slot = q('[data-info="error"]');
        if (openFailureText && slot.textContent === openFailureText) { slot.textContent = ''; slot.title = ''; }
        openFailed = false; openFailureText = '';
      }
    } catch (error) {
      if (!disposed) {
        openFailed = true;
        openFailureText = showError(q('[data-info="error"]'), error, '无法打开系统浏览器，请重试或手动复制固定申请链接。').message;
      }
    } finally {
      opening = false;
      if (!disposed) renderApplication();
    }
  });
  q('[data-action="test"]').addEventListener('click', async () => {
    if (!searchTest) return;
    setBusy(true); const testedGeneration = ++generation; const testedSource = q('[data-test-key]').selectedOptions[0]?.textContent || sourceText(current); reportTest('running', '正在测试');
    try {
      const selected = q('[data-test-key]').value;
      const selection = selected && selected !== 'env' ? { index: Number(selected), expected: readSnapshot } : undefined;
      const outcome = selection ? await api.credentialTest(source, selection) : await api.credentialTest(source);
      if (testedGeneration === generation && !disposed) reportTest(outcome.result === 'success' ? 'success' : 'error', testText(outcome.result, label, testedSource), outcome.message || '');
    } catch (error) {
      // Launch failures go to the error slot; the test area only says the test did not run.
      if (testedGeneration === generation && !disposed) {
        reportTest('error', '测试失败', '');
        showError(q('[data-info="error"]'), error, '测试启动失败，请检查 CLI 后重试。');
      }
    }
    finally { if (!disposed) setBusy(false); }
  });
  q('[data-test-key]').addEventListener('change', invalidateTest);
  q('[data-action="refresh"]').addEventListener('click', refresh);
  renderDrafts();
  await refresh();
  const extraDisposers = [];
  if (source === 'exa' && !accountEditor) extraDisposers.push(await mountExaAdminEditor(root, api));
  // OAuth providers keep the normal key editor too (Firecrawl's API key stays editable).
  // Successful browser login refreshes the credential rows and the overview's login status.
  const oauthSlot = root.ownerDocument.createElement('div');
  const oauthBlock = await mountOAuthLogin(oauthSlot, api, {
    source: accountEditor ? undefined : source,
    label,
    pollInterval: oauthPollInterval,
    onComplete: async () => {
      await refresh();
      if (!disposed) onLogin?.();
    },
  });
  if (!oauthSlot.hidden) {
    root.prepend(oauthSlot);
    extraDisposers.push(oauthBlock);
  }
  if (!accountEditor) {
    const dashboardSlot = root.ownerDocument.createElement('div');
    const dashboard = await mountDashboardLogin(dashboardSlot, api, { source, onComplete: onLogin });
    if (!dashboardSlot.hidden) { root.prepend(dashboardSlot); extraDisposers.push(dashboard); }
  }
  return {
    dispose() {
      for (const extra of extraDisposers) extra.dispose();
      disposePage(root);
      disposed = true;
      generation += 1;
      revealed.clear();
      for (const input of root.querySelectorAll("input")) input.value = "";
      root.replaceChildren();
    },
  };
}


export function providerIdForSource(source) {
  return SOURCE_CATALOG.plugins.find(plugin => plugin.id === source
    || plugin.search_sources.includes(source) || plugin.scrape_channels.includes(source))?.id || source;
}

// Match Core's short SHA-256 identifier; raw values never enter account metadata or markup.
async function keyFingerprint(value) {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return `sha256:${[...new Uint8Array(digest)].slice(0, 4).map(byte => byte.toString(16).padStart(2, '0')).join('')}`;
}

/** @param {any} holder @param {any} api @param {any} options */
export async function mountProviderAccounts(holder, api, { source, onStatus, onTest, onLogin, onChange, initialAccounts = null }) {
  const root = pageRoot(holder), doc = root.ownerDocument;
  const provider = providerIdForSource(source);
  // Accounts come from a browser login or from pasted keys (the unassigned "default" group);
  // there is no empty account to create first. Login sits below the list as the way to add one.
  root.innerHTML = `<div class="provider-actions" data-account-tools></div><p class="provider-note" data-account-error role="alert"></p><div class="account-list" data-accounts></div><div class="account-add" data-provider-login></div>`;
  const errorSlot = root.querySelector('[data-account-error]');
  const list = root.querySelector('[data-accounts]');
  const tools = root.querySelector('[data-account-tools]');
  let disposed = false, busy = false, generation = 0;
  let editors = [];
  let oauth, dashboard;
  let editingDefault = false;
  const addAdmin = el(doc, 'button', { type: 'button', 'data-account-action': 'add-admin', hidden: '' }, '添加 Exa 管理 Key');
  tools.append(addAdmin);
  addAdmin.addEventListener('click', () => { editingDefault = true; void renderAccounts().catch(error => showError(errorSlot, error, '账号读取失败，请重新展开服务商。')); });
  function ready(result) {
    if (result.status !== 'ready') throw new Error(result.message || '账号操作未完成，请更新 CLI 后重试。');
    return result;
  }
  async function mutate(action) {
    if (busy || disposed) return;
    busy = true;
    errorSlot.textContent = '';
    for (const button of root.querySelectorAll('[data-account-action]')) button.setAttribute('disabled', '');
    try {
      ready(await action());
      if (!disposed) { await renderAccounts(); await onChange?.(); }
    } catch (error) { if (!disposed) showError(errorSlot, error, '账号操作失败，请重试。'); }
    finally {
      busy = false;
      if (!disposed) for (const button of root.querySelectorAll('[data-account-action]')) button.removeAttribute('disabled');
    }
  }
  async function refreshAfterKeyChange() {
    if (disposed) return;
    try { await renderAccounts(); await onChange?.(); }
    catch (error) { if (!disposed) showError(errorSlot, error, '凭据已更新，但账号刷新失败，请重新展开服务商。'); }
  }
  function nameForm(parent, account) {
    if (busy || disposed || parent.querySelector('.account-form')) return;
    const form = el(doc, 'form', { class: 'account-form' });
    form.innerHTML = `<label>账号名称<input required maxlength="120" data-account-name></label><button type="submit" data-account-action="save-name">保存名称</button><button type="button" data-action="cancel-name">取消</button>`;
    const input = form.querySelector('input');
    input.value = account?.name || '';
    parent.append(form); input.focus();
    form.querySelector('[data-action="cancel-name"]').addEventListener('click', () => form.remove());
    form.addEventListener('submit', event => {
      event.preventDefault();
      const name = input.value.trim();
      if (!name) { input.focus(); return; }
      void mutate(() => account ? api.accountsRename(provider, account.id, name) : api.accountsAdd(provider, name));
    });
  }
  function removeAccount(parent, account, trigger) {
    if (busy || parent.querySelector('[data-account-confirm]')) return;
    const panel = el(doc, 'div', { class: 'inline-confirm', 'data-account-confirm': '' });
    panel.innerHTML = `<p>删除账号时如何处理搜索 Key？仅查余额的凭据会保留。</p><div class="account-actions"><button type="button" data-account-action="keep-keys">删除账号，Key 移到默认账号</button><button type="button" class="danger" data-account-action="delete-keys">删除账号及搜索 Key</button><button type="button" data-action="cancel-account-remove">取消</button></div>`;
    parent.append(panel);
    const close = () => { panel.remove(); release(); };
    const release = confirmInline(panel, close, trigger);
    panel.querySelector('[data-action="cancel-account-remove"]').addEventListener('click', close);
    for (const [action, deleteKeys] of [['keep-keys', false], ['delete-keys', true]]) panel.querySelector(`[data-account-action="${action}"]`).addEventListener('click', () => {
      void mutate(() => api.accountsRemove(provider, account.id, deleteKeys));
    });
  }
  async function renderAccounts() {
    const ticket = ++generation;
    // The first render reuses the account groups the providers page already read; later renders re-read.
    const view = ticket === 1 && initialAccounts
      ? { status: 'ready', accounts: { [provider]: initialAccounts } }
      : ready(await api.accountsView(provider));
    if (disposed || ticket !== generation) return;
    for (const editor of editors) editor.dispose();
    editors = [];
    list.replaceChildren();
    tools.querySelector('.account-form')?.remove();
    const accounts = view.accounts[provider] || [];
    const shown = accounts.filter(account => account.id !== 'default' || account.keys.length
      || Object.keys(account.balance_credentials).length || accounts.length === 1 || editingDefault);
    addAdmin.hidden = source !== 'exa' || shown.some(account => account.id === 'default')
      || accounts.some(account => account.balance_credentials.exa_admin);
    // Browser-login accounts first; the pasted keys of the default group last.
    shown.sort((a, b) => Number(a.id === 'default') - Number(b.id === 'default'));
    for (const account of shown) {
      if (disposed || ticket !== generation) return;
      const row = el(doc, 'section', { class: 'account-row', 'data-account-id': account.id });
      const summary = el(doc, 'div', { class: 'account-summary' });
      const identity = el(doc, 'div', { class: 'account-identity' });
      const isDefault = account.id === 'default';
      identity.append(el(doc, 'h3', { class: 'account-name' }, isDefault ? '手动添加的 Key' : account.name),
        el(doc, 'p', { class: 'account-source' }, account.source === 'oauth' ? '浏览器登录' : isDefault ? '粘贴的 Key，可保存多条轮换使用' : '手动账号'));
      if (account.login_identity && account.login_identity !== account.name) {
        identity.append(el(doc, 'p', { class: 'account-source' }, account.login_identity));
      }
      const actions = el(doc, 'div', { class: 'account-actions' });
      summary.append(identity, el(doc, 'span', { class: 'provider-note' }, `${account.keys.length} 个 Key`), actions);
      row.append(summary); list.append(row);
      if (account.id !== 'default') {
        const rename = el(doc, 'button', { type: 'button', 'data-account-action': 'rename' }, '重命名账号');
        const remove = el(doc, 'button', { type: 'button', 'data-account-action': 'remove' }, '删除账号');
        actions.append(rename, remove);
        rename.addEventListener('click', () => nameForm(row, account));
        remove.addEventListener('click', () => removeAccount(row, account, remove));
      }
      if (account.source === 'oauth' && account.keys.length === 0) row.append(el(doc, 'p', { class: 'provider-note' }, '请为这个账号添加搜索 Key'));
      const keys = el(doc, 'div', { class: 'account-keys' }); row.append(keys);
      // The legacy row editor owns reveal/copy/drafts/confirmation and snapshot guards.
      // Scope its rows to fingerprints, resolving global indices only for an explicit action.
      let fingerprints = [...account.keys];
      let snapshot;
      const resolve = async (index, expected) => {
        const fingerprint = fingerprints[index];
        const fresh = ready(await api.accountsView(provider)).accounts[provider]?.find(item => item.id === account.id);
        if (!fingerprint || !fresh?.keys.includes(fingerprint)) throw new Error('Key 归属已变化，请刷新后重试。');
        const revealed = await api.credentialReveal(source);
        if (expected !== revealed.snapshot) throw new Error('凭据已变化，请刷新后重试。');
        const values = revealed.value.split('\n').filter(value => value.trim());
        const ids = await Promise.all(values.map(keyFingerprint));
        const globalIndex = ids.indexOf(fingerprint);
        if (globalIndex < 0) throw new Error('凭据已变化，请刷新后重试。');
        return { index: globalIndex, expected: revealed.snapshot, value: values[globalIndex] };
      };
      let environmentKey = false;
      const scopedApi = {
        ...api,
        credentialStatus: async () => {
          const view = await api.credentialStatus(source);
          onStatus?.(view);
          environmentKey = account.id === 'default' && view.effective_source === 'env';
          return { ...view, file_key_count: fingerprints.length, effective_source: environmentKey ? 'env' : fingerprints.length ? 'file' : 'none', env_var: environmentKey ? view.env_var : undefined };
        },
        credentialRead: async () => {
          const [saved, fresh] = await Promise.all([api.credentialRead(source), api.accountsView(provider)]);
          const current = ready(fresh).accounts[provider]?.find(item => item.id === account.id);
          if (!current) throw new Error('账号已变化，请重新展开服务商。');
          fingerprints = [...current.keys]; snapshot = saved.snapshot;
          return { value: fingerprints.join('\n'), snapshot };
        },
        credentialReveal: async () => {
          const values = await Promise.all(fingerprints.map((_, index) => resolve(index, snapshot)));
          return { value: values.map(item => item.value).join('\n'), snapshot };
        },
        credentialTest: async (_, selection) => {
          if (!selection) {
            if (!environmentKey) throw new Error('请为这个账号添加搜索 Key');
            return api.credentialTest(source);
          }
          const selected = await resolve(selection.index, selection.expected);
          return api.credentialTest(source, { index: selected.index, expected: selected.expected });
        },
        credentialRemove: async (_, index, expected) => {
          const selected = await resolve(index, expected);
          const result = await api.credentialRemove(source, selected.index, selected.expected);
          onStatus?.(result);
          await refreshAfterKeyChange();
          return result;
        },
        credentialAppend: async (_, values) => {
          const ids = await Promise.all(values.map(keyFingerprint));
          const result = await api.credentialAppend(source, values);
          onStatus?.(result);
          // Append already succeeded: an assignment failure must not invite duplicate retries.
          try {
            if (account.id !== 'default') for (const fingerprint of ids) ready(await api.accountsMoveKey(provider, fingerprint, account.id));
          } catch (error) {
            if (!disposed) {
              showError(errorSlot, error, '请刷新后整理账号。');
              errorSlot.prepend(doc.createTextNode('Key 已保存，但部分 Key 的账号归属更新失败。'));
            }
          }
          await refreshAfterKeyChange();
          return result;
        },
      };
      const editor = await mountCredentialBody(keys, scopedApi, { source, accountEditor: true, onTest });
      if (disposed || ticket !== generation) { editor.dispose(); return; }
      editors.push(editor);
      for (const [entry, fingerprint] of Object.entries(account.balance_credentials)) {
        const credential = el(doc, 'div', { class: 'key-row' });
        const name = entry === 'parallel_account' ? 'Parallel 账户令牌' : entry === 'exa_admin' ? 'Exa 余额凭据' : entry === 'brave_dashboard' ? 'Brave 控制台登录' : entry;
        const label = el(doc, 'div', { class: 'key-identity' });
        label.append(el(doc, 'strong', { class: 'key-kind' }, `${name} · 仅查余额`), el(doc, 'p', { class: 'key-fingerprint' }, String(fingerprint)));
        credential.append(label); keys.append(credential);
      }
      // A new Exa management key belongs to default until the account API assigns it.
      if (source === 'exa' && (account.balance_credentials.exa_admin || (account.id === 'default'
        && !accounts.some(item => item.balance_credentials.exa_admin)))) {
        row.append(el(doc, 'p', { class: 'provider-note' }, 'Exa 管理 Key · 仅查余额。新增管理 Key 保存在默认账号。'));
        const admin = await mountExaAdminEditor(row, api);
        if (disposed || ticket !== generation) { admin.dispose(); return; }
        editors.push(admin);
      }
    }
  }
  try { await renderAccounts(); }
  catch (error) { if (!disposed) showError(errorSlot, error, '账号读取失败，请重新展开服务商。'); }
  if (!disposed) {
    const loginRoot = root.querySelector('[data-provider-login]');
    const oauthSlot = el(doc, 'div'), dashboardSlot = el(doc, 'div');
    loginRoot.append(oauthSlot, dashboardSlot);
    const onComplete = async () => { if (!disposed) { await renderAccounts(); await onChange?.(); onLogin?.(); } };
    oauth = await mountOAuthLogin(oauthSlot, api, { source, label: sourceEntry(source).label, onComplete });
    dashboard = await mountDashboardLogin(dashboardSlot, api, { source, onComplete });
  }
  return { dispose() { disposed = true; generation += 1; oauth?.dispose(); dashboard?.dispose(); for (const editor of editors) editor.dispose(); disposePage(root); root.replaceChildren(); } };
}
