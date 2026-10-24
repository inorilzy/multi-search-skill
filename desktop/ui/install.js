import { openConfirm } from './confirm.js';

const statusLabels = {
  ready: '可安装',
  installed: '已由本工具安装',
  prerequisite_missing: '缺少安装前提',
  integrity_failed: '完整性校验失败',
  unknown_existing: '已有未知安装，未修改',
  unavailable: '不可用',
  failed: '安装失败',
  already_installed: '已安装，未覆盖',
  update_available: '有可用更新',
  unverified: '安装记录无法验证，已阻止修改',
  not_installed: '未安装',
  uninstalled: '已卸载',
};

export async function mountInstall(root, api, { number = '02' } = {}) {
  root.innerHTML = `<section class="heading"><p class="eyebrow">${number} / INSTALL CLI</p><h1 tabindex="-1">安装命令行工具。</h1><p>从受控来源安装并校验。未知安装不会被覆盖，失败不会改动已有可用版本。</p></section>
    <section class="panel install"><div class="section-title"><h2>安装计划</h2><button type="button" data-action="plan">重新检查</button></div>
      <strong data-status="plan" aria-live="polite">检查中</strong>
      <dl class="install-plan"><dt>安装目录</dt><dd data-info="root"></dd><dt>可执行文件</dt><dd data-info="bin"></dd><dt>版本</dt><dd data-info="version"></dd><dt>当前版本</dt><dd data-info="current-version"></dd><dt>安装来源</dt><dd data-info="source"></dd><dt>Skill 兼容性</dt><dd data-info="compatibility"></dd></dl>
      <p data-info="path-hint" class="note"></p><p data-info="reason" role="alert"></p>
      <div class="run-controls"><button type="button" data-action="install" class="primary" disabled>安装 CLI</button><button type="button" data-action="update" disabled>更新 CLI</button><button type="button" data-action="uninstall" disabled>卸载 CLI</button><strong data-status="result" aria-live="polite"></strong></div>
      <div class="run-controls" data-confirm hidden><p>卸载只删除本工具安装的 CLI 文件；配置、凭据和 Skill 会保留。</p><button type="button" data-action="uninstall-confirm" class="danger">确认卸载</button><button type="button" data-action="uninstall-cancel">取消</button></div>
      <ol data-steps aria-label="安装步骤"></ol></section>
    <section class="panel"><h2>用户 PATH 与宿主发现</h2><p data-path-directory></p><p data-path-reason></p>
      <button type="button" data-action="path-add" disabled>将 CLI 加入当前用户 PATH</button>
      <button type="button" data-action="path-remove" disabled>移除本工具添加的 PATH 项</button>
      <div data-path-confirm hidden><p>确认仅修改上方目录对应的当前用户 PATH 项？系统 PATH 不变。完成后请重启终端或 Agent 宿主。</p><button type="button" data-action="path-confirm">确认修改用户 PATH</button><button type="button" data-action="path-cancel">取消</button></div>
      <p data-path-result role="status"></p></section>`;
  const install = root.querySelector('[data-action="install"]');
  const update = root.querySelector('[data-action="update"]');
  const uninstall = root.querySelector('[data-action="uninstall"]');
  const confirmBox = root.querySelector('[data-confirm]');
  const plan = root.querySelector('[data-action="plan"]');
  const uninstallCancel = root.querySelector('[data-action="uninstall-cancel"]');
  let busy = false;
  let releaseUninstall = null;
  function closeUninstall(options) {
    releaseUninstall?.(options);
    releaseUninstall = null;
    confirmBox.hidden = true;
  }

  function renderPlan(status) {
    root.querySelector('[data-status="plan"]').textContent = statusLabels[status.status] || status.status;
    root.querySelector('[data-status="plan"]').dataset.kind = status.status;
    root.querySelector('[data-info="root"]').textContent = status.root || '';
    root.querySelector('[data-info="bin"]').textContent = status.bin || '';
    root.querySelector('[data-info="version"]').textContent = status.version ? `v${status.version}` : '';
    root.querySelector('[data-info="current-version"]').textContent = status.current_version ? `v${status.current_version}` : '';
    root.querySelector('[data-info="source"]').textContent = status.source || '';
    const compatLabel = { compatible: '兼容', incompatible: '不兼容', unknown: '未知' }[status.compatibility];
    root.querySelector('[data-info="compatibility"]').textContent = status.compatibility
      ? `${compatLabel || status.compatibility}：${status.compatibility_reason || ''}` : '';
    root.querySelector('[data-info="path-hint"]').textContent = ['ready', 'installed'].includes(status.status) ? status.path_hint : '';
    // A ready plan must not erase the reason of the previous install result.
    if (status.status !== 'ready') root.querySelector('[data-info="reason"]').textContent = status.reason || '';
    install.disabled = busy || status.status !== 'ready';
    update.disabled = busy || status.status !== 'update_available';
    uninstall.disabled = busy || status.status !== 'installed';
    if (status.status !== 'installed') closeUninstall({ restoreFocus: false });
  }

  function renderSteps(steps) {
    const list = root.querySelector('[data-steps]');
    list.replaceChildren(...steps.map(step => {
      const item = root.ownerDocument.createElement('li');
      item.dataset.ok = String(step.ok);
      item.textContent = `${step.ok ? '✓' : '✗'} ${step.name}${step.detail ? `：${step.detail}` : ''}`;
      return item;
    }));
  }

  const pathAdd = root.querySelector('[data-action="path-add"]');
  const pathRemove = root.querySelector('[data-action="path-remove"]');
  const pathConfirm = root.querySelector('[data-path-confirm]');
  let removePath = false;
  async function refreshPath() {
    if (!api.userPathPlan) return;
    pathAdd.disabled = true; pathRemove.disabled = true;
    try {
      const state = await api.userPathPlan();
      root.querySelector('[data-path-directory]').textContent = state.directory;
      root.querySelector('[data-path-reason]').textContent = state.reason;
      pathAdd.disabled = busy || !state.can_add;
      pathRemove.disabled = busy || !state.can_remove;
    } catch { root.querySelector('[data-path-reason]').textContent = '无法检查用户 PATH，未修改。请重新检查。'; }
  }
  const pathCancel = root.querySelector('[data-action="path-cancel"]');
  let releasePath = null;
  function closePath(options) {
    releasePath?.(options);
    releasePath = null;
    pathConfirm.hidden = true;
  }
  function openPath(remove, trigger) {
    closePath({ restoreFocus: false });
    removePath = remove;
    releasePath = openConfirm(pathConfirm, { trigger, cancel: pathCancel, onCancel: () => closePath() });
  }
  pathAdd.addEventListener('click', () => openPath(false, pathAdd));
  pathRemove.addEventListener('click', () => openPath(true, pathRemove));
  pathCancel.addEventListener('click', () => closePath());
  root.querySelector('[data-action="path-confirm"]').addEventListener('click', async () => {
    if (busy) return;
    busy = true; closePath(); pathAdd.disabled = true; pathRemove.disabled = true;
    const result = root.querySelector('[data-path-result]');
    try {
      const outcome = await api.userPathChange(removePath, true);
      const status = await api.detect();
      result.textContent = `${outcome.status}；当前应用：${status.app.status}；新用户环境：${status.user.status}。请重启终端或 Agent 宿主。`;
    } catch (error) { result.textContent = typeof error === 'string' ? error : '用户 PATH 修改未确认，请重新检查；原有或被修改项目会保留。'; }
    finally { busy = false; await refreshPath(); }
  });

  async function refresh() {
    plan.disabled = true;
    try { renderPlan(await api.installPlan()); await refreshPath(); }
    catch { renderPlan({ status: 'unavailable', reason: '无法检查安装计划，请重新检查。' }); }
    finally { plan.disabled = busy; }
  }

  // Runs one mutating action (install, update or uninstall) and always re-reads the plan afterwards.
  async function run(label, failLabel, call, successWhen, successText, unconfirmed = '请求失败，未确认操作结果，请重新检查。') {
    if (busy) return;
    busy = true; install.disabled = true; update.disabled = true; uninstall.disabled = true; plan.disabled = true;
    root.querySelector('[data-status="result"]').textContent = label;
    root.querySelector('[data-info="reason"]').textContent = '';
    renderSteps([]);
    try {
      const outcome = await call();
      renderSteps(outcome.steps || []);
      if (successWhen(outcome)) {
        root.querySelector('[data-status="result"]').textContent = successText(outcome);
        root.querySelector('[data-info="path-hint"]').textContent = outcome.path_hint || '';
      } else {
        root.querySelector('[data-status="result"]').textContent = statusLabels[outcome.status] || failLabel;
        root.querySelector('[data-info="reason"]').textContent = outcome.reason || '操作未完成，已保留原有状态。';
      }
    } catch {
      root.querySelector('[data-status="result"]').textContent = failLabel;
      root.querySelector('[data-info="reason"]').textContent = unconfirmed;
    } finally {
      busy = false; plan.disabled = false;
      await refresh();
    }
  }

  install.addEventListener('click', () => run('正在安装', '安装失败', () => api.install(),
    o => o.status === 'installed', o => `安装成功 v${o.version}`, '安装请求失败，未确认安装结果，请重新检查。'));
  update.addEventListener('click', () => run('正在更新', '更新失败', () => api.update(),
    o => o.status === 'installed', o => `更新成功 v${o.version}`));
  uninstall.addEventListener('click', () => {
    closeUninstall({ restoreFocus: false });
    releaseUninstall = openConfirm(confirmBox, { trigger: uninstall, cancel: uninstallCancel, onCancel: () => closeUninstall() });
  });
  uninstallCancel.addEventListener('click', () => closeUninstall());
  root.querySelector('[data-action="uninstall-confirm"]').addEventListener('click', () => {
    closeUninstall();
    run('正在卸载', '卸载失败', () => api.uninstall(), o => o.status === 'uninstalled', () => '已卸载 CLI，配置与 Skill 已保留');
  });
  plan.addEventListener('click', refresh);
  await refresh();
  return { dispose() {} };
}
