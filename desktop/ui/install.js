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

export async function mountInstall(root, api) {
  root.innerHTML = `<section class="heading"><p class="eyebrow">02 / INSTALL CLI</p><h1>安装命令行工具。</h1><p>从受控来源安装并校验。未知安装不会被覆盖，失败不会改动已有可用版本。</p></section>
    <section class="panel install"><div class="section-title"><h2>安装计划</h2><button type="button" data-action="plan">重新检查</button></div>
      <strong data-status="plan" aria-live="polite">检查中</strong>
      <dl class="install-plan"><dt>安装目录</dt><dd data-info="root"></dd><dt>可执行文件</dt><dd data-info="bin"></dd><dt>版本</dt><dd data-info="version"></dd><dt>当前版本</dt><dd data-info="current-version"></dd><dt>安装来源</dt><dd data-info="source"></dd><dt>Skill 兼容性</dt><dd data-info="compatibility"></dd></dl>
      <p data-info="path-hint" class="note"></p><p data-info="reason" role="alert"></p>
      <div class="run-controls"><button type="button" data-action="install" class="primary" disabled>安装 CLI</button><button type="button" data-action="update" disabled>更新 CLI</button><button type="button" data-action="uninstall" disabled>卸载 CLI</button><strong data-status="result" aria-live="polite"></strong></div>
      <div class="run-controls" data-confirm hidden><strong>卸载只删除本工具安装的 CLI 文件；配置、凭据和 Skill 会保留。</strong><button type="button" data-action="uninstall-confirm" class="danger">确认卸载</button><button type="button" data-action="uninstall-cancel">取消</button></div>
      <ol data-steps aria-label="安装步骤"></ol></section>`;
  const install = root.querySelector('[data-action="install"]');
  const update = root.querySelector('[data-action="update"]');
  const uninstall = root.querySelector('[data-action="uninstall"]');
  const confirmBox = root.querySelector('[data-confirm]');
  const plan = root.querySelector('[data-action="plan"]');
  let busy = false;

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
    if (status.status !== 'installed') confirmBox.hidden = true;
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

  async function refresh() {
    plan.disabled = true;
    try { renderPlan(await api.installPlan()); }
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
  uninstall.addEventListener('click', () => { confirmBox.hidden = false; });
  root.querySelector('[data-action="uninstall-cancel"]').addEventListener('click', () => { confirmBox.hidden = true; });
  root.querySelector('[data-action="uninstall-confirm"]').addEventListener('click', () => {
    confirmBox.hidden = true;
    run('正在卸载', '卸载失败', () => api.uninstall(), o => o.status === 'uninstalled', () => '已卸载 CLI，配置与 Skill 已保留');
  });
  plan.addEventListener('click', refresh);
  await refresh();
  return { dispose() {} };
}
