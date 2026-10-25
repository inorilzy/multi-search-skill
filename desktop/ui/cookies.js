// Cookie 托管页：只在本机托管 Twitter / X 的 Cookie 文件。
//
// Cookie 内容永不经过这个 UI：页面只接收用户选择的文件路径和托管状态。错误一律经
// `showError` 规范化成中文，加载中禁用全部变更控件，确认面板走共享键盘契约。

import { el, confirmInline, pageRoot, disposePage } from './dom.js';
import { showError } from './api.js';

const MODE_TEXT = { managed: '加密托管（managed）', file: '文件兼容（file）' };

export async function mountCookies(root, api, { number = '07' } = {}) {
  root = pageRoot(root);
  const doc = root.ownerDocument;
  root.innerHTML = `<section class="heading"><p class="eyebrow">${number} / COOKIES</p><h1 tabindex="-1">Cookie 托管。</h1>
      <p>把 Twitter / X 的明文 Cookie 文件导入为当前系统用户加密托管的凭据；抓取时不再读取旧文件。</p></section>
    <section class="panel"><div class="section-title"><h2>Twitter / X Cookie</h2><span class="eyebrow">DPAPI / SQLITE</span></div>
    <p class="status-text" data-cookie-status role="status" aria-live="polite">正在读取托管状态…</p>
    <p class="note">文件兼容模式（file）从原文件读取明文 Cookie，其他可访问该文件的程序也可能读取。加密托管（managed）仅适用于 Windows 当前用户的 DPAPI；不会自动切换模式或回退到旧文件。</p>
    <label>待导入的 Cookie 文件路径<input data-cookie-path type="text" autocomplete="off" spellcheck="false" placeholder="例如 D:/secure/twitter-cookies.json"></label>
    <div class="run-controls"><button type="button" data-cookie-import disabled>导入加密托管</button><button type="button" data-cookie-delete disabled>删除托管 Cookie</button><button type="button" data-cookie-refresh>刷新状态</button></div>
    <p class="note">导入不会修改或删除原文件。请自行妥善处理原文件及其他明文副本；本页不读取或显示 Cookie 内容。删除后保持 managed 模式且不可用，不会使用旧文件。</p>
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
    q('[data-cookie-import]').disabled = value || !status?.supported;
    q('[data-cookie-delete]').disabled = value || !status?.supported || !status?.present;
    q('[data-cookie-refresh]').disabled = value;
    q('[data-cookie-path]').disabled = value || !status?.supported;
    for (const button of root.querySelectorAll('[data-cookie-confirm] button')) button.disabled = value;
  }

  function render(view) {
    if (disposed) return;
    status = view;
    const mode = MODE_TEXT[view.mode] || String(view.mode);
    q('[data-cookie-status]').textContent = `${mode} · ${view.present ? '已有托管 Cookie' : '没有托管 Cookie'}`
      + (view.supported ? '' : '。此平台不支持加密导入；Linux 仅可显式使用文件兼容模式。');
  }

  async function refresh() {
    if (busy || disposed) return;
    setBusy(true);
    closeConfirm();
    q('[data-cookie-error]').textContent = '';
    try { render(await api.cookieStatus()); }
    catch (error) {
      if (!disposed) {
        // Fail closed: an unreadable status never selects a mode on its own.
        status = null;
        q('[data-cookie-status]').textContent = '托管状态未知，不会自动切换模式。';
        showError(q('[data-cookie-error]'), error, '无法读取 Cookie 托管状态，请重试。');
      }
    } finally { if (!disposed) setBusy(false); }
  }

  function confirm(kind) {
    if (busy || disposed || !status || (kind === 'import' ? !status.supported : !status.present)) return;
    closeConfirm();
    const path = q('[data-cookie-path]').value.trim();
    if (kind === 'import' && !path) {
      q('[data-cookie-error]').textContent = '请先填写待导入文件路径。';
      return;
    }
    const holder = q('[data-cookie-confirm]');
    const panel = el(doc, 'div', { class: 'inline-confirm', role: 'group' });
    panel.append(el(doc, 'p', {}, kind === 'import'
      ? `确认从 ${path} 导入并切换到 managed？已有托管 Cookie 将被替换；原文件不会被修改或删除。`
      : '确认删除已托管的 Cookie？此操作不可撤销。模式保持 managed，不会回退到旧明文文件。'));
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
        if (!disposed) showError(q('[data-cookie-error]'), error, kind === 'import' ? '导入失败，原文件与已有托管 Cookie 都没有改动。' : '删除失败，仍保持托管模式。');
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
