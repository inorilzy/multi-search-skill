import { ROUTES, SEARCH_SOURCES } from './catalog.js';
import { errorReason } from './api.js';

const statusLabels = { ready: '可调用', missing: '未发现', not_executable: '不可执行', version_failed: '版本检查失败', unavailable: '不可用' };
const routeOptions = ROUTES.map(({ name, label }) => `<option value="${name}">${label} / ${name}</option>`).join('');
const sourceOptions = [
  '<option value="">按路由配置</option>',
  ...SEARCH_SOURCES.map(source => `<option value="${source.name}">${source.label}${source.keyed ? '' : '（无 key）'}</option>`),
].join('');
export async function mountDiagnostics(root, api, { pollInterval = 150, signal } = {}) {
  root.innerHTML = `<section class="heading"><p class="eyebrow">01 / LOCAL RUNTIME</p><h1>搜索，从本机开始。</h1><p>桌面应用只负责管理。搜索由独立 CLI 按需执行，关闭窗口后仍可使用。</p></section>
    <section class="runtime panel"><div class="section-title"><h2>CLI 概览</h2><button type="button" data-action="refresh">重新检测</button></div>
      <p class="note">测试搜索使用 <strong data-status="execution-cli">检测中</strong><span data-info="execution-cli"></span></p>
      <div class="discovery-grid"><article><span class="eyebrow">APP INVOCATION</span><h3>应用调用</h3><strong data-status="app">检测中</strong><p data-info="app"></p></article><article><span class="eyebrow">FRESH USER ENVIRONMENT</span><h3>用户命令发现</h3><strong data-status="user">检测中</strong><p data-info="user"></p></article></div>
      <p data-info="restart" class="note"></p><p data-info="error" role="alert"></p></section>
    <section class="panel test-search"><div class="section-title"><h2>一次测试搜索</h2><span class="eyebrow">ON DEMAND / NO SERVICE</span></div>
      <form data-search-form><label>搜索词<input data-field="query" required maxlength="2000" placeholder="例如：Python SQLite 缓存"></label>
      <div class="search-options"><label>路由<select data-field="route">${routeOptions}</select></label><label>搜索源<select data-field="sources">${sourceOptions}</select></label><label>超时 / 秒<input data-field="timeout" type="number" min="1" max="60" value="15"></label></div>
      <div class="run-controls"><button type="submit" data-action="search" class="primary" disabled>开始测试</button><button type="button" data-action="cancel" disabled>取消本次执行</button><strong data-status="execution" aria-live="polite">等待测试</strong></div></form>
      <p data-execution-error role="alert"></p><pre data-results tabindex="0" aria-label="搜索结果">结果会显示在这里。</pre></section>`;
  let appReady = false, activeId = null, timer = null, disposed = false, starting = false, cancelling = false;
  const search = root.querySelector('[data-action="search"]');
  const cancel = root.querySelector('[data-action="cancel"]');
  const executionError = root.querySelector('[data-execution-error]');
  function controls(running) { search.disabled = running || !appReady || cancelling; cancel.disabled = !running || cancelling; root.querySelector('[data-action="refresh"]').disabled = running; }
  function setExecutionError(message) { executionError.textContent = message; }
  function renderExecution(status) {
    const labels = { running: '正在执行', success: '搜索成功', empty: '没有结果', partial: '部分来源失败', failed: '执行失败', cancelled: '已取消', timed_out: '执行超时' };
    root.querySelector('[data-status="execution"]').textContent = labels[status.status] || '执行失败';
    setExecutionError(status.error || '');
    if (status.payload) root.querySelector('[data-results]').textContent = JSON.stringify(status.payload, null, 2);
    controls(status.status === 'running');
  }
  async function poll() {
    if (disposed || activeId === null) return;
    const id = activeId;
    try {
      const state = await api.poll(id);
      if (disposed || activeId !== id) return;
      renderExecution(state);
      if (state.status === 'running') timer = setTimeout(poll, pollInterval); else activeId = null;
    } catch (error) {
      if (!disposed && activeId === id) {
        setExecutionError(`无法读取执行状态：${errorReason(error, '请稍后重试或取消本次执行。')}`);
        cancel.disabled = false;
      }
    }
  }
  async function requestCancel() {
    if (disposed || activeId === null || cancelling) return;
    const id = activeId;
    cancelling = true;
    clearTimeout(timer);
    cancel.disabled = true;
    search.disabled = true;
    try {
      const state = await api.cancel(id);
      if (disposed) return;
      // A late response belongs to the execution the user just left behind.
      if (activeId !== id) return;
      activeId = null;
      renderExecution(state);
    } catch (error) {
      if (disposed) return;
      activeId = null;
      root.querySelector('[data-status="execution"]').textContent = '等待测试';
      setExecutionError(`取消失败：${errorReason(error, '无法取消本次执行。')} 状态已复位，可重新发起测试搜索。`);
    } finally {
      if (!disposed) {
        cancelling = false;
        controls(false);
      }
    }
  }
  root.querySelector('[data-search-form]').addEventListener('submit', async event => {
    event.preventDefault(); if (!appReady || activeId !== null || starting || cancelling) return;
    starting = true; controls(true); root.querySelector('[data-results]').textContent = '';
    renderExecution({ status: 'running' });
    try {
      const id = await api.start({ query: root.querySelector('[data-field="query"]').value, route: root.querySelector('[data-field="route"]').value, sources: root.querySelector('[data-field="sources"]').value.split(',').filter(Boolean), timeout: Number(root.querySelector('[data-field="timeout"]').value) });
      if (disposed) { await Promise.resolve(api.cancel(id)).catch(() => {}); return; }
      activeId = id; await poll();
    } catch (error) {
      if (disposed) return;
      activeId = null;
      renderExecution({ status: 'failed', error: `启动失败：${errorReason(error, '请检查 CLI 与搜索参数后重试。')}` });
    } finally { starting = false; }
  });
  cancel.addEventListener('click', () => { void requestCancel(); });
  async function detect() {
    const button = root.querySelector('[data-action="refresh"]'); button.disabled = true;
    try {
      const status = await api.detect();
      if (disposed) return;
      // Ready means exactly what the backend will run: the managed install first, then PATH.
      const execution = status.execution || { status: 'missing' };
      const app = status.app ?? { status: 'unavailable' };
      const user = status.user ?? { status: 'unavailable' };
      appReady = execution.status === 'ready'; controls(activeId !== null);
      root.querySelector('[data-status="execution-cli"]').textContent = execution.status === 'ready'
        ? (status.managed ? '受管安装的 CLI' : 'PATH 中发现的 CLI')
        : `无可用 CLI（${statusLabels[execution.status] || execution.status}）`;
      root.querySelector('[data-info="execution-cli"]').textContent = execution.path ? `：${execution.path}` : '';
      for (const [scope, row] of [['app', app], ['user', user]]) {
        root.querySelector(`[data-status="${scope}"]`).textContent = statusLabels[row.status] || row.status;
        root.querySelector(`[data-status="${scope}"]`).dataset.kind = row.status;
        root.querySelector(`[data-info="${scope}"]`).textContent = [row.version && `v${row.version}`, row.path, row.reason].filter(Boolean).join('\n');
      }
      const reasons = [app.status, user.status];
      root.querySelector('[data-info="restart"]').textContent = status.restart_required
        ? '用户环境已可发现 CLI；本次测试可直接使用新路径。应用继承的旧 PATH 未改变，请重启终端或 Agent 宿主。'
        : reasons.includes('version_failed')
          ? '已找到 CLI，但版本检测未通过。请更新 CLI 后点击“重新检测”；已有 uv 安装需通过 uv 更新，桌面安装不会覆盖它。'
          : reasons.includes('not_executable') || reasons.includes('unavailable')
            ? 'CLI 未通过执行检测。请先按上方原因检查文件权限或运行时，或在“安装”页重新安装受管 CLI，再重新检测。'
            : user.status === 'missing'
              ? '用户环境未发现 CLI。请检查用户 PATH；更新后重启终端或 Agent 宿主。'
              : '新终端可以发现 CLI。已打开的终端或 Agent 宿主如仍不可用，请重启后重试。';
      root.querySelector('[data-info="error"]').textContent = '';
    } catch (error) {
      if (disposed) return;
      appReady = false; controls(false);
      root.querySelector('[data-info="error"]').textContent = `检测失败：${errorReason(error, '请重新检测。')}`;
    } finally { if (!disposed) button.disabled = false; }
  }
  root.querySelector('[data-action="refresh"]').addEventListener('click', detect);
  function dispose() {
    if (disposed) return;
    disposed = true;
    clearTimeout(timer);
    const id = activeId;
    activeId = null;
    signal?.removeEventListener('abort', dispose);
    if (id !== null) {
      try { Promise.resolve(api.cancel(id)).catch(() => {}); } catch { /* page is already gone */ }
    }
  }
  signal?.addEventListener('abort', dispose, { once: true });
  await detect();
  return { dispose };
}
