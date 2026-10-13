// Credential panel for one allowlisted search source. Source names mirror credential_commands::SOURCES in Rust.
export const MANAGED_SOURCES = [
  { source: 'baidu', label: 'Baidu AI 搜索' },
  { source: 'brave', label: 'Brave 搜索' },
  { source: 'parallel', label: 'Parallel' },
  { source: 'tavily', label: 'Tavily' },
  { source: 'exa', label: 'Exa' },
  { source: 'firecrawl', label: 'Firecrawl' },
  { source: 'serpapi', label: 'SerpAPI' },
  { source: 'github-repos', label: 'GitHub 仓库' },
];

const storeLabels = { present: '已保存', absent: '未保存', unavailable: '凭据库不可用', unreadable: '已保存条目无法读取' };

function sourceText(overview) {
  if (overview.effective_source === 'env') return `环境变量 ${overview.env_var}`;
  if (overview.effective_source === 'credential_store') return 'Windows 凭据库';
  if (overview.effective_source === 'file') return `文件中的 ${overview.file_key_count} 个 key`;
  if (overview.effective_source === 'unavailable') return '不可用';
  return '未配置';
}

function testText(result, label, provenance) {
  const labels = {
    success: `测试成功：${label} 本次使用${provenance}。`,
    auth_failed: `认证失败：${label} 拒绝了该 key。`,
    quota: `额度不足：${label} 额度已用尽。`,
    rate_limited: '触发频率限制：请稍后再试。',
    network: `网络错误：无法连接 ${label}。`,
    timeout: '超时：请稍后重试。',
    error: '测试失败：请查看 CLI 输出。',
    cli_failed: 'CLI 未返回有效结果。',
  };
  return labels[result] || '测试失败';
}

