// Cookie 导入页：把 Twitter / X 的 Cookie 文件复制为 ~/.multi-search/twitter-cookies.json。
//
// Cookie 内容永不经过这个 UI：页面只接收用户选择的文件路径和状态。错误一律经
// `showError` 规范化成中文，加载中禁用全部变更控件，确认面板走共享键盘契约。

import { el, confirmInline, pageRoot, disposePage } from './dom.js';
import { showError } from './api.js';

const MANAGED_FILE = '~/.multi-search/twitter-cookies.json';

export async function mountCookies(root, api, { number = '07' } = {}) {
  root = pageRoot(root);
  const doc = root.ownerDocument;
  root.innerHTML = `<section class="heading"><p class="eyebrow">${number} / COOKIES</p><h1 tabindex="-1">Cookie 导入。</h1>
      <p>校验 Twitter / X 的 Cookie 文件后复制到 ${MANAGED_FILE}，并把设置中的 Cookie 文件路径指向它。</p></section>
    <section class="panel"><div class="section-title"><h2>Twitter / X Cookie</h2><span class="eyebrow">FILE</span></div>
    <p class="status-text" data-cookie-status role="status" aria-live="polite">正在读取 Cookie 状态…</p>
    <p class="note" data-cookie-configured></p>
    <p class="note">Cookie 以明文保存在 ${MANAGED_FILE}（仅当前用户可读写）。文件需要包含 auth_token 与 ct0。</p>
    <label>待导入的 Cookie 文件路径<input data-cookie-path type="text" autocomplete="off" spellcheck="false" placeholder="例如 D:/secure/twitter-cookies.json"></label>
    <div class="run-controls"><button type="button" data-cookie-import disabled>导入 Cookie</button><button type="button" data-cookie-delete disabled>删除</button><button type="button" data-cookie-refresh>刷新状态</button></div>
    <p class="note">导入不会修改或删除原文件，请自行处理原文件；本页不读取或显示 Cookie 内容。删除只移除 ${MANAGED_FILE}，并在设置指向它时清空 Cookie 文件路径。</p>
    <p class="error-message" data-cookie-error role="alert"></p><div data-cookie-confirm></div></section>`;
  const q = selector => /** @type {any} */ (root.querySelector(selector));
  let disposed = false;
  let busy = false;
  let status = null;
  let closeConfirm = () => {};

  // Controls stay disabled while a request is in flight, so a double click can never send a second
  // import or delete; the status paragraph is the single place loading state is announced.
  function setBusy(value) {
    busy = value;
    root.setAttribute('aria-busy', String(value));
    q('[data-cookie-status]').classList.toggle('is-busy', value);
    q('[data-cookie-import]').disabled = value || !status;
    q('[data-cookie-delete]').disabled = value || !status?.present;
    q('[data-cookie-refresh]').disabled = value;
    q('[data-cookie-path]').disabled = value || !status;
    for (const button of root.querySelectorAll('[data-cookie-confirm] button')) button.disabled = value;
  }

  function render(view) {
    if (disposed) return;
    status = view;
    q('[data-cookie-status]').textContent = view.present ? `已导入：${view.path || MANAGED_FILE}` : '尚未导入 Cookie';
    q('[data-cookie-configured]').textContent = view.configured_path
      ? `设置中的 Cookie 文件：${view.configured_path}`
      : '设置中没有 Cookie 文件路径。';
  }

  async function refresh() {
    if (busy || disposed) return;
    setBusy(true);
    closeConfirm();
    q('[data-cookie-error]').textContent = '';
    try { render(await api.cookieStatus()); }
    catch (error) {
      if (!disposed) {
        status = null;
        q('[data-cookie-status]').textContent = 'Cookie 状态未知。';
        showError(q('[data-cookie-error]'), error, '无法读取 Cookie 状态，请重试。');
      }
    } finally { if (!disposed) setBusy(false); }
  }

  function confirm(kind) {
    if (busy || disposed || !status || (kind === 'delete' && !status.present)) return;
    closeConfirm();
    const path = q('[data-cookie-path]').value.trim();
    if (kind === 'import' && !path) {
      q('[data-cookie-error]').textContent = '请先填写待导入文件路径。';
      return;
    }
    const holder = q('[data-cookie-confirm]');
    const panel = el(doc, 'div', { class: 'inline-confirm', role: 'group' });
    panel.append(el(doc, 'p', {}, kind === 'import'
      ? `确认从 ${path} 导入？已导入的 Cookie 将被替换；原文件不会被修改或删除。`
      : `确认删除 ${MANAGED_FILE}？此操作不可撤销。`));
    const yes = el(doc, 'button', { type: 'button', class: kind === 'delete' ? 'danger' : 'primary', 'data-cookie-confirm-yes': '' }, kind === 'import' ? '确认导入' : '确认删除');
    const no = el(doc, 'button', { type: 'button', 'data-cookie-confirm-cancel': '', 'data-action': 'cancel-cookie' }, '取消');
    panel.append(yes, no);
    holder.append(panel);
    // Shared contract: the safe choice gets focus, Escape cancels, focus returns to the trigger.
    const restore = confirmInline(panel, () => closeConfirm());
    closeConfirm = () => { holder.replaceChildren(); restore(); closeConfirm = () => {}; };
    no.addEventListener('click', closeConfirm);
    yes.addEventListener('click', async () => {
      if (busy || disposed) return;
      setBusy(true);
      q('[data-cookie-error]').textContent = '';
      try {
        const view = kind === 'import' ? await api.cookieImport(path, true) : await api.cookieDelete(true);
        if (disposed) return;
        render(view);
        if (kind === 'import') q('[data-cookie-path]').value = '';
      } catch (error) {
        if (!disposed) showError(q('[data-cookie-error]'), error, kind === 'import' ? '导入失败，原文件与已导入的 Cookie 都没有改动。' : '删除失败，请重试。');
      } finally { if (!disposed) { closeConfirm(); setBusy(false); } }
    });
  }

  q('[data-cookie-import]').addEventListener('click', () => confirm('import'));
  q('[data-cookie-delete]').addEventListener('click', () => confirm('delete'));
  q('[data-cookie-refresh]').addEventListener('click', () => { void refresh(); });
  await refresh();
  return {
    dispose() {
      disposed = true;
      closeConfirm();
      disposePage(root);
      root.replaceChildren();
    },
  };
}
