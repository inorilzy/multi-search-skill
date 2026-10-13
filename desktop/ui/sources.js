import { MANAGED_SOURCES, mountCredentials } from './credentials.js';

// Search-source page: one credential panel per allowlisted source. Each panel is scoped to its
// own container, so every action and status read is bound to that row's public source name.
export async function mountSources(root, api) {
  root.innerHTML = '<section class="heading"><p class="eyebrow">SOURCES</p><h1>搜索源与凭据。</h1>'
    + '<p>每个搜索源的 key 分别保存在 Windows 凭据库中。环境变量优先于凭据库，凭据库优先于文件中的 key。</p></section>';
  const disposers = [];
  for (const entry of MANAGED_SOURCES) {
    const section = root.ownerDocument.createElement('div');
    section.setAttribute('data-source-panel', entry.source);
    root.append(section);
    const mounted = await mountCredentials(section, api, { source: entry.source });
    disposers.push(mounted);
  }
  for (const [source, label] of [['hackernews', 'Hacker News'], ['stackoverflow', 'Stack Overflow'], ['sov2ex', 'V2EX'], ['twitter', 'Twitter']]) {
    const section = root.ownerDocument.createElement('section');
    section.className = 'panel';
    section.setAttribute('data-source-panel', source);
    section.innerHTML = `<h2>${label}</h2><p>${source === 'twitter' ? '使用设置页中的 Cookie 文件路径；不在此读取或显示 Cookie 正文。' : '无需凭据（keyless）。'}</p>
      <p>测试会发送外部搜索请求，请只在需要时测试。</p>
      <button type="button" data-action="test">测试 ${label}</button><strong data-status="test" aria-live="polite">尚未测试</strong><p data-info="test"></p>`;
    let disposed = false;
    const button = section.querySelector('button');
    button.addEventListener('click', async () => {
      button.disabled = true;
      const status = section.querySelector('[data-status="test"]');
      const info = section.querySelector('[data-info="test"]');
      status.textContent = '正在测试';
      try {
        const outcome = await api.credentialTest(source, null);
        if (disposed) return;
        status.textContent = outcome.result === 'success' ? '测试成功' : '测试失败';
        info.textContent = outcome.message || outcome.result;
      } catch {
        if (!disposed) { status.textContent = '测试失败'; info.textContent = '测试启动失败，请检查 CLI 后重试。'; }
      } finally { if (!disposed) button.disabled = false; }
    });
    root.append(section);
    disposers.push({ dispose() { disposed = true; } });
  }
  return { dispose() { for (const mounted of disposers) mounted.dispose(); } };
}
