// Browser/device-code login panel for providers whose plugin declares an `oauth` auth method.
// The managed CLI owns the flow; this module only starts, polls and cancels it. Polling matches
// the test-search page, and leaving the page stops the timer and cancels the CLI child.
import { showError } from './api.js';
import { SOURCE_CATALOG } from './source-catalog.js';

const ACTIVE_PHASES = new Set(['starting', 'waiting']);
const PHASE_TEXT = {
  starting: '正在启动浏览器登录…',
  waiting: '等待浏览器授权…',
  complete: '登录完成，凭据与余额已刷新。',
  error: '登录失败',
  cancelled: '已取消登录。',
};
const START_LABEL = '浏览器登录';
const DEFAULT_POLL_INTERVAL = 150;

function pluginForSource(source) {
  return SOURCE_CATALOG.plugins.find(item =>
    item.id === source || item.search_sources?.includes(source) || item.scrape_channels?.includes(source));
}

/** The oauth auth method declared by the plugin that owns `source`, if any. */
export function oauthMethodForSource(source) {
  return pluginForSource(source)?.auth_methods?.find(method => method.type === 'oauth') || null;
}

const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[ch]);

/**
 * Mount the oauth login panel. The panel is omitted entirely for providers without an oauth
 * method or when the injected API predates the oauth commands.
 * @param {HTMLElement} root
 * @param {any} api
 * @param {{ source?: string, label?: string, pollInterval?: number, onComplete?: (status: any) => Promise<void>|void }} [options]
 */
