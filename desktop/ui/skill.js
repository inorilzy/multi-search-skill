const reasons = { exists: '目标已存在', invalid_scope: '目标无效', cli_missing: 'CLI 不可发现', cli_incompatible: 'CLI 与 Skill 不兼容', ready: '可安装' };
export async function mountSkill(root, api) {
  root.innerHTML = `<section class="heading"><p class="eyebrow">02 / CLAUDE CODE SKILL</p><h1>让 Claude Code 使用本机 CLI。</h1><p>安装仅写入所选目录中的 multi-search 技能文件，不覆盖已有内容，不使用 MCP。</p></section>
    <section class="panel skill-install"><div class="section-title"><h2>安装范围</h2><span class="eyebrow">CLAUDE CODE ONLY</span></div>
      <fieldset><legend>作用范围</legend>
        <label><input type="radio" name="scope" value="global" checked> 全局（当前用户的所有项目）</label>
        <label><input type="radio" name="scope" value="project"> 项目（仅所选项目）</label></fieldset>
      <label class="path-input">项目目录<input data-field="project" placeholder="仅项目范围需要，例如 C:\\…\\my-project" spellcheck="false" disabled></label>
      <div class="run-controls"><button type="button" data-action="preview">预览目标</button><button type="button" data-action="install" class="primary" disabled>安装 Skill</button></div>
      <p data-info="target"></p><p data-info="status" aria-live="polite"></p><p data-info="error" role="alert"></p></section>`;
  const project = root.querySelector('[data-field="project"]');
  const install = root.querySelector('[data-action="install"]');
  let plannedScope = null, plannedProject = null, ready = false;
  const selectedScope = () => root.querySelector('input[name="scope"]:checked').value;
  const projectValue = () => (selectedScope() === 'project' ? project.value.trim() || null : null);
  root.querySelectorAll('input[name="scope"]').forEach(input => input.addEventListener('change', () => {
    project.disabled = selectedScope() !== 'project';
    ready = false; install.disabled = true;
    root.querySelector('[data-info="target"]').textContent = ''; root.querySelector('[data-info="status"]').textContent = '';
  }));
  root.querySelector('[data-action="preview"]').addEventListener('click', async () => {
    root.querySelector('[data-info="error"]').textContent = '';
    try {
      const plan = await api.skillPlan(selectedScope(), projectValue());
      plannedScope = plan.scope; plannedProject = projectValue(); ready = plan.can_install;
      root.querySelector('[data-info="target"]').textContent = plan.target ? `目标目录：${plan.target}\n文件：${plan.files.join('、')}` : '';
      root.querySelector('[data-info="status"]').textContent = `${reasons[plan.status] || plan.status}：${plan.reason}`;
      install.disabled = !ready;
    } catch { ready = false; install.disabled = true; root.querySelector('[data-info="error"]').textContent = '预览失败，请重试。'; }
  });
  install.addEventListener('click', async () => {
    if (!ready || plannedScope !== selectedScope() || plannedProject !== projectValue()) { root.querySelector('[data-info="error"]').textContent = '请先预览目标目录。'; return; }
    install.disabled = true;
    try {
      const result = await api.skillInstall(plannedScope, plannedProject);
      root.querySelector('[data-info="target"]').textContent = result.target ? `目标目录：${result.target}` : '';
      root.querySelector('[data-info="status"]').textContent = result.status === 'installed' ? `已安装并校验：${result.reason}` : `未完成安装：${result.reason}`;
      ready = false;
    } catch { root.querySelector('[data-info="error"]').textContent = '安装失败，未确认写入结果，请重新预览。'; ready = false; }
    finally { install.disabled = true; }
  });
  return { dispose() {} };
}