export async function mountCredentials(root, api, { source = 'tavily' } = {}) {
  const entry = MANAGED_SOURCES.find(item => item.source === source) || MANAGED_SOURCES[3];
  const label = entry.label;
  root.innerHTML = `<section class="heading"><p class="eyebrow">CREDENTIALS / ${entry.source}</p><h1>${label} 凭据。</h1><p>key 只保存在 Windows 凭据库中，不写入配置文件，也不会再次显示。</p></section>
    <section class="panel"><div class="section-title"><h2>保存状态</h2><button type="button" data-action="refresh">刷新</button></div>
      <dl class="cred-status"><dt>已保存</dt><dd data-status="store"></dd><dt>生效来源</dt><dd data-status="source"></dd></dl>
      <p data-info="override" class="note" role="status"></p><p data-info="error" role="alert"></p></section>
    <section class="panel"><div class="section-title"><h2>替换或保存 key</h2></div>
      <form data-save-form><label>${label} API key<input data-field="key" type="password" autocomplete="off" spellcheck="false" maxlength="1024" placeholder="粘贴 key（保存后不再显示）"></label>
      <div class="run-controls"><button type="submit" class="primary" data-action="save">保存到凭据库</button></div></form>
      <p class="note">保存只写入凭据库，不会访问 ${label}，也不会产生费用。</p></section>
    <section class="panel"><div class="section-title"><h2>删除已保存的 key</h2></div>
      <div data-delete-slot><button type="button" data-action="delete">删除已保存的 key</button></div></section>
    <section class="panel"><div class="section-title"><h2>测试连接</h2></div>
      <p class="note" data-info="warning">测试会向 ${label} 发送一次外部搜索请求，可能消耗额度并计入费用。请只在需要时测试。</p>
      <div class="run-controls"><button type="button" data-action="test">测试 ${label}</button><strong data-status="test" aria-live="polite">尚未测试</strong></div>
      <p data-info="test" role="status"></p></section>`;

  const field = root.querySelector('[data-field="key"]');
  const text = (selector, value) => { root.querySelector(selector).textContent = value; };
  const buttons = () => root.querySelectorAll('button');
  let current = { store: { state: 'absent', error: null }, effective_source: 'none', env_overrides_store: false, env_var: '', file_key_count: 0 };

  let generation = 0;
  const provenance = value => JSON.stringify([value.effective_source, value.env_var, value.file_key_count, value.store?.state, value.store?.saved_at]);
  function invalidateTest() {
    generation += 1;
    text('[data-status="test"]', '尚未测试');
    text('[data-info="test"]', '');
  }
  function render(overview) {
    if (provenance(current) !== provenance({ ...current, ...overview })) invalidateTest();
    current = { ...current, ...overview };
    const files = overview.file_key_count ?? 0;
    text('[data-status="store"]', storeLabels[overview.store.state] || overview.store.state);
    text('[data-status="source"]', sourceText(current));
    let note = '';
    if (overview.env_overrides_store) {
      note = `检测到环境变量 ${overview.env_var}，它会覆盖已保存的 key。删除或替换已保存的 key 不会改变当前生效的来源。`;
    } else if (files > 0 && overview.store.state === 'present') {
      note = `文件中的 ${files} 个 key 已保留，但被凭据库 key 覆盖，不参与本来源轮换。`;
    }
    text('[data-info="override"]', note);
    text('[data-info="error"]', overview.store.error || '');
  }
  function setBusy(busy) { for (const button of buttons()) button.disabled = busy; }

  async function refresh() {
    setBusy(true);
    try { render(await api.credentialStatus(source)); }
    catch { text('[data-info="error"]', '无法读取凭据状态，请重试。'); }
    finally { setBusy(false); }
  }

  // Save is confirmed in-page when a file list exists: the file keys stay listed but stop
  // rotating for this source. Cancel removes the panel and writes nothing.
  let pendingKey = null;
  function closeSaveConfirm() { root.querySelector('[data-confirm="save"]')?.remove(); pendingKey = null; }
  function openSaveConfirm(key) {
    closeSaveConfirm();
    pendingKey = key;
    const panel = root.ownerDocument.createElement('div');
    panel.setAttribute('data-confirm', 'save');
    panel.innerHTML = `<p class="note">保存后使用凭据库key，文件中的${current.file_key_count}个key保留但不参与本来源轮换</p>`
      + '<div class="run-controls"><button type="button" class="primary" data-action="confirm-save">确认保存</button>'
      + '<button type="button" data-action="cancel-save">取消</button></div>';
    root.querySelector('[data-save-form]').append(panel);
    panel.querySelector('[data-action="confirm-save"]').addEventListener('click', confirmSave);
    panel.querySelector('[data-action="cancel-save"]').addEventListener('click', closeSaveConfirm);
  }
  async function doSave(key) {
    invalidateTest();
    setBusy(true);
    try { render(await api.credentialSave(source, key)); text('[data-info="test"]', '已保存。尚未测试。'); }
    catch (error) { text('[data-info="error"]', typeof error === 'string' ? error : '保存失败，请检查凭据库访问后重试。'); }
    finally { setBusy(false); }
  }
  async function confirmSave() {
    const key = pendingKey;
    closeSaveConfirm();
    if (key) await doSave(key);
  }

  root.querySelector('[data-save-form]').addEventListener('submit', async event => {
    event.preventDefault();
    const key = field.value;
    field.value = '';
    if ((current.file_key_count ?? 0) > 0) { openSaveConfirm(key); return; }
    await doSave(key);
  });

  // Delete is two-step: the first click only opens an in-page confirmation whose wording
  // says what happens next. It never claims the source has no credentials while a file list
  // or an env var still provides one.
  function deleteWarning() {
    const files = current.file_key_count ?? 0;
    const parts = ['确定删除已保存的 key 吗？'];
    if (current.env_var) parts.push(`环境变量 ${current.env_var} 仍会覆盖，删除不会改变当前生效的来源。`);
    if (files > 0) parts.push(`删除后将恢复使用文件中的 ${files} 个 key。`);
    if (!files && !current.env_var) parts.push('删除后需要重新粘贴 key 才能使用。');
    return parts.join('');
  }
  function closeDeleteConfirm() { root.querySelector('[data-confirm="delete"]')?.remove(); }
  function openDeleteConfirm() {
    if (root.querySelector('[data-confirm="delete"]')) return;
    const panel = root.ownerDocument.createElement('div');
    panel.setAttribute('data-confirm', 'delete');
    panel.innerHTML = `<p class="note">${deleteWarning()}</p>`
      + '<div class="run-controls"><button type="button" class="primary" data-action="confirm-delete">确认删除</button>'
      + '<button type="button" data-action="cancel-delete">取消</button></div>';
    root.querySelector('[data-delete-slot]').append(panel);
    panel.querySelector('[data-action="confirm-delete"]').addEventListener('click', confirmDelete);
    panel.querySelector('[data-action="cancel-delete"]').addEventListener('click', closeDeleteConfirm);
  }

  async function confirmDelete() {
    invalidateTest();
    setBusy(true);
    try {
      render(await api.credentialDelete(source));
      closeDeleteConfirm();
      const files = current.file_key_count ?? 0;
      let message = '已删除。';
      if (current.env_var) message += `仍由环境变量 ${current.env_var} 生效。`;
      else if (files > 0) message += `已恢复使用文件中的 ${files} 个 key。`;
      else message += '当前没有可用的 key。';
      text('[data-info="test"]', message);
    }
    catch (error) {
      closeDeleteConfirm();
      text('[data-info="error"]', typeof error === 'string' ? error : '删除失败，请重试。');
    }
    finally { setBusy(false); }
  }

  root.querySelector('[data-action="delete"]').addEventListener('click', openDeleteConfirm);

  root.querySelector('[data-action="test"]').addEventListener('click', async () => {
    setBusy(true);
    const testedGeneration = ++generation;
    const testedSource = sourceText(current);
    text('[data-status="test"]', '正在测试');
    try {
      const outcome = await api.credentialTest(source, null);
      if (testedGeneration !== generation) return;
      text('[data-status="test"]', testText(outcome.result, label, testedSource));
      text('[data-info="test"]', outcome.message || '');
    } catch (error) {
      if (testedGeneration !== generation) return;
      text('[data-status="test"]', '测试失败');
      text('[data-info="test"]', typeof error === 'string' ? error : '测试启动失败，请检查 CLI 后重试。');
    } finally { if (testedGeneration === generation) setBusy(false); }
  });

  root.querySelector('[data-action="refresh"]').addEventListener('click', refresh);
  await refresh();
  return { dispose() { generation += 1; } };
}
