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
  return { dispose() { for (const mounted of disposers) mounted.dispose(); } };
}
