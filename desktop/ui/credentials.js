import { openConfirm } from './confirm.js';

// Copy: 'API Key' for the credential, 'Cookie' for Twitter, and a space between Chinese and Latin text.
// The single canonical search-source list. Keyed sources store a key in the Windows credential
// store; their names mirror credential_commands::SOURCES in Rust, which also accepts the
// hyphenated `github-repos` alias. Keyless sources need no key. `twitter` reads a cookie file
// path from settings and never a cookie body. settings.js derives its own view from this list,
// so the allowlist is described in exactly one place.
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

const storeLabels = { present: '已保存', absent: '未保存', unavailable: '凭据库不可用', unreadable: '已保存条目无法读取' };

function sourceText(overview) {
  if (overview.effective_source === 'env') return `环境变量 ${overview.env_var}`;
  if (overview.effective_source === 'credential_store') return 'Windows 凭据库';
  if (overview.effective_source === 'file') return `文件中的 ${overview.file_key_count} 个 Key`;
  if (overview.effective_source === 'unavailable') return '不可用';
  return '未配置';
}

function testText(result, label, provenance) {
  const labels = {
    success: `测试成功：${label} 本次使用 ${provenance}。`,
    auth_failed: `认证失败：${label} 拒绝了该 Key。`,
    quota: `额度不足：${label} 额度已用尽。`,
    rate_limited: '触发频率限制：请稍后再试。',
    network: `网络错误：无法连接 ${label}。`,
    timeout: '超时：请稍后重试。',
    error: '测试失败：请查看 CLI 输出。',
    cli_failed: 'CLI 未返回有效结果。',
  };
  return labels[result] || '测试失败';
}

/// Full page: heading plus the credential panels. Used when a source owns its own page.
export async function mountCredentials(root, api, options = {}) {
  const entry = sourceEntry(options.source);
  root.innerHTML = `<section class="heading"><p class="eyebrow">CREDENTIALS / ${entry.source}</p><h1 tabindex="-1">${entry.label} 凭据。</h1><p>Key 只保存在 Windows 凭据库中，不写入配置文件，也不会再次显示。</p></section>`;
  const holder = root.ownerDocument.createElement('div');
  root.append(holder);
  return mountCredentialBody(holder, api, options);
}

function sourceEntry(source) {
  return SOURCES.find(item => item.source === source)
    || SOURCES.find(item => item.source === DEFAULT_SOURCE);
}

