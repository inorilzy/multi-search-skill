import { pageRoot, confirmInline, disposePage } from './dom.js';
import { showError } from './api.js';
import { SEARCH_SOURCES } from './catalog.js';
import { SOURCE_CATALOG } from './source-catalog.js';

// Search sources come from the catalog generated from Python core metadata (one source of truth for
// the CLI and this UI). Scraper-only providers also live there: they have credentials but no search
// endpoint, so they get a credential panel without a connectivity test.
export const SOURCES = SEARCH_SOURCES.map(({ name, label, keyed, cookie, description, mark }) => ({
  source: name,
  label,
  keyed,
  cookie,
  description,
  mark,
}));

const SCRAPE_PROVIDERS = SOURCE_CATALOG.sources
  .filter(entry => entry.searchable === false && entry.keyed === true)
  .map(entry => ({ source: entry.name, label: entry.label, keyed: true, cookie: entry.cookie, search: false }));

/// Scraper-only providers that own credentials (no search test). Today the catalog has none, so the
/// section is simply absent instead of hardcoding a provider list.
export function scrapeCredentialProviders() {
  return SCRAPE_PROVIDERS;
}

const DEFAULT_SOURCE = 'tavily';
const storeLabels = { present: '已保存', absent: '未保存', unavailable: '数据库不可用', unreadable: '已保存条目无法读取' };
// Backend-reported capability only: a browser platform string or a failed save
// never decides this. The wire reason is `platform_unsupported`
// (credential::PLATFORM_UNSUPPORTED_REASON); any unrecognized reason falls back
// to the same honest text rather than a second near-identical copy.
const CAPABILITY_TEXT = {
  platform_unsupported: '加密凭据存储仅支持 Windows 当前用户 DPAPI。当前平台不支持该操作：可以查看生效来源并运行允许的连接测试，但无法创建、修改或显示已保存的 Key。',
};
const capabilityText = reason => CAPABILITY_TEXT[reason] || CAPABILITY_TEXT.platform_unsupported;
// Shown while a capability query is in flight or after it failed: writes stay
// off and the user gets a retry entry instead of a guessed platform answer.
const CAPABILITY_PENDING = '正在确认当前平台是否支持加密凭据存储…';
const CAPABILITY_FAILED = '无法确认当前平台是否支持加密凭据存储。可以查看生效来源，但保存、删除和显示 Key 不可用；请点击"刷新已保存值"重试。';

// The effective source after the SQLite/DPAPI merge. Unknown future values stay labelled.
function sourceText(overview) {
  // Core's doctor report may name the provenance it actually resolved (types.d.ts:
  // env | credential_store | file | none | unavailable, or sqlite when only the store is known).
  if (overview.effective_source === 'env') return overview.env_var ? `环境变量 ${overview.env_var}` : '环境变量';
  if (overview.effective_source === 'credential_store') return '本机凭据库';
  if (overview.effective_source === 'file') {
    return overview.file_key_count ? `旧 Key 文件中的 ${overview.file_key_count} 个 Key` : '旧 Key 文件';
  }
  if (overview.effective_source === 'sqlite') return 'SQLite / DPAPI';
  if (overview.effective_source === 'none') return '未配置';
  if (overview.effective_source === 'unavailable') return '不可用';
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
    credential_store: '凭据库错误：无法读取这个来源的 Key，请重新保存。',
    network: `网络错误：无法连接 ${label}。`,
    timeout: '超时：请稍后重试。',
    error: '测试失败：请查看 CLI 输出。',
    cli_failed: 'CLI 未返回有效结果。',
  };
  return labels[result] || '测试失败';
}
/** @typedef {{ source: string, label: string, keyed: boolean, cookie?: boolean, search?: boolean }} CredentialEntry */
/** @param {string} source @returns {CredentialEntry} */
const sourceEntry = source => SOURCES.find(item => item.source === source)
  || SCRAPE_PROVIDERS.find(item => item.source === source)
  || SOURCES.find(item => item.source === DEFAULT_SOURCE)
  || { source, label: source, keyed: true, search: true };