export async function mountOAuthLogin(root, api, { source, label, pollInterval = DEFAULT_POLL_INTERVAL, onComplete } = {}) {
  const plugin = pluginForSource(source);
  const method = plugin?.auth_methods?.find(item => item.type === 'oauth');
  const doc = root.ownerDocument;
  if (!plugin || !method
    || typeof api?.oauthLoginStart !== 'function'
    || typeof api?.oauthLoginPoll !== 'function'
    || typeof api?.oauthLoginCancel !== 'function') {
    root.replaceChildren();
    root.hidden = true;
    return { dispose() {} };
  }
  const provider = plugin.id;
  root.hidden = false;
  const note = method.purpose === 'balance_only'
    ? '仅用于查看余额：设备码登录只保存账户令牌，不用于搜索。'
    : '在浏览器中完成授权后会自动保存凭据。';
  root.innerHTML = `<section class="oauth-login" data-oauth-login aria-label="${esc(label ?? plugin.label)} 浏览器登录">
    <div class="oauth-login-head"><div><h3>浏览器登录</h3><p class="oauth-login-sub">${esc(note)}</p></div>
    <div class="oauth-login-actions"><button type="button" class="primary" data-action="oauth-start">${START_LABEL}</button><button type="button" data-action="oauth-cancel" hidden>取消登录</button></div></div>
    <p class="oauth-login-status" data-oauth-status role="status" aria-live="polite">尚未登录。</p>
    <div class="oauth-login-code" data-oauth-code hidden><span class="oauth-login-code-label">设备码</span><code data-oauth-user-code></code><button type="button" data-action="copy-code">复制</button></div>
    <p class="oauth-login-copied" data-oauth-copy-status role="status"></p>
    <p class="error-message" data-info="oauth-error" role="alert"></p></section>`;
  const q = selector => /** @type {any} */ (root.querySelector(selector));
  const section = q('[data-oauth-login]');
  const statusNode = q('[data-oauth-status]');
  const startButton = q('[data-action="oauth-start"]');
  const cancelButton = q('[data-action="oauth-cancel"]');
  const codeBlock = q('[data-oauth-code]');
  const userCode = q('[data-oauth-user-code]');
  const copyStatus = q('[data-oauth-copy-status]');
  const errorSlot = q('[data-info="oauth-error"]');

  let id = null;
  let timer = null;
  let disposed = false;
  let starting = false;
  let cancelling = false;
  let generation = 0;
  let status = null;
  const view = root.ownerDocument.defaultView;

  function stopTimer() {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  }
  function clearError() {
    errorSlot.textContent = '';
    errorSlot.title = '';
  }
  function render(next) {
    if (disposed) return;
    status = next;
    const phase = next?.phase || 'idle';
    const active = ACTIVE_PHASES.has(phase);
    section.dataset.phase = phase;
    section.setAttribute('aria-busy', String(active));
    statusNode.textContent = phase === 'complete' && next.needs_search_key
      ? '登录完成。请为这个账号添加搜索 Key' : PHASE_TEXT[phase] || '尚未登录。';
    startButton.hidden = active;
    startButton.disabled = starting || active;
    cancelButton.hidden = !active;
    cancelButton.disabled = cancelling;
    const code = active && typeof next?.user_code === 'string' ? next.user_code : '';
    codeBlock.hidden = code === '';
    userCode.textContent = code;
  }
  render({ phase: 'idle' });

  async function poll(ticket) {
    if (disposed || ticket !== generation || id === null) return;
    try {
      const next = await api.oauthLoginPoll(id);
      if (disposed || ticket !== generation || id === null || next.id !== id) return;
      render(next);
      if (next.phase === 'complete') {
        id = null;
        stopTimer();
        clearError();
        try {
          await onComplete?.(next);
        } catch (error) {
          if (!disposed) showError(errorSlot, error, '登录已完成，但刷新凭据与余额失败，请手动刷新。');
        }
        return;
      }
      if (!ACTIVE_PHASES.has(next.phase)) {
        id = null;
        stopTimer();
        // The CLI's own message (already secret-scrubbed) is the diagnosis; showError
        // would replace a provider's English text with a generic line.
        if (next.phase === 'error') errorSlot.textContent = next.message || '登录失败，请重试。';
        else clearError();
        return;
      }
      timer = setTimeout(() => void poll(ticket), pollInterval);
    } catch (error) {
      if (disposed || ticket !== generation) return;
      const failedId = id;
      id = null;
      stopTimer();
      render({ phase: 'error' });
      showError(errorSlot, error, '登录状态读取失败，请重试。');
      // The managed login may still be running: make one best-effort cancel before letting the
      // user start another session.
      if (failedId !== null) void api.oauthLoginCancel(failedId).catch(() => {});
    }
  }

  async function start() {
    if (starting || disposed) return;
    starting = true;
    stopTimer();
    generation += 1;
    const ticket = generation;
    clearError();
    copyStatus.textContent = '';
    render({ provider, phase: 'starting' });
    try {
      const started = await api.oauthLoginStart(provider);
      if (disposed || ticket !== generation) {
        void api.oauthLoginCancel(started).catch(() => {});
        return;
      }
      id = started;
      await poll(ticket);
    } catch (error) {
      if (!disposed && ticket === generation) {
        id = null;
        render({ phase: 'idle' });
        showError(errorSlot, error, '启动浏览器登录失败，请检查 CLI 后重试。');
      }
    } finally {
      starting = false;
      if (!disposed) render(status);
    }
  }

  async function cancel() {
    if (cancelling || id === null || disposed) return;
    cancelling = true;
    stopTimer();
    const cancelId = id;
    render(status);
    try {
      const next = await api.oauthLoginCancel(cancelId);
      if (disposed) return;
      id = null;
      generation += 1;
      clearError();
      render(next);
    } catch (error) {
      if (!disposed) {
        showError(errorSlot, error, '取消登录失败，请重试。');
        // Cancellation was not confirmed: resume observing the session instead of pretending it ended.
        if (id === cancelId) timer = setTimeout(() => void poll(generation), pollInterval);
      }
    } finally {
      cancelling = false;
      if (!disposed) render(status);
    }
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    generation += 1;
    stopTimer();
    view?.removeEventListener?.('pagehide', dispose);
    const activeId = id;
    id = null;
    // Page unload/navigation must end the CLI child, not leave an orphan waiting for an authorization
    // nobody will complete.
    if (activeId !== null) void api.oauthLoginCancel(activeId).catch(() => {});
    root.replaceChildren();
    root.hidden = true;
  }
  startButton.addEventListener('click', () => void start());
  cancelButton.addEventListener('click', () => void cancel());
  q('[data-action="copy-code"]').addEventListener('click', async () => {
    const code = userCode.textContent;
    if (!code) return;
    try {
      const clipboard = view?.navigator?.clipboard;
      if (!clipboard?.writeText) throw new Error('clipboard unavailable');
      await clipboard.writeText(code);
      copyStatus.textContent = '设备码已复制。';
    } catch (error) {
      showError(errorSlot, error, '复制失败，请手动选择设备码复制。');
    }
  });
  // A real page unload bypasses the SPA's dispose chain; the same cleanup runs here.
  view?.addEventListener?.('pagehide', dispose);

  return { dispose };
}
