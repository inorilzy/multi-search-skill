const storeLabels = { present: '已保存', absent: '未保存', unavailable: '凭据库不可用', unreadable: '已保存条目无法读取' };
const sourceLabels = { env: '环境变量 TAVILY_API_KEY', credential_store: 'Windows 凭据库', none: '未配置', unavailable: '不可用' };
const testLabels = {
  success: '测试成功：Tavily 可以使用已保存的 key。',
  auth_failed: '认证失败：Tavily 拒绝了该 key。',
  quota: '额度不足：Tavily 额度已用尽。',
  rate_limited: '触发频率限制：请稍后再试。',
  network: '网络错误：无法连接 Tavily。',
  timeout: '超时：请稍后重试。',
  error: '测试失败：请查看 CLI 输出。',
  cli_failed: 'CLI 未返回有效结果。',
};

export async function mountCredentials(root, api) {
  root.innerHTML = `<section class="heading"><p class="eyebrow">02 / CREDENTIALS</p><h1>Tavily 凭据。</h1><p>key 只保存在 Windows 凭据库中，不写入配置文件，也不会再次显示。</p></section>
    <section class="panel"><div class="section-title"><h2>保存状态</h2><button type="button" data-action="refresh">刷新</button></div>
      <dl class="cred-status"><dt>已保存</dt><dd data-status="store"></dd><dt>生效来源</dt><dd data-status="source"></dd></dl>
      <p data-info="override" class="note" role="status"></p><p data-info="error" role="alert"></p></section>
    <section class="panel"><div class="section-title"><h2>替换或保存 key</h2></div>
      <form data-save-form><label>Tavily API key<input data-field="key" type="password" autocomplete="off" spellcheck="false" maxlength="1024" placeholder="粘贴 key（保存后不再显示）"></label>
      <div class="run-controls"><button type="submit" class="primary" data-action="save">保存到凭据库</button></div></form>
      <p class="note">保存只写入凭据库，不会访问 Tavily，也不会产生费用。</p></section>
    <section class="panel"><div class="section-title"><h2>删除已保存的 key</h2></div>
      <button type="button" data-action="delete">删除已保存的 key</button></section>
    <section class="panel"><div class="section-title"><h2>测试连接</h2></div>
      <p class="note" data-info="warning">测试会向 Tavily 发送一次外部搜索请求，可能消耗额度并计入费用。请只在需要时测试。</p>
      <div class="run-controls"><button type="button" data-action="test">测试 Tavily</button><strong data-status="test" aria-live="polite">尚未测试</strong></div>
      <p data-info="test" role="status"></p></section>`;

  const field = root.querySelector('[data-field="key"]');
  const text = (selector, value) => { root.querySelector(selector).textContent = value; };
  const buttons = () => root.querySelectorAll('button');

  function render(overview) {
    text('[data-status="store"]', storeLabels[overview.store.state] || overview.store.state);
    text('[data-status="source"]', sourceLabels[overview.effective_source] || overview.effective_source);
    text('[data-info="override"]', overview.env_overrides_store
      ? '检测到 TAVILY_API_KEY 环境变量，它会覆盖已保存的 key。删除或替换已保存的 key 不会改变当前生效的来源。'
      : '');
    text('[data-info="error"]', overview.store.error || '');
  }
  function setBusy(busy) { for (const button of buttons()) button.disabled = busy; }

  async function refresh() {
    setBusy(true);
    try { render(await api.credentialStatus()); }
    catch { text('[data-info="error"]', '无法读取凭据状态，请重试。'); }
    finally { setBusy(false); }
  }

  root.querySelector('[data-save-form]').addEventListener('submit', async event => {
    event.preventDefault();
    const key = field.value;
    field.value = '';
    setBusy(true);
    try { render(await api.credentialSave(key)); text('[data-info="test"]', '已保存。尚未测试。'); }
    catch (error) { text('[data-info="error"]', typeof error === 'string' ? error : '保存失败，请检查凭据库访问后重试。'); }
    finally { setBusy(false); }
  });

  root.querySelector('[data-action="delete"]').addEventListener('click', async () => {
    setBusy(true);
    try { render(await api.credentialDelete()); text('[data-info="test"]', '已删除。'); }
    catch (error) { text('[data-info="error"]', typeof error === 'string' ? error : '删除失败，请重试。'); }
    finally { setBusy(false); }
  });

  root.querySelector('[data-action="test"]').addEventListener('click', async () => {
    setBusy(true);
    text('[data-status="test"]', '正在测试');
    try {
      const outcome = await api.credentialTest(null);
      text('[data-status="test"]', testLabels[outcome.result] || '测试失败');
      text('[data-info="test"]', outcome.message || '');
    } catch (error) {
      text('[data-status="test"]', '测试失败');
      text('[data-info="test"]', typeof error === 'string' ? error : '测试启动失败，请检查 CLI 后重试。');
    } finally { setBusy(false); }
  });

  root.querySelector('[data-action="refresh"]').addEventListener('click', refresh);
  await refresh();
  return { dispose() {} };
}
