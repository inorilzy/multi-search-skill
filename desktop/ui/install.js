const statusLabels = {
  ready: '可安装',
  installed: '已由本工具安装',
  unconfigured: '未配置受控发布来源',
  prerequisite_missing: '缺少安装前提',
  integrity_failed: '完整性校验失败',
  unknown_existing: '已有未知安装，未修改',
  unavailable: '不可用',
  failed: '安装失败',
  already_installed: '已安装，未覆盖',
};

export async function mountInstall(root, api) {
  root.innerHTML = `<section class="heading"><p class="eyebrow">02 / INSTALL CLI</p><h1>安装命令行工具。</h1><p>从受控来源安装并校验。未知安装不会被覆盖，失败不会改动已有可用版本。</p></section>
    <section class="panel install"><div class="section-title"><h2>安装计划</h2><button type="button" data-action="plan">重新检查</button></div>
      <strong data-status="plan" aria-live="polite">检查中</strong>
      <dl class="install-plan"><dt>安装目录</dt><dd data-info="root"></dd><dt>可执行文件</dt><dd data-info="bin"></dd><dt>版本</dt><dd data-info="version"></dd></dl>
      <p data-info="path-hint" class="note"></p><p data-info="reason" role="alert"></p>
      <div class="run-controls"><button type="button" data-action="install" class="primary" disabled>安装 CLI</button><strong data-status="result" aria-live="polite"></strong></div>
      <ol data-steps aria-label="安装步骤"></ol></section>`;
  const install = root.querySelector('[data-action="install"]');
  const plan = root.querySelector('[data-action="plan"]');
  let busy = false;

  function renderPlan(status) {
    root.querySelector('[data-status="plan"]').textContent = statusLabels[status.status] || status.status;
    root.querySelector('[data-status="plan"]').dataset.kind = status.status;
    root.querySelector('[data-info="root"]').textContent = status.root || '';
    root.querySelector('[data-info="bin"]').textContent = status.bin || '';
    root.querySelector('[data-info="version"]').textContent = status.version ? `v${status.version}` : '';
    root.querySelector('[data-info="path-hint"]').textContent = ['ready', 'installed'].includes(status.status) ? status.path_hint : '';
    // A ready plan must not erase the reason of the previous install result.
    if (status.status !== 'ready') root.querySelector('[data-info="reason"]').textContent = status.reason || '';
    install.disabled = busy || status.status !== 'ready';
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

  install.addEventListener('click', async () => {
    if (busy) return;
    busy = true; install.disabled = true; plan.disabled = true;
    root.querySelector('[data-status="result"]').textContent = '正在安装';
    root.querySelector('[data-info="reason"]').textContent = '';
    renderSteps([]);
    try {
      const outcome = await api.install();
      renderSteps(outcome.steps || []);
      if (outcome.status === 'installed') {
        root.querySelector('[data-status="result"]').textContent = `安装成功 v${outcome.version}`;
        root.querySelector('[data-info="path-hint"]').textContent = outcome.path_hint;
      } else {
        root.querySelector('[data-status="result"]').textContent = statusLabels[outcome.status] || '安装失败';
        root.querySelector('[data-info="reason"]').textContent = outcome.reason || '安装未完成，已保留原有状态。';
      }
    } catch {
      root.querySelector('[data-status="result"]').textContent = '安装失败';
      root.querySelector('[data-info="reason"]').textContent = '安装请求失败，未确认安装结果，请重新检查。';
    } finally {
      busy = false; plan.disabled = false;
      await refresh();
    }
  });
  plan.addEventListener('click', refresh);
  await refresh();
  return { dispose() {} };
}
