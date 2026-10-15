// Canonical UI search sources. Keys live only in config.sqlite, encrypted with current-user DPAPI.
export const SOURCES = [
  { source: 'baidu', label: 'Baidu AI 搜索', keyed: true },
  { source: 'brave', label: 'Brave 搜索', keyed: true },
  { source: 'parallel', label: 'Parallel', keyed: true },
  { source: 'tavily', label: 'Tavily', keyed: true },
  { source: 'exa', label: 'Exa', keyed: true },
  { source: 'firecrawl', label: 'Firecrawl', keyed: true },
  { source: 'serpapi', label: 'SerpAPI', keyed: true },
  { source: 'github_repos', label: 'GitHub 仓库', keyed: true },
  { source: 'hackernews', label: 'Hacker News', keyed: false },
  { source: 'stackoverflow', label: 'Stack Overflow', keyed: false },
  { source: 'sov2ex', label: 'V2EX', keyed: false },
  { source: 'twitter', label: 'Twitter / X', keyed: false, cookie: true },
];
const DEFAULT_SOURCE = 'tavily';
const storeLabels = { present: '已保存', absent: '未保存', unavailable: '数据库不可用', unreadable: '已保存条目无法读取' };
const sourceEntry = source => SOURCES.find(item => item.source === source) || SOURCES.find(item => item.source === DEFAULT_SOURCE);
const provenance = value => JSON.stringify([value.effective_source, value.store?.state, value.store?.saved_at]);
export async function mountCredentials(root, api, options = {}) {
  const entry = sourceEntry(options.source);
  root.innerHTML = `<section class="heading"><p class="eyebrow">CREDENTIALS / ${entry.source}</p><h1>${entry.label} 凭据。</h1><p>Key 在编辑区直接可见，以 Windows 当前用户 DPAPI 加密保存在 SQLite。旧来源不会自动生效。</p></section>`;
  const holder = root.ownerDocument.createElement('div'); root.append(holder);
  return mountCredentialBody(holder, api, options);
}
export async function mountCredentialBody(root, api, { source = DEFAULT_SOURCE, onStatus, onTest } = {}) {
  const { label } = sourceEntry(source);
  root.innerHTML = `<div class="credential-editor"><div class="credential-fields"><form data-save-form>
    <label>${label} API Key（多 Key 一行一个）<span class="key-input"><textarea data-field="key" autocomplete="off" spellcheck="false" rows="2" placeholder="输入 Key，多 Key 一行一个"></textarea></span></label>
    <button type="submit" class="primary" data-action="save">保存 Key</button><button type="button" data-action="test">测试连接</button><button type="button" data-action="application" disabled>获取 API Key</button>
    <span class="credential-note" data-info="application">申请链接待配置</span></form>
    <p class="credential-note">Key 仅保存在本机 SQLite，DPAPI 保护范围为当前 Windows 用户/设备。保存不会发起搜索；环境变量与旧文件不会自动生效，也不作为配置来源。</p>
    <dl class="cred-status"><dt>已保存</dt><dd data-status="store"></dd><dt>生效来源</dt><dd data-status="source"></dd></dl>
    <p data-info="override" class="note" role="status"></p><p data-info="error" role="alert"></p>
    <div class="credential-tools"><button type="button" data-action="refresh">刷新已保存值</button><div data-delete-slot><button type="button" data-action="delete">删除已保存的 key</button></div></div></div>
    <div class="credential-feedback"><div class="test-result" data-test-result data-kind="idle"><span class="result-symbol" aria-hidden="true"></span><div><strong data-status="test" aria-live="polite">尚未测试</strong><p data-info="test" role="status"></p></div></div>
    <p class="credential-note">测试会向 ${label} 发送外部搜索请求，可能消耗额度。测试使用已保存的值；编辑后请先保存。</p></div></div>`;
  const q = selector => root.querySelector(selector);
  const text = (selector, value) => { q(selector).textContent = value; };
  const field = q('[data-field="key"]');
  let current = { store: { state: 'absent', error: '' }, effective_source: 'none' };
  let generation = 0, disposed = false, busy = false;
  function reportTest(kind, title, message = '') {
    if (disposed) return;
    text('[data-status="test"]', title); text('[data-info="test"]', message);
    q('[data-test-result]').dataset.kind = kind; onTest?.({ kind, title, message });
  }
  function invalidateTest() { generation += 1; reportTest('idle', '尚未测试'); }
  function setBusy(value) {
    busy = value;
    for (const button of root.querySelectorAll('button')) button.disabled = value;
    field.disabled = value;
    q('[data-action="application"]').disabled = value || !current.key_application_available;
  }
  function render(view) {
    if (disposed) return;
    if (provenance(current) !== provenance(view)) invalidateTest();
    current = view; onStatus?.(view);
    text('[data-status="store"]', storeLabels[view.store.state] || view.store.state);
    text('[data-status="source"]', view.effective_source === 'sqlite' ? 'SQLite / DPAPI' : view.effective_source === 'none' ? '未配置' : '不可用');
    text('[data-info="error"]', view.store.error || '');
    text('[data-info="application"]', view.key_application_available ? '使用系统浏览器打开固定申请链接' : '申请链接待配置');
    q('[data-action="application"]').disabled = busy || !view.key_application_available;
  }
  async function refresh() {
    setBusy(true);
    try {
      render(await api.credentialStatus(source));
      const saved = await api.credentialRead(source);
      if (!disposed) field.value = saved.value;
    } catch (error) { if (!disposed) text('[data-info="error"]', typeof error === 'string' ? error : '无法读取已保存凭据，请重试。'); }
    finally { if (!disposed) setBusy(false); }
  }
  field.addEventListener('input', invalidateTest);
  q('[data-save-form]').addEventListener('submit', async event => {
    event.preventDefault(); const edited = field.value; invalidateTest(); setBusy(true);
    try {
      render(await api.credentialSave(source, edited));
      const saved = await api.credentialRead(source);
      if (!disposed) { field.value = saved.value; text('[data-info="test"]', '已保存。尚未测试。'); }
    } catch (error) { if (!disposed) { field.value = edited; text('[data-info="error"]', typeof error === 'string' ? error : '保存失败，编辑值已保留。'); } }
    finally { if (!disposed) setBusy(false); }
  });
  const closeDelete = () => q('[data-confirm="delete"]')?.remove();
  q('[data-action="delete"]').addEventListener('click', () => {
    if (q('[data-confirm="delete"]')) return;
    const panel = root.ownerDocument.createElement('div'); panel.dataset.confirm = 'delete';
    panel.innerHTML = '<p class="note">确定删除 SQLite 中已保存的 Key 吗？删除后旧文件、凭据库及环境变量不会自动恢复生效。</p><div class="run-controls"><button type="button" class="danger" data-action="confirm-delete">确认删除</button><button type="button" data-action="cancel-delete">取消</button></div>';
    q('[data-delete-slot]').append(panel);
    panel.querySelector('[data-action="cancel-delete"]').addEventListener('click', closeDelete);
    panel.querySelector('[data-action="confirm-delete"]').addEventListener('click', async () => {
      invalidateTest(); setBusy(true);
      try { render(await api.credentialDelete(source)); if (!disposed) { field.value = ''; closeDelete(); text('[data-info="test"]', '已删除。当前没有可用的 Key。'); } }
      catch (error) { if (!disposed) text('[data-info="error"]', typeof error === 'string' ? error : '删除失败，编辑值已保留。'); }
      finally { if (!disposed) setBusy(false); }
    });
  });
  q('[data-action="application"]').addEventListener('click', async () => {
    try { await api.credentialApplicationOpen(source); }
    catch (error) { if (!disposed) text('[data-info="error"]', typeof error === 'string' ? error : '无法打开系统浏览器。'); }
  });
  q('[data-action="test"]').addEventListener('click', async () => {
    setBusy(true); const testedGeneration = ++generation; reportTest('running', '正在测试');
    try { const outcome = await api.credentialTest(source, null); if (testedGeneration === generation && !disposed) reportTest(outcome.result === 'success' ? 'success' : 'error', outcome.result === 'success' ? '测试成功' : '测试失败', outcome.message || ''); }
    catch (error) { if (testedGeneration === generation && !disposed) reportTest('error', '测试失败', typeof error === 'string' ? error : '请检查 CLI 后重试。'); }
    finally { if (!disposed) setBusy(false); }
  });
  q('[data-action="refresh"]').addEventListener('click', refresh);
  await refresh();
  return { dispose() { disposed = true; generation += 1; } };
}
