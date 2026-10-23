// Canonical UI search source list is provided by the desktop at runtime via
// `api.providerList()`. The list below is populated by `initProviders` the first
// time a page mounts; module-level `SOURCES` is a live binding that consumers
// should treat as "resolved only after an `await initProviders(api)` call".
// This keeps the desktop `provider::PROVIDERS` table as the single source of truth.

let SOURCES = [];
let PROVIDERS = [];
export const scrapeCredentialProviders = () => PROVIDERS.filter(row => row.search === false && row.keyed);
export { SOURCES };
let providerLoad = null;

/// Fetch the provider manifest from Rust once per page mount. Subsequent calls
/// reuse the in-flight promise so multiple pages share a single round trip.
/// `SOURCES` is replaced atomically; readers see either the previous list or
/// the new list, never a partial row.
export function initProviders(api) {
  if (!providerLoad) {
    providerLoad = Promise.resolve()
      .then(() => api.providerList())
      .then(rows => {
        // Internally the UI uses the canonical `source` (underscore form, e.g.
        // `github_repos`). The Rust resolver accepts both spellings, so IPC
        // calls below pass `source` directly.
        PROVIDERS = rows.map(row => ({
          search: row.search,
          cliSource: row.cliSource,
          source: row.source,
          label: row.label,
          keyed: row.keyed,
          cookie: row.cookie,
          aliases: row.aliases || [],
        }));
        SOURCES = PROVIDERS.filter(row => row.search !== false);
        return SOURCES;
      })
      .catch(error => {
        // Keep the failure visible: leave SOURCES empty so downstream rows never
        // render, and rethrow so callers can show the minimal error state.
        SOURCES = [];
        PROVIDERS = [];
        throw error;
      });
  }
  return providerLoad;
}

/// Sync access for code paths that run after `initProviders` has resolved.
/// Returns the same array; callers must not mutate it.
export function providerList() {
  return SOURCES;
}

