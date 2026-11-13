// Native dashboard login keeps HttpOnly cookies out of the frontend. Search keys
// stay editable through the existing credential editor; these logins only query usage.
import { showError } from './api.js';
import { SOURCE_CATALOG } from './source-catalog.js';

export function dashboardMethodForSource(source) {
  const plugin = SOURCE_CATALOG.plugins.find(item => item.id === source
    || item.search_sources?.includes(source) || item.scrape_channels?.includes(source));
  return plugin?.auth_methods?.some(method => method.type === 'web') ? plugin : null;
}

/** @param {HTMLElement} root @param {any} api @param {{source?: string, onComplete?: () => Promise<void>|void}} [options] */
export async function mountDashboardLogin(root, api, { source, onComplete } = {}) {
  const plugin = dashboardMethodForSource(source);
  if (!plugin || typeof api?.dashboardLogin !== 'function' || typeof api?.dashboardLoginCancel !== 'function') {
    root.hidden = true;
    return { dispose() {} };
  }
  root.hidden = false;
  root.innerHTML = `<section class="oauth-login" data-dashboard-login>
    <div class="oauth-login-head"><div><h3>控制台登录</h3><p class="oauth-login-sub">登录后查询账户真实用量与余额。</p></div>
    <div class="oauth-login-actions"><button type="button" class="primary" data-dashboard-start>登录控制台</button><button type="button" data-dashboard-cancel hidden>取消登录</button></div></div>
    <p class="oauth-login-status" data-dashboard-status role="status" aria-live="polite"></p>
    <p class="error-message" data-dashboard-error role="alert"></p></section>`;
  const start = /** @type {HTMLButtonElement} */ (root.querySelector('[data-dashboard-start]'));
  const cancel = /** @type {HTMLButtonElement} */ (root.querySelector('[data-dashboard-cancel]'));
  const status = root.querySelector('[data-dashboard-status]');
  const errorSlot = root.querySelector('[data-dashboard-error]');
  const view = root.ownerDocument.defaultView;
  let disposed = false, active = false, cancelling = false;
  function render() {
    start.hidden = active;
    start.disabled = active;
    cancel.hidden = !active;
    cancel.disabled = cancelling;
    root.setAttribute('aria-busy', String(active));
  }
  async function cancelLogin() {
    if (!active || cancelling || disposed) return;
    cancelling = true; render();
    try { await api.dashboardLoginCancel(plugin.id); }
    catch (error) { if (!disposed) showError(errorSlot, error, '取消登录失败，请关闭登录窗口。'); }
    finally { cancelling = false; if (!disposed) render(); }
  }
  start.addEventListener('click', async () => {
    if (active || disposed) return;
    active = true; render();
    errorSlot.textContent = ''; errorSlot.removeAttribute('title');
    status.textContent = '请在新窗口完成登录…';
    try {
      const completed = await api.dashboardLogin(plugin.id);
      if (disposed) return;
      if (!completed) { status.textContent = '已取消登录。'; return; }
      status.textContent = '登录已保存，正在读取用量…';
      // Force one fresh observation after a new login, even if a local estimate
      // is still within its TTL. Normal refreshes keep provider rate limits.
      try {
        await api.balanceView?.(plugin.id, true);
        await onComplete?.();
        if (!disposed) status.textContent = '登录完成，用量已刷新。';
      } catch (error) {
        if (!disposed) {
          status.textContent = '登录已保存。';
          showError(errorSlot, error, '登录已保存，但用量读取失败，请手动刷新。');
        }
      }
    } catch (error) {
      if (!disposed) { status.textContent = ''; showError(errorSlot, error, '控制台登录失败，请重试。'); }
    } finally { active = false; if (!disposed) render(); }
  });
  cancel.addEventListener('click', () => void cancelLogin());
  function dispose() {
    if (disposed) return;
    disposed = true;
    view?.removeEventListener('pagehide', dispose);
    if (active) void api.dashboardLoginCancel(plugin.id).catch(() => {});
    root.replaceChildren();
  }
  view?.addEventListener('pagehide', dispose);
  return { dispose };
}
