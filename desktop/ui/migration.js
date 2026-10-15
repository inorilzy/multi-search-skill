// Explicit import. Python CLI owns preview, conflict resolution, DPAPI and transactional apply.
const actionLabels = { migrate: '可导入', already_current: '已是最新', conflict: '需要选择来源或解决 SQLite 冲突', unsupported: '不支持，保留原数据', blocked: '无法检查，已跳过' };
const sourceOf = provider => provider === 'github' ? 'github-repos' : provider;
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
const previewText = value => typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value);
export async function mountMigration(root, api) {
  root.innerHTML = `<section class="heading"><p class="eyebrow">LEGACY / MIGRATION</p><h1>显式导入旧配置到 SQLite。</h1><p>旧来源尚未导入，不会自动生效。支持多 Key、Jina 与普通设置；原文件、Windows 旧凭据及环境变量不修改、不删除。</p></section>
    <section class="panel"><div class="section-title"><h2>选择旧来源</h2><button type="button" data-action="preview">预览旧配置</button></div>
    <label><input type="checkbox" data-import="keys_file">旧 Key JSON（.search-keys.json）</label>
    <label><input type="checkbox" data-import="credentials">软件原 Windows 凭据条目</label>
    <label><input type="checkbox" data-import="environment">当前进程 Provider 环境变量</label>
    <label><input type="checkbox" data-import="settings">旧普通设置 JSON</label>
    <p data-info="error" role="alert"></p><div data-plan></div></section>`;
  const text = (selector, value) => { root.querySelector(selector).textContent = value; };
  const selected = () => Object.fromEntries([...root.querySelectorAll('[data-import]')].map(box => [box.dataset.import, box.checked]));
  let plan = null, selection = null, disposed = false, generation = 0;
  function renderPlan(result) {
    plan = result;
    const rows = result.items.map(item => {
      const source = sourceOf(item.provider);
      let control = '';
      if (['migrate', 'conflict'].includes(item.action)) control = `<label><input type="checkbox" data-approve="${esc(source)}"> 确认导入 ${esc(source)}</label>`;
      if (item.source_conflict) control += `<label>导入来源 <select data-source-choice="${esc(source)}"><option value="">请选择</option>${(item.sources || []).map(s => `<option value="${esc(s.source)}">${esc(s.source)} ${esc(previewText(s.preview))}</option>`).join('')}</select></label>`;
      if (item.target_conflict || item.action === 'conflict' && !item.source_conflict) control += `<label>SQLite 冲突选择 <select data-choice="${esc(source)}"><option value="">请选择</option><option value="keep">保留 SQLite 中的值</option><option value="replace">使用选定旧来源替换</option></select></label>`;
      return `<li data-item="${esc(source)}"><strong>${esc(source)}</strong> ${esc(actionLabels[item.action] || item.action)} <code>${esc(previewText(item.preview))}</code> ${control}<p class="note">${esc(item.reason)}</p></li>`;
    }).join('');
    root.querySelector('[data-plan]').innerHTML = `<p>可导入 ${result.migratable.length} 项；跳过 ${result.skipped.length} 项。</p><ul>${rows}</ul><button type="button" class="primary" data-action="apply">确认并导入已选项</button><p data-info="result" role="status"></p>`;
    root.querySelector('[data-action="apply"]').addEventListener('click', apply);
  }
  for (const box of root.querySelectorAll('[data-import]')) box.addEventListener('change', () => { generation += 1; plan = null; selection = null; root.querySelector('[data-plan]').innerHTML = ''; });
  async function preview() {
    text('[data-info="error"]', '');
    const ticket = ++generation;
    plan = null; selection = null; root.querySelector('[data-plan]').innerHTML = '';
    const input = selected();
    if (!Object.values(input).some(Boolean)) { text('[data-info="error"]', '请选择至少一个旧来源。'); return; }
    try { const result = await api.migrationPlan(input); if (!disposed && ticket === generation) { selection = input; renderPlan(result); } }
    catch (error) { if (!disposed && ticket === generation) text('[data-info="error"]', typeof error === 'string' ? error : '无法预览，请检查 CLI 和旧配置。'); }
  }
  async function apply() {
    if (!plan) return;
    const approved = [], choices = {}, sources = {};
    for (const box of root.querySelectorAll('[data-approve]')) if (box.checked) {
      const source = box.dataset.approve; approved.push(source);
      const choice = root.querySelector(`[data-choice="${source}"]`);
      const sourceChoice = root.querySelector(`[data-source-choice="${source}"]`);
      if (choice && !choice.value || sourceChoice && !sourceChoice.value) { text('[data-info="result"]', `请为 ${source} 完成来源与冲突选择。`); return; }
      if (choice) choices[source] = choice.value; if (sourceChoice) sources[source] = sourceChoice.value;
    }
    if (!approved.length) { text('[data-info="result"]', '未选择任何导入项。'); return; }
    try {
      const result = await api.migrationApply(plan.plan_token, approved, choices, sources, selection);
      if (disposed) return;
      const parts = [['已写入', result.written], ['保留', result.kept], ['未变化', result.unchanged], ['失败', result.failed], ['未完成', result.not_done]].map(([label, items]) => `${label}：${items.join('、') || '无'}`);
      text('[data-info="result"]', `${result.complete ? '导入完成' : '导入未全部完成'}。${parts.join('；')}`);
    } catch (error) { if (!disposed) text('[data-info="result"]', typeof error === 'string' ? error : '导入未完成，旧来源或数据库可能已变化，请重新预览。'); }
  }
  root.querySelector('[data-action="preview"]').addEventListener('click', preview);
  return { dispose() { disposed = true; } };
}