const DEFAULT_SOURCE = 'tavily';
const storeLabels = { present: '已保存', absent: '未保存', unavailable: '数据库不可用', unreadable: '已保存条目无法读取' };
const sourceEntry = source => PROVIDERS.find(item => item.source === source || item.cliSource === source) || SOURCES.find(item => item.source === DEFAULT_SOURCE) || { source, label: source, keyed: true };
const provenance = value => JSON.stringify([value.effective_source, value.store?.state, value.store?.saved_at]);
export async function mountCredentials(root, api, options = {}) {
  await initProviders(api);
  const entry = sourceEntry(options.source);
  root.innerHTML = `<section class="heading"><p class="eyebrow">CREDENTIALS / ${entry.source}</p><h1>${entry.label} 凭据。</h1><p>Key 在编辑区直接可见，以 Windows 当前用户 DPAPI 加密保存在 SQLite。旧来源不会自动生效。</p></section>`;
  const holder = root.ownerDocument.createElement('div'); root.append(holder);
  return mountCredentialBody(holder, api, options);
}
export async function mountCredentialBody(root, api, { source = DEFAULT_SOURCE, onStatus, onTest } = {}) {
  await initProviders(api);
  const { label, search } = sourceEntry(source);
  const searchTest = search !== false;
  root.innerHTML = `<div class="credential-editor"><div class="credential-fields">
    <p class="credential-note">${label} API Key：已保存的每行一条；下方逐行输入新增 Key，一次粘贴一行。删除为单行操作。</p>
    <div data-saved-list class="key-saved-list"></div>
    <p data-saved-empty class="credential-note key-saved-empty" hidden>当前没有已保存的 Key。</p>
    <form data-save-form>
      <div data-draft-list class="key-draft-list"></div>
      <div class="run-controls draft-controls"><button type="button" data-action="add" aria-label="新增一行 Key 输入">＋</button>
      <button type="submit" class="primary" data-action="save">提交新增 Key</button><button type="button" data-action="test">测试连接</button><button type="button" data-action="application" disabled>获取 API Key</button>
      <span class="credential-note" data-info="application">申请链接待配置</span></div>
    </form>
    <p class="credential-note">Key 仅保存在本机 SQLite，DPAPI 保护范围为当前 Windows 用户/设备。保存不会发起搜索；环境变量与旧文件不会自动生效，也不作为配置来源。未修改的 Key 保留 exhausted 等已有元数据。</p>
    <dl class="cred-status"><dt>已保存</dt><dd data-status="store"></dd><dt>生效来源</dt><dd data-status="source"></dd></dl>
    <p data-info="error" role="alert"></p>
    <div class="credential-tools"><button type="button" data-action="refresh">刷新已保存值</button></div></div>
    <div class="credential-feedback"><div class="test-result" data-test-result data-kind="idle"><span class="result-symbol" aria-hidden="true"></span><div><strong data-status="test" aria-live="polite">尚未测试</strong><p data-info="test" role="status"></p></div></div>
    <p class="credential-note">${searchTest ? `测试会向 ${label} 发送外部搜索请求，可能消耗额度。测试使用已保存的值；新增后请先提交。` : '仅用于网页抓取，不提供搜索连接测试。保存 Key 不会发起外部请求。新增 Key 视为新条目，删除一行即移除该条目。'}</p></div></div>`;
  const q = selector => root.querySelector(selector);
  const text = (selector, value) => { q(selector).textContent = value; };
  let current = { store: { state: 'absent', error: '' }, effective_source: 'none' };
  let generation = 0, disposed = false, busy = false;
  /** @type {string[]} rows last confirmed by credentialRead */
  let savedRows = [];
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
  function setBusy(value) {
    busy = value;
    for (const button of root.querySelectorAll('button')) button.disabled = value;
    for (const input of root.querySelectorAll('[data-draft-list] input')) input.disabled = value || !readHealthy;
    for (const input of root.querySelectorAll('[data-saved-list] input')) input.disabled = value;
    q('[data-action="application"]').disabled = value || !current.key_application_available;
    q('[data-action="test"]').disabled = value || !searchTest;
    q('[data-action="test"]').hidden = !searchTest;
    // Saved-row delete and draft add/submit are mutations; keep them disabled
    // until a successful read anchors the remove guard.
    for (const button of root.querySelectorAll('[data-action="remove"], [data-action="remove-draft"], [data-action="add"], [data-action="save"]')) button.disabled = value || !readHealthy;
  }
  function renderSaved() {
    const list = q('[data-saved-list]');
    list.innerHTML = '';
    q('[data-saved-empty]').hidden = savedRows.length > 0;
    savedRows.forEach((value, index) => {
      const row = root.ownerDocument.createElement('div');
      row.className = 'key-saved-row'; row.dataset.savedIndex = String(index);
      row.innerHTML = `<label>Key ${index + 1}<input type="text" readonly data-saved-input aria-label="已保存 Key 第 ${index + 1} 行"></label>
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
      input.addEventListener('input', () => { drafts[index] = input.value; invalidateTest(); });
      // A pasted newline is refused rather than silently merged into one key.
      input.addEventListener('paste', event => {
        const pasted = event.clipboardData?.getData('text') || '';
        if (/[\r\n]/.test(pasted)) { event.preventDefault(); text('[data-info="error"]', '每行一条 Key：多行内容请拆分后逐行粘贴。'); }
      });
      row.querySelector('[data-action="remove-draft"]').addEventListener('click', () => {
        if (busy || !readHealthy || disposed) return;
        if (drafts.length === 1) { drafts[0] = ''; } else drafts.splice(index, 1);
        renderDrafts();
      });
      list.append(row);
    });
    setBusy(busy);
  }
  function render(view) {
    if (disposed) return;
    if (provenance(current) !== provenance(view)) invalidateTest();
    current = view; onStatus?.(view);
    text('[data-status="store"]', storeLabels[view.store.state] || view.store.state);
    text('[data-status="source"]', view.effective_source === 'sqlite' ? 'SQLite / DPAPI' : view.effective_source === 'none' ? '未配置' : '不可用');
    text('[data-info="application"]', view.key_application_available ? '使用系统浏览器打开固定申请链接' : '申请链接待配置');
    q('[data-action="application"]').disabled = busy || !view.key_application_available;
  }
  async function readBack() {
    const saved = await api.credentialRead(source);
    if (disposed) return;
    readSnapshot = saved.value;
    savedRows = saved.value.split('\n').filter(line => line.trim() !== '');
    readHealthy = true;
    renderSaved();
  }
  async function refresh() {
    setBusy(true);
    try {
      render(await api.credentialStatus(source));
      await readBack();
      if (readHealthy && !disposed) text('[data-info="error"]', current.store.error || '');
    } catch (error) {
      if (!disposed) {
        readHealthy = false;
        // Keep the last saved rows visible so the user can still see state; all
        // writes stay disabled until a refresh succeeds again.
        renderSaved();
        text('[data-info="error"]', typeof error === 'string' ? error : '无法读取已保存凭据，请重试。');
      }
    }
    finally { if (!disposed) setBusy(false); }
  }
  q('[data-save-form]').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !readHealthy || disposed) return;
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
    } catch (error) { if (!disposed) text('[data-info="error"]', typeof error === 'string' ? error : '保存失败，编辑值已保留。'); }
    finally { if (!disposed) setBusy(false); }
  });
  q('[data-action="add"]').addEventListener('click', () => {
    if (busy || !readHealthy || disposed) return;
    drafts.push(''); renderDrafts();
    const inputs = q('[data-draft-list]').querySelectorAll('input');
    inputs[inputs.length - 1]?.focus();
  });
  q('[data-saved-list]').addEventListener('click', event => {
    const button = event.target.closest('[data-action="remove"]');
    if (!button) return;
    if (busy || !readHealthy || disposed) return;
    const index = Number(button.dataset.removeIndex);
    const row = button.closest('[data-saved-index]');
    const slot = row.querySelector('[data-confirm-slot]');
    if (slot.firstElementChild) return;
    const panel = root.ownerDocument.createElement('div');
    panel.className = 'inline-confirm'; panel.dataset.confirm = 'remove';
    panel.innerHTML = `<p class="note">确定删除第 ${index + 1} 行已保存的 Key 吗？删除后旧文件、凭据库及环境变量不会自动恢复生效。</p><div class="run-controls"><button type="button" class="danger" data-action="confirm-remove">确认删除</button><button type="button" data-action="cancel-remove">取消</button></div>`;
    slot.append(panel);
    panel.querySelector('[data-action="cancel-remove"]').addEventListener('click', () => panel.remove());
    panel.querySelector('[data-action="confirm-remove"]').addEventListener('click', async () => {
      if (busy || !readHealthy || disposed) return;
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
        if (!disposed) { panel.remove(); text('[data-info="error"]', typeof error === 'string' ? error : '删除失败，已保存值未变。'); }
      } finally { if (!disposed) setBusy(false); }
    });
  });
  q('[data-action="application"]').addEventListener('click', async () => {
    try { await api.credentialApplicationOpen(source); }
    catch (error) { if (!disposed) text('[data-info="error"]', typeof error === 'string' ? error : '无法打开系统浏览器。'); }
  });
  q('[data-action="test"]').addEventListener('click', async () => {
    if (!searchTest) return;
    setBusy(true); const testedGeneration = ++generation; reportTest('running', '正在测试');
    try { const outcome = await api.credentialTest(source, null); if (testedGeneration === generation && !disposed) reportTest(outcome.result === 'success' ? 'success' : 'error', outcome.result === 'success' ? '测试成功' : '测试失败', outcome.message || ''); }
    catch (error) { if (testedGeneration === generation && !disposed) reportTest('error', '测试失败', typeof error === 'string' ? error : '请检查 CLI 后重试。'); }
    finally { if (!disposed) setBusy(false); }
  });
  q('[data-action="refresh"]').addEventListener('click', refresh);
  renderDrafts();
  await refresh();
  return { dispose() { disposed = true; generation += 1; } };
}