/// Panels only, no heading: the detail pane of the sources page mounts this so a selected
/// source does not add a second h1 to the document.
export async function mountCredentialBody(root, api, { source = DEFAULT_SOURCE, onStatus, onTest } = {}) {
  const entry = sourceEntry(source);
  const label = entry.label;
  root.innerHTML = `<div class="credential-editor">
      <div class="credential-fields"><form data-save-form>
        <label>${label} API Key<span class="key-input"><input data-field="key" type="password" autocomplete="off" spellcheck="false" maxlength="1024" placeholder="输入新 Key（已保存的 Key 不回显）"><button type="button" data-action="reveal" aria-label="显示本次输入" aria-pressed="false">显示</button></span></label>
        <button type="submit" class="primary" data-action="save">保存 Key</button><button type="button" data-action="test">测试连接</button>
      </form>
      <p class="credential-note">Key 保存在本机 Windows 凭据库。保存不会发起搜索请求。</p>
      <dl class="cred-status"><dt>已保存</dt><dd data-status="store"></dd><dt>生效来源</dt><dd data-status="source"></dd></dl>
      <p data-info="override" class="note" role="status"></p><p data-info="error" role="alert"></p>
      <div class="credential-tools"><button type="button" data-action="refresh">刷新状态</button><div data-delete-slot><button type="button" data-action="delete">删除已保存的 Key</button></div></div></div>
      <div class="credential-feedback"><div class="test-result" data-test-result data-kind="idle"><span class="result-symbol" aria-hidden="true"></span><div><strong data-status="test" aria-live="polite">尚未测试</strong><p data-info="test" role="status"></p></div></div>
      <p class="credential-note" data-info="warning">测试会向 ${label} 发送一次外部搜索请求，并向对应服务商提供认证凭据，可能消耗额度并计入费用。请只在需要时测试。</p></div>
    </div>`;

  const field = root.querySelector('[data-field="key"]');
  const text = (selector, value) => { root.querySelector(selector).textContent = value; };
  const buttons = () => root.querySelectorAll('button');
  let current = { store: { state: 'absent', error: null }, effective_source: 'none', env_overrides_store: false, env_var: '', file_key_count: 0 };

  let generation = 0;
  let disposed = false;
  function reportTest(kind, title, message = '') {
    if (disposed) return;
    text('[data-status="test"]', title);
    text('[data-info="test"]', message);
    root.querySelector('[data-test-result]').dataset.kind = kind;
    onTest?.({ kind, title, message });
  }
  root.querySelector('[data-action="reveal"]').addEventListener('click', event => {
    const visible = field.type === 'password';
    field.type = visible ? 'text' : 'password';
    event.currentTarget.textContent = visible ? '隐藏' : '显示';
    event.currentTarget.setAttribute('aria-pressed', String(visible));
    event.currentTarget.setAttribute('aria-label', `${visible ? '隐藏' : '显示'}本次输入`);
  });
  const provenance = value => JSON.stringify([value.effective_source, value.env_var, value.file_key_count, value.store?.state, value.store?.saved_at]);
  function invalidateTest() {
    generation += 1;
    reportTest('idle', '尚未测试');
  }
  function render(overview) {
    if (disposed) return;
    if (provenance(current) !== provenance({ ...current, ...overview })) invalidateTest();
    current = { ...current, ...overview };
    onStatus?.(current);
    const files = overview.file_key_count ?? 0;
    text('[data-status="store"]', storeLabels[overview.store.state] || overview.store.state);
    text('[data-status="source"]', sourceText(current));
    let note = '';
    if (overview.env_overrides_store) {
      note = `检测到环境变量 ${overview.env_var}，它会覆盖已保存的 Key。删除或替换已保存的 Key 不会改变当前生效的来源。`;
    } else if (files > 0 && overview.store.state === 'present') {
      note = `文件中的 ${files} 个 Key 已保留，但被凭据库 Key 覆盖，不参与本来源轮换。`;
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
  let releaseSave = null;
  // Backend values are set with textContent; only constant markup goes through innerHTML.
  function confirmPanel(kind, message, confirmClass, confirmLabel) {
    const panel = root.ownerDocument.createElement('div');
    panel.setAttribute('data-confirm', kind);
    panel.innerHTML = `<p class="note"></p><div class="run-controls"><button type="button" class="${confirmClass}" data-action="confirm-${kind}">${confirmLabel}</button>`
      + `<button type="button" data-action="cancel-${kind}">取消</button></div>`;
    panel.querySelector('p').textContent = message;
    return panel;
  }
  function closeSaveConfirm(options) {
    releaseSave?.(options);
    releaseSave = null;
    root.querySelector('[data-confirm="save"]')?.remove();
    pendingKey = null;
  }
  function openSaveConfirm(key) {
    closeSaveConfirm({ restoreFocus: false });
    pendingKey = key;
    const panel = confirmPanel('save', `保存后使用凭据库 Key，文件中的 ${current.file_key_count} 个 Key 保留但不参与本来源轮换。`, 'primary', '确认保存');
    root.querySelector('[data-save-form]').append(panel);
    panel.querySelector('[data-action="confirm-save"]').addEventListener('click', confirmSave);
    panel.querySelector('[data-action="cancel-save"]').addEventListener('click', () => closeSaveConfirm());
    releaseSave = openConfirm(panel, { trigger: root.querySelector('[data-action="save"]'), cancel: panel.querySelector('[data-action="cancel-save"]'), onCancel: () => closeSaveConfirm() });
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
    closeSaveConfirm({ restoreFocus: false });
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
    const parts = ['确定删除已保存的 Key 吗？'];
    if (current.env_var) parts.push(`环境变量 ${current.env_var} 仍会覆盖，删除不会改变当前生效的来源。`);
    if (files > 0) parts.push(`删除后将恢复使用文件中的 ${files} 个 Key。`);
    if (!files && !current.env_var) parts.push('删除后需要重新粘贴 Key 才能使用。');
    return parts.join('');
  }
  let releaseDelete = null;
  function closeDeleteConfirm(options) {
    releaseDelete?.(options);
    releaseDelete = null;
    root.querySelector('[data-confirm="delete"]')?.remove();
  }
  function openDeleteConfirm() {
    if (root.querySelector('[data-confirm="delete"]')) return;
    const panel = confirmPanel('delete', deleteWarning(), 'danger', '确认删除');
    root.querySelector('[data-delete-slot]').append(panel);
    panel.querySelector('[data-action="confirm-delete"]').addEventListener('click', confirmDelete);
    panel.querySelector('[data-action="cancel-delete"]').addEventListener('click', () => closeDeleteConfirm());
    releaseDelete = openConfirm(panel, { trigger: root.querySelector('[data-action="delete"]'), cancel: panel.querySelector('[data-action="cancel-delete"]'), onCancel: () => closeDeleteConfirm() });
  }

  async function confirmDelete() {
    invalidateTest();
    setBusy(true);
    try {
      render(await api.credentialDelete(source));
      const files = current.file_key_count ?? 0;
      let message = '已删除。';
      if (current.env_var) message += `仍由环境变量 ${current.env_var} 生效。`;
      else if (files > 0) message += `已恢复使用文件中的 ${files} 个 Key。`;
      else message += '当前没有可用的 Key。';
      text('[data-info="test"]', message);
    }
    catch (error) {
      text('[data-info="error"]', typeof error === 'string' ? error : '删除失败，请重试。');
    }
    // Re-enable first so focus can return to the delete button.
    finally { setBusy(false); closeDeleteConfirm(); }
  }

  root.querySelector('[data-action="delete"]').addEventListener('click', openDeleteConfirm);

  root.querySelector('[data-action="test"]').addEventListener('click', async () => {
    setBusy(true);
    const testedGeneration = ++generation;
    const testedSource = sourceText(current);
    reportTest('running', '正在测试');
    try {
      const outcome = await api.credentialTest(source, null);
      if (testedGeneration !== generation) return;
      reportTest(outcome.result === 'success' ? 'success' : 'error', testText(outcome.result, label, testedSource), outcome.message || '');
    } catch (error) {
      if (testedGeneration !== generation) return;
      reportTest('error', '测试失败', typeof error === 'string' ? error : '测试启动失败，请检查 CLI 后重试。');
    } finally { if (testedGeneration === generation) setBusy(false); }
  });

  root.querySelector('[data-action="refresh"]').addEventListener('click', refresh);
  await refresh();
  return { dispose() { disposed = true; generation += 1; } };
}
