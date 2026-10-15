const statusLabels = { ready: '可调用', missing: '未发现', not_executable: '不可执行', version_failed: '版本检查失败', unavailable: '不可用' };
export async function mountDiagnostics(root, api, { pollInterval = 150 } = {}) {
  const doc = root.ownerDocument;
  root.innerHTML = `<section class="heading"><p class="eyebrow">01 / LOCAL RUNTIME</p><h1>搜索，从本机开始。</h1><p>桌面应用只负责管理。搜索由独立 CLI 按需执行，关闭窗口后仍可使用。</p></section>
    <section class="runtime panel"><div class="section-title"><h2>CLI 概览</h2><button type="button" data-action="refresh">重新检测</button></div>
      <label class="path-input">指定已安装的 CLI <input data-field="path" placeholder="可选：C:\\…\\multi-search.exe" spellcheck="false"></label>
      <div class="discovery-grid"><article><span class="eyebrow">APP INVOCATION</span><h3>应用调用</h3><strong data-status="app">检测中</strong><p data-info="app"></p></article><article><span class="eyebrow">FRESH USER ENVIRONMENT</span><h3>用户命令发现</h3><strong data-status="user">检测中</strong><p data-info="user"></p></article></div>
      <p data-info="restart" class="note"></p><p data-info="error" role="alert"></p></section>
    <section class="panel test-search"><div class="section-title"><h2>一次测试搜索</h2><span class="eyebrow">ON DEMAND / NO SERVICE</span></div>
      <form data-search-form><label>搜索词<input data-field="query" required maxlength="2000" placeholder="例如：Python SQLite 缓存"></label>
      <div class="search-options"><label>路由<select data-field="route" disabled></select></label><label>搜索源<select data-field="sources"><option value="">按路由配置</option><option value="hackernews">Hacker News（无 key）</option><option value="hackernews,brave">Hacker News + Brave</option><option value="github_repos">GitHub</option><option value="brave">Brave</option><option value="exa">Exa</option><option value="tavily">Tavily</option></select></label><label>超时 / 秒<input data-field="timeout" type="number" min="1" max="90" value="15" disabled></label></div>
      <p data-info="settings-error" role="alert"></p><div class="run-controls"><button type="submit" data-action="search" class="primary" disabled>开始测试</button><button type="button" data-action="cancel" disabled>取消本次执行</button><strong data-status="execution" aria-live="polite">等待测试</strong></div></form>
      <p data-execution-error role="alert"></p><pre data-results tabindex="0" aria-label="搜索结果">结果会显示在这里。</pre></section>`;
  const path = root.querySelector('[data-field="path"]');
  const routeField = root.querySelector('[data-field="route"]');
  const timeoutField = root.querySelector('[data-field="timeout"]');
  let appReady = false, settingsReady = false, settingsView = null, activeId = null, timer = null, disposed = false, starting = false;
  const search = root.querySelector('[data-action="search"]');
  const cancel = root.querySelector('[data-action="cancel"]');
  function controls(running) {
    search.disabled = running || !appReady || !settingsReady;
    cancel.disabled = !running;
    path.disabled = running;
    routeField.disabled = running || !settingsReady;
    timeoutField.disabled = running || !settingsReady;
    root.querySelector('[data-field="sources"]').disabled = running || !settingsReady;
    root.querySelector('[data-action="refresh"]').disabled = running;
  }
  function renderExecution(status) {
    const labels = { running: '正在执行', success: '搜索成功', empty: '没有结果', partial: '部分来源失败', failed: '执行失败', cancelled: '已取消', timed_out: '执行超时' };
    root.querySelector('[data-status="execution"]').textContent = labels[status.status] || '执行失败';
    root.querySelector('[data-execution-error]').textContent = status.error || '';
    if (status.payload) root.querySelector('[data-results]').textContent = JSON.stringify(status.payload, null, 2);
    controls(status.status === 'running');
  }
  async function poll() {
    if (disposed || activeId === null) return;
    const id = activeId;
    try { const state = await api.poll(id); if (disposed || activeId !== id) return; renderExecution(state); if (state.status === 'running') timer = setTimeout(poll, pollInterval); else activeId = null; }
    catch { if (!disposed && activeId === id) { root.querySelector('[data-execution-error]').textContent = '无法读取执行状态，请取消后重试。'; cancel.disabled = false; } }
  }
  root.querySelector('[data-search-form]').addEventListener('submit', async event => {
    event.preventDefault(); if (!appReady || !settingsReady || activeId !== null || starting) return;
    const timeout = Number(timeoutField.value);
    const effective = routeTimeout(routeField.value);
    if (!Number.isInteger(timeout) || timeout < 1 || (timeout > 60 && timeout !== effective)) {
      root.querySelector('[data-execution-error]').textContent = effective > 60
        ? `超时只能填写 1–60 秒，或使用当前分组的实际默认值 ${effective} 秒。`
        : '超时只能填写 1–60 秒。';
      return;
    }
    starting = true; controls(true); root.querySelector('[data-results]').textContent = '';
    renderExecution({ status: 'running' });
    try { activeId = await api.start(path.value.trim() || null, { query: root.querySelector('[data-field="query"]').value, route: routeField.value, sources: root.querySelector('[data-field="sources"]').value.split(',').filter(Boolean), timeout }); await poll(); }
    catch { activeId = null; renderExecution({ status: 'failed', error: '启动失败，请检查 CLI 与搜索参数后重试。' }); }
    finally { starting = false; }
  });
  cancel.addEventListener('click', async () => { if (activeId === null) return; cancel.disabled = true; clearTimeout(timer); try { renderExecution(await api.cancel(activeId)); activeId = null; } catch { root.querySelector('[data-execution-error]').textContent = '取消失败，请重试。'; cancel.disabled = false; } });

  function routeTimeout(id) {
    const currentRoutes = settingsView?.routes || {};
    if (!Object.hasOwn(currentRoutes, id)) return 60;
    const previews = settingsView?.effective_timeouts || {};
    if (Object.hasOwn(previews, id)) return Number(previews[id]);
    const route = currentRoutes[id];
    return id === settingsView.route ? settingsView.effective_timeout : route.timeout ?? settingsView.timeout;
  }
  function applyRouteTimeout(id) {
    const timeout = routeTimeout(id);
    timeoutField.value = String(timeout);
    timeoutField.max = String(Math.max(60, timeout));
    root.querySelector('[data-execution-error]').textContent = '';
  }
  function renderSettings(view) {
    settingsView = view;
    routeField.replaceChildren();
    const entries = Object.entries(view.routes || {});
    settingsReady = view.status !== 'config_unreadable' && entries.length > 0 && Object.hasOwn(view.routes || {}, view.route);
    if (!settingsReady) {
      root.querySelector('[data-info="settings-error"]').textContent = view.message || '搜索设置不可读，测试已禁用。';
      controls(activeId !== null);
      return;
    }
    for (const [id, route] of entries) {
      const option = doc.createElement('option');
      option.value = id;
      option.textContent = `${route.label} / ${id}`;
      option.selected = id === view.route;
      routeField.append(option);
    }
    routeField.value = view.route;
    applyRouteTimeout(view.route);
    root.querySelector('[data-info="settings-error"]').textContent = view.status === 'no_active_source' ? view.message : '';
    controls(activeId !== null);
  }
  routeField.addEventListener('change', () => { applyRouteTimeout(routeField.value); });

  async function loadSettings() {
    try { renderSettings(await api.settingsView()); }
    catch {
      settingsReady = false;
      settingsView = null;
      routeField.replaceChildren();
      root.querySelector('[data-info="settings-error"]').textContent = '无法读取搜索设置，测试已禁用；不会使用硬编码路由代替。';
      controls(activeId !== null);
    }
  }

  async function detect() {
    const button = root.querySelector('[data-action="refresh"]'); button.disabled = true;
    try {
      const status = await api.detect(path.value.trim() || null);
      appReady = status.app.status === 'ready' || (!path.value.trim() && status.user.status === 'ready'); controls(activeId !== null);
      for (const scope of ['app', 'user']) {
        const row = status[scope];
        root.querySelector(`[data-status="${scope}"]`).textContent = statusLabels[row.status] || row.status;
        root.querySelector(`[data-status="${scope}"]`).dataset.kind = row.status;
        root.querySelector(`[data-info="${scope}"]`).textContent = [row.version && `v${row.version}`, row.path, row.reason].filter(Boolean).join('\n');
      }
      const reasons = [status.app.status, status.user.status];
      root.querySelector('[data-info="restart"]').textContent = status.restart_required
        ? '用户环境已可发现 CLI；本次测试可直接使用新路径。应用继承的旧 PATH 未改变，请重启终端或 Agent 宿主。'
        : reasons.includes('version_failed')
          ? '已找到 CLI，但版本检测未通过。请更新 CLI 后点击“重新检测”；已有 uv 安装需通过 uv 更新，桌面安装不会覆盖它。'
          : reasons.includes('not_executable') || reasons.includes('unavailable')
            ? 'CLI 未通过执行检测。请先按上方原因检查文件权限、运行时或指定路径，再重新检测。'
            : status.user.status === 'missing'
              ? '用户环境未发现 CLI。请检查用户 PATH；更新后重启终端或 Agent 宿主。'
              : '新终端可以发现 CLI。已打开的终端或 Agent 宿主如仍不可用，请重启后重试。';
      root.querySelector('[data-info="error"]').textContent = '';
    } catch { appReady = false; controls(false); root.querySelector('[data-info="error"]').textContent = '检测失败，请重新检测。'; }
    finally { button.disabled = false; }
  }
  root.querySelector('[data-action="refresh"]').addEventListener('click', async () => { await Promise.all([detect(), loadSettings()]); });
  await Promise.all([detect(), loadSettings()]);
  return { dispose() { disposed = true; clearTimeout(timer); } };
}