const provenance = value => JSON.stringify([value.effective_source, value.store?.state, value.store?.saved_at]);
/** @param {HTMLElement} root @param {any} api @param {{ number?: string, source?: string, onStatus?: (view: any) => void, onTest?: (result: any) => void }} [options] */
export async function mountCredentials(root, api, options = {}) {
  root = pageRoot(root);
  const { number = '04', ...pageOptions } = options;
  const entry = sourceEntry(pageOptions.source);
  root.innerHTML = `<section class="heading"><p class="eyebrow">${number} / CREDENTIALS</p><h1 tabindex="-1">凭据</h1><p>Key 默认掩码显示，以当前系统用户的 DPAPI 加密保存在本机 SQLite。生效来源按 Core 的优先级判定：环境变量 > 凭据库 > 旧 Key 文件。</p></section>`;
  root.querySelector('h1').textContent = `${entry.label} 凭据`;
  const holder = root.ownerDocument.createElement('div'); root.append(holder);
  return mountCredentialBody(holder, api, pageOptions);
}
/** @param {any} root @param {any} api @param {{source?: string, onStatus?: (view: any) => void, onTest?: (result: any) => void}} [options] */
export async function mountCredentialBody(root, api, { source = DEFAULT_SOURCE, onStatus, onTest } = {}) {
  root = pageRoot(root);
  const { label, search } = sourceEntry(source);
  const searchTest = search !== false;
  root.innerHTML = `<div class="credential-editor"><div class="credential-fields">
    <p class="credential-note">API Key：已保存的每行一条；下方逐行输入新增 Key，一次粘贴一行。删除为单行操作。</p>
    <div data-saved-list class="key-saved-list"></div>
    <p data-saved-empty class="credential-note key-saved-empty" hidden>当前没有已保存的 Key。</p>
    <form data-save-form>
      <div data-draft-list class="key-draft-list"></div>
      <div class="run-controls draft-controls"><button type="button" data-action="add" aria-label="新增一行 Key 输入">＋</button>
      <button type="submit" class="primary" data-action="save">提交新增 Key</button><button type="button" data-action="test">测试连接</button><button type="button" data-action="application" disabled>获取 API Key</button>
      <span class="credential-note" data-info="application">申请链接待配置</span></div>
    </form>
    <details class="config-details"><summary>说明</summary><p class="credential-note">Key 仅保存在本机 SQLite，DPAPI 保护范围为当前 Windows 用户/设备。保存不会发起搜索。生效来源按 Core 的优先级判定：环境变量 > 凭据库 > 旧 Key 文件。未修改的 Key 保留 exhausted 等已有元数据。</p></details>
    <p data-capability class="credential-note" role="note" hidden></p>
    <dl class="cred-status"><dt>已保存</dt><dd class="status-text" data-status="store"></dd><dt>生效来源</dt><dd class="status-text" data-status="source"></dd></dl>
    <p data-info="error" class="error-message"></p>
    <div class="credential-tools"><button type="button" data-action="refresh">刷新已保存值</button></div></div>
    <div class="credential-feedback"><div class="test-result" data-test-result data-kind="idle"><span class="result-symbol" aria-hidden="true"></span><div><strong class="status-text" data-status="test" aria-live="polite">尚未测试</strong><p data-info="test" role="status"></p></div></div>
    <details class="config-details"><summary>说明</summary><p class="credential-note">${searchTest ? `测试会向对应服务发送外部搜索请求，可能消耗额度。测试使用已保存的值；新增后请先提交。` : '仅用于网页抓取，不提供搜索连接测试。保存 Key 不会发起外部请求。新增 Key 视为新条目，删除一行即移除该条目。'}</p></details></div></div>`;
  root.querySelector('.credential-note').prepend(root.ownerDocument.createTextNode(`${label} `));
  const q = selector => /** @type {any} */ (root.querySelector(selector));
  const text = (selector, value) => { q(selector).textContent = value; };
  let current = { store: { state: 'absent', error: '' }, effective_source: 'none' };
  let generation = 0, disposed = false, busy = false;
  // Storage capability is unknown until credentialStatus reports it: all writes stay
  // disabled rather than presenting an uncertain state as permission to save.
  // `capability.phase`: 'pending' (first/re-query in flight) | 'ok' | 'failed'.
  let capability = { supported: null, reason: '', phase: 'pending' };
  // Monotonic refresh guard: only the latest refresh may publish capability or
  // rows. A slower older response must never overwrite a newer outcome.
  let refreshGeneration = 0;
  /** @type {string[]} rows last confirmed by credentialRead */
  let savedRows = [];
  const revealed = new Map();
  /** @type {string|null} snapshot used as remove guard */
  let readSnapshot = null;
  let readHealthy = false;
  /** @type {string[]} draft input values; index aligned with draft rows */
  let drafts = [''];
  function reportTest(kind, title, message = '') {
    if (disposed) return;
    text('[data-status="test"]', title); text('[data-info="test"]', message);
    q('[data-test-result]').dataset.kind = kind; onTest?.({ kind, title, message });
  }
  function invalidateTest() { generation += 1; reportTest('idle', '尚未测试'); }
  // Capability-confirmed encrypted operation check, shared by reveals and
  // mutations so the unsupported judgement lives in one place.
  const capabilityReady = () => capability.supported === true;
  // Every encrypted mutation additionally requires a successful row read so
  // the remove guard has a live snapshot to check.
  const writesReady = () => readHealthy && capabilityReady();
  function setBusy(value) {
    busy = value;
    root.setAttribute('aria-busy', String(value)); root.classList.toggle('is-busy', value);
    for (const button of root.querySelectorAll('button')) button.disabled = value;
    for (const input of root.querySelectorAll('[data-draft-list] input')) input.disabled = value || !writesReady();
    for (const input of root.querySelectorAll('[data-saved-list] input')) input.disabled = value;
    for (const button of root.querySelectorAll('[data-action="copy"]')) button.disabled = value || !revealed.has(Number(button.dataset.rowIndex));
    // Plaintext reveal is an encrypted read; unsupported platforms cannot run it.
    for (const button of root.querySelectorAll('[data-action="reveal"]')) button.disabled = value || !capabilityReady();
    q('[data-action="application"]').disabled = value || !current.key_application_available;
    q('[data-action="test"]').disabled = value || !searchTest;
    q('[data-action="test"]').hidden = !searchTest;
    // Saved-row delete and draft add/submit are mutations; keep them disabled
    // until a successful read anchors the remove guard AND the backend reports
    // a supported platform.
    for (const button of root.querySelectorAll('[data-action="remove"], [data-action="remove-draft"], [data-action="add"], [data-action="save"]')) button.disabled = value || !writesReady();
  }
  function renderCapability() {
    const banner = q('[data-capability]');
    if (capability.supported === true) { banner.hidden = true; banner.textContent = ''; return; }
    banner.hidden = false;
    banner.textContent = capability.phase === 'pending' ? CAPABILITY_PENDING
      : capability.phase === 'failed' ? CAPABILITY_FAILED
      : capabilityText(capability.reason);
  }
  function renderSaved() {
    const list = q('[data-saved-list]');
    list.innerHTML = '';
    q('[data-saved-empty]').hidden = savedRows.length > 0;
    savedRows.forEach((value, index) => {
      const row = root.ownerDocument.createElement('div');
      row.className = 'key-saved-row'; row.dataset.savedIndex = String(index);
      row.innerHTML = `<label>Key ${index + 1}<input type="password" readonly data-saved-input aria-label="已保存 Key 第 ${index + 1} 行"></label>
        <button type="button" data-action="reveal" data-row-index="${index}">显示</button><button type="button" data-action="copy" data-row-index="${index}" disabled>复制</button>
        <button type="button" data-action="remove" data-remove-index="${index}" aria-label="删除第 ${index + 1} 行 Key">删除</button>
        <div data-confirm-slot></div>`;
      // Saved value is assigned via .value, never innerHTML, so raw key text
      // cannot break the markup.
      row.querySelector('input').value = value;
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
      row.innerHTML = `<label>新增 Key ${index + 1}<input type="text" data-field="key" data-draft-input autocomplete="off" spellcheck="false" aria-label="新增 Key 第 ${index + 1} 行" placeholder="输入一条 Key"></label>
        <button type="button" data-action="remove-draft" aria-label="移除该输入行">×</button>`;
      const input = row.querySelector('input');
      input.value = value;
      list.append(row);
    });
    setBusy(busy);
  }
  function render(view) {
    if (disposed) return;
    if (provenance(current) !== provenance(view)) invalidateTest();
    current = view; onStatus?.(view);
    // The backend is authoritative: absent/false means unsupported, not "Key 未配置".
    capability = { supported: view.store_supported === true, reason: view.store_supported === true ? '' : (view.store_unsupported_reason || 'platform_unsupported'), phase: 'ok' };
    renderCapability();
    setBusy(busy);
    text('[data-status="store"]', storeLabels[view.store.state] || view.store.state);
    text('[data-status="source"]', sourceText(view));
    text('[data-info="application"]', view.key_application_available ? '使用系统浏览器打开固定申请链接' : '申请链接待配置');
    q('[data-action="application"]').disabled = busy || !view.key_application_available;
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
    // A newer refresh supersedes this one: only it may publish capability or
    // rows, so a slower older response cannot overwrite a newer outcome.
    const requestId = ++refreshGeneration;
    capability = { supported: null, reason: '', phase: 'pending' };
    renderCapability();
    setBusy(true);
    try {
      const view = await api.credentialStatus(source);
      if (disposed || requestId !== refreshGeneration) return;
      render(view);
      // Capability is known now (even if it is "unsupported"); only the row
      // read can still fail below. Keep that distinct so a read failure is not
      // misreported as "capability unconfirmed".
      try {
        await readBack(requestId);
        if (disposed || requestId !== refreshGeneration) return;
        if (readHealthy) text('[data-info="error"]', current.store.error || '');
      } catch (readError) {
        if (!disposed && requestId === refreshGeneration) {
          readHealthy = false;
          // Rows could not be read but capability already arrived; the banner
          // keeps its status-based message and the error slot gets the read
          // reason. Writes stay off until a refresh read succeeds again.
          renderSaved();
          showError(q('[data-info="error"]'), readError, '无法读取已保存凭据，请重试。');
        }
      }
    } catch (error) {
      if (!disposed && requestId === refreshGeneration) {
        readHealthy = false;
        // Capability is unknown again: writes stay disabled until a status
        // succeeds, so a failed lookup is never an empty, writable store.
        capability = { supported: null, reason: '', phase: 'failed' };
        renderCapability();
        // Keep the last saved rows visible so the user can still see state; all
        // writes stay disabled until a refresh succeeds again.
        renderSaved();
        showError(q('[data-info="error"]'), error, '无法确认凭据能力，请重试。');
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
    if (drafts.length === 1) drafts[0] = ''; else drafts.splice(index, 1);
    renderDrafts();
  });
  q('[data-saved-list]').addEventListener('click', async event => {
    const button = event.target.closest('[data-action="reveal"], [data-action="copy"]');
    if (!button || busy || disposed) return;
    // Guard the action itself too: a synthesized click on an enabled row must
    // still not issue an encrypted read on an unsupported platform.
    if (button.dataset.action === 'reveal' && !capabilityReady()) return;
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
    if (!capabilityReady()) return;
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
      drafts = [''];
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
    panel.innerHTML = `<p class="note">确定删除第 ${index + 1} 行已保存的 Key 吗？删除后旧文件、凭据库及环境变量不会自动恢复生效。</p><div class="run-controls"><button type="button" class="danger" data-action="confirm-remove">确认删除</button><button type="button" data-action="cancel-remove">取消</button></div>`;
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
    try { await api.credentialApplicationOpen(source); }
    catch (error) { if (!disposed) showError(q('[data-info="error"]'), error, '无法打开系统浏览器。'); }
  });
  q('[data-action="test"]').addEventListener('click', async () => {
    if (!searchTest) return;
    setBusy(true); const testedGeneration = ++generation; const testedSource = sourceText(current); reportTest('running', '正在测试');
    try {
      const outcome = await api.credentialTest(source);
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
  q('[data-action="refresh"]').addEventListener('click', refresh);
  renderDrafts();
  await refresh();
  return { dispose() { disposePage(root); disposed = true; generation += 1; revealed.clear(); for (const input of root.querySelectorAll("input")) input.value = ""; root.replaceChildren(); } };
}
