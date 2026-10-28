import { showError } from './api.js';

const reasons = { exists: '目标已存在', invalid_scope: '目标无效', cli_missing: 'CLI 不可发现', cli_incompatible: 'CLI 与 Skill 不兼容', ready: '可安装' };
const stateLabels = { current: '当前版本', outdated: '有可用更新', modified: '有本地修改', absent: '未安装', unknown: '未知状态' };
// Known statuses are localized; a raw backend enum is never shown on its own.
const statusText = (status, fallback) => reasons[status] || fallback || `未知状态（${status ?? '无'}）`;
export async function mountSkill(root, api, { number = '03' } = {}) {
  root.innerHTML = `<section class="heading"><p class="eyebrow">${number} / CLAUDE CODE SKILL</p><h1 tabindex="-1">让 Claude Code 使用本机 CLI。</h1><p>安装仅写入所选目录中的 multi-search 技能文件，不覆盖已有内容，不使用 MCP。</p></section>
    <section class="panel skill-install"><div class="section-title"><h2>安装范围</h2><span class="eyebrow">CLAUDE CODE ONLY</span></div>
      <fieldset><legend>作用范围</legend>
        <label><input type="radio" name="scope" value="global" checked> 全局（当前用户的所有项目）</label>
        <label><input type="radio" name="scope" value="project"> 项目（仅所选项目）</label></fieldset>
      <label class="path-input">项目目录<input data-field="project" placeholder="仅项目范围需要，例如 C:\\…\\my-project" spellcheck="false" disabled></label>
      <div class="run-controls"><button type="button" data-action="preview">预览目标</button><button type="button" data-action="install" class="primary" disabled>安装 Skill</button></div>
      <p data-info="target"></p><p data-info="status" aria-live="polite"></p><p data-info="error" role="alert"></p></section>
    <section class="panel skill-manage"><div class="section-title"><h2>已安装 Skill</h2><span class="eyebrow">UPDATE / REMOVE</span></div>
      <div class="run-controls"><button type="button" data-action="check">检查已安装版本</button></div>
      <p data-info="installed" aria-live="polite"></p><p data-info="managed-target"></p><p data-info="compatibility"></p><p data-info="modified"></p>
      <label class="confirm"><input type="checkbox" data-field="confirm-overwrite"> 我已确认：备份本地修改后再用本版本覆盖</label>
      <div class="run-controls"><button type="button" data-action="update" disabled>更新 Skill</button><button type="button" data-action="remove-plan" disabled>预览移除</button><button type="button" data-action="remove" class="danger" disabled>确认移除</button></div>
      <p data-info="manage-plan"></p><p data-info="manage-status" aria-live="polite"></p><p data-info="manage-error" role="alert"></p></section>`;
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
      root.querySelector('[data-info="status"]').textContent = `${statusText(plan.status)}：${plan.reason}`;
      install.disabled = !ready;
    } catch (error) { ready = false; install.disabled = true; showError(root.querySelector('[data-info="error"]'), error, '预览失败，请重试。'); }
  });
  install.addEventListener('click', async () => {
    if (!ready || plannedScope !== selectedScope() || plannedProject !== projectValue()) { root.querySelector('[data-info="error"]').textContent = '请先预览目标目录。'; return; }
    install.disabled = true;
    // Blocks manage actions and drops any manage plan made before this write.
    setBusy(true);
    let writeNote = '';
    try {
      const result = await api.skillInstall(plannedScope, plannedProject);
      root.querySelector('[data-info="target"]').textContent = result.target ? `目标目录：${result.target}` : '';
      root.querySelector('[data-info="status"]').textContent = result.status === 'installed' ? `已安装并校验：${result.reason}` : `未完成安装：${result.reason}`;
      if (result.status === 'installed') writeNote = '操作已完成';
      ready = false;
    } catch (error) { showError(root.querySelector('[data-info="error"]'), error, '安装失败，未确认写入结果，请重新预览。'); ready = false; }
    finally { install.disabled = true; }
    // Re-read the real target so the manage panel shows what is on disk, not the expected result.
    try { await refreshManage(writeNote); } finally { if (!disposed) setBusy(false); }
  });
  // Manage panel: status, update, and removal. Each destructive step needs its own explicit confirmation.
  const info = name => root.querySelector(`[data-info="${name}"]`);
  const manageButton = name => root.querySelector(`[data-action="${name}"]`);
  const confirmOverwrite = root.querySelector('[data-field="confirm-overwrite"]');
  let managedScope = null, managedProject = null, removeReady = false, generation = 0, disposed = false, busy = false;
  const setBusy = value => {
    busy = value;
    manageButton('check').disabled = value;
    root.querySelectorAll('input[name="scope"]').forEach(input => { input.disabled = value; });
    project.disabled = value || selectedScope() !== 'project';
    confirmOverwrite.disabled = value;
    if (value) {
      generation++; removeReady = false;
      ['update', 'remove-plan', 'remove'].forEach(name => { manageButton(name).disabled = true; });
    }
  };
  const invalidateManage = () => {
    generation++; managedScope = null; managedProject = null; removeReady = false;
    confirmOverwrite.checked = false;
    ['update', 'remove-plan', 'remove'].forEach(name => { manageButton(name).disabled = true; });
    ['installed', 'managed-target', 'compatibility', 'modified', 'manage-plan'].forEach(name => { info(name).textContent = ''; });
  };
  root.querySelectorAll('input[name="scope"]').forEach(input => input.addEventListener('change', invalidateManage));
  project.addEventListener('input', invalidateManage);
  const manageScope = () => selectedScope();
  const manageProject = () => projectValue();
  const sameTarget = () => managedScope === manageScope() && managedProject === manageProject();
  const setManageError = text => { info('manage-error').textContent = text; };
  // Reads the real target and rebuilds the manage panel. Obsolete plans are dropped first.
  // `writeDone` is set when a write just returned success; a failed read then must not look like a failed write.
  const refreshManage = async (writeDone = '') => {
    invalidateManage();
    setManageError('');
    const request = generation, scope = manageScope(), targetProject = manageProject();
    try {
      const status = await api.skillStatus(scope, targetProject);
      if (disposed || request !== generation || scope !== manageScope() || targetProject !== manageProject()) return;
      managedScope = scope; managedProject = targetProject; removeReady = false;
      info('installed').textContent = `状态：${stateLabels[status.state] || `未知状态（${status.state}）`}；已装版本：${status.installed_version ?? '无'}；发布版本：${status.release_version}。${status.reason}`;
      info('managed-target').textContent = `目标目录：${status.target ?? '未确认'}`;
      info('compatibility').textContent = `CLI 要求：${status.cli_requirements ?? '请重新检查'}。${status.compatibility_reason ?? ''}`;
      info('modified').textContent = status.modified_files.length ? `本地修改：${status.modified_files.join('、')}` : '';
      info('manage-plan').textContent = status.unknown_entries.length ? `保留（非本工具管理）：${status.unknown_entries.join('、')}` : '';
      manageButton('update').disabled = status.can_update !== true;
      manageButton('remove-plan').disabled = !['outdated', 'modified', 'current'].includes(status.state);
      manageButton('remove').disabled = true;
      confirmOverwrite.checked = false;
    } catch (error) {
      if (disposed || request !== generation) return;
      const shown = showError(info('manage-error'), error, '检查失败，请重试。');
      if (writeDone) info('manage-error').textContent = `${writeDone}，当前状态未确认：${shown.message}。请点击“检查已安装版本”重试。`;
    }
  };
  manageButton('check').addEventListener('click', async () => {
    if (busy || disposed) return;
    await refreshManage();
  });
  manageButton('update').addEventListener('click', async () => {
    if (!sameTarget()) { setManageError('请先检查当前目标。'); return; }
    setManageError('');
    if (busy || disposed) return;
    setBusy(true);
    let writeDone = '';
    try {
      const result = await api.skillUpdate(managedScope, managedProject, confirmOverwrite.checked);
      info('manage-status').textContent = result.status === 'updated' && result.verified === true
        ? `已更新并校验：${result.reason}${result.backup ? `；本地修改已备份到 ${result.backup}` : ''}`
        : `未完成更新：${result.reason}${result.backup ? `；备份位置 ${result.backup}` : ''}`;
      if (result.status === 'updated') writeDone = '操作已完成';
    } catch (error) { showError(info('manage-error'), error, '更新失败，原 Skill 未被确认改变，请重新检查。'); }
    finally { setBusy(false); }
    if (!disposed) await refreshManage(writeDone);
  });
  manageButton('remove-plan').addEventListener('click', async () => {
    if (!sameTarget()) { setManageError('请先检查当前目标。'); return; }
    setManageError('');
    removeReady = false; manageButton('remove').disabled = true;
    const request = ++generation;
    try {
      const plan = await api.skillRemovePlan(managedScope, managedProject);
      if (disposed || request !== generation || !sameTarget()) return;
      removeReady = plan.can_remove;
      info('manage-plan').textContent = plan.can_remove
        ? `将删除：${plan.will_delete.join('、')}；保留：${plan.will_keep.join('、') || '无'}。${plan.reason}`
        : `无可移除内容：${plan.reason}`;
      manageButton('remove').disabled = !removeReady;
    } catch (error) { if (!disposed && request === generation) showError(info('manage-error'), error, '移除预览失败，请重试。'); }
  });
  manageButton('remove').addEventListener('click', async () => {
    if (busy || disposed) return;
    if (!removeReady || !sameTarget()) { setManageError('请先预览移除范围。'); return; }
    setBusy(true);
    try {
      const result = await api.skillRemove(managedScope, managedProject, true);
      info('manage-status').textContent = result.status === 'removed'
        ? `已移除：${result.deleted.join('、')}。${result.reason}`
        : `未移除：${result.reason}`;
    } catch (error) { showError(info('manage-error'), error, '移除失败，请重新检查目标。'); }
    finally { removeReady = false; setBusy(false); if (!disposed) manageButton('check').click(); }
  });
  return { dispose() { disposed = true; generation++; } };
}
