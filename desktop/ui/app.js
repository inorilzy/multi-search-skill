// @ts-check
import { pages } from './pages.js';
import { managementApi } from './api.js';
import { el } from './dom.js';
import { toMessage } from './errors.js';

/** @param {HTMLElement} root @param {HTMLElement} nav @param {any} api @param {typeof pages} [entries] */
export function createNavigation(root, nav, api, entries = pages) {
  const live = el(root.ownerDocument, 'p', { class: 'sr-only', role: 'alert', 'aria-atomic': 'true' });
  root.after(live);
  const observer = new MutationObserver(() => {
    const messages = [...root.querySelectorAll('.error-message')].map(node => node.textContent?.trim()).filter(Boolean).join('；');
    if (live.textContent !== messages) live.textContent = messages;
  });
  observer.observe(root, { childList: true, subtree: true, characterData: true });
  let revision = 0;
  /** @type {{dispose: () => void}|undefined} */
  let mounted;
  /** @param {typeof pages[number]} page */
  async function select(page) {
    const ticket = ++revision;
    mounted?.dispose(); mounted = undefined;
    for (const button of nav.querySelectorAll('button')) button.setAttribute('aria-current', button.dataset.page === page.id ? 'page' : 'false');
    const container = el(root.ownerDocument, 'div', { class: 'page-container', 'aria-busy': 'true' });
    root.replaceChildren(container);
    try {
      if (!api) throw new Error('此页面需要在 Multi Search 桌面应用中打开。');
      const result = await page.mount(container, api);
      if (ticket !== revision) { result?.dispose(); return; }
      mounted = result;
      const title = container.querySelector('h1');
      title?.setAttribute('tabindex', '-1'); title?.focus();
    } catch (error) {
      if (ticket !== revision) return;
      container.replaceChildren(el(root.ownerDocument, 'h1', { tabindex: '-1' }, '页面加载失败'), el(root.ownerDocument, 'p', { class: 'error-message' }, toMessage(error)));
      const retry = el(root.ownerDocument, 'button', { type: 'button' }, '重试');
      retry.addEventListener('click', () => { void select(page); });
      container.append(retry); container.querySelector('h1')?.focus();
    } finally { container.setAttribute('aria-busy', 'false'); }
  }
  for (const page of entries) {
    const button = el(root.ownerDocument, 'button', { type: 'button', 'data-page': page.id });
    button.append(el(root.ownerDocument, 'span', {}, page.number), root.ownerDocument.createTextNode(page.label));
    button.addEventListener('click', () => { void select(page); }); nav.append(button);
  }
  return { select, dispose() { revision++; mounted?.dispose(); observer.disconnect(); live.remove(); nav.replaceChildren(); } };
}
const root = document.querySelector('#page');
const nav = document.querySelector('[data-navigation]');
if (root instanceof HTMLElement && nav instanceof HTMLElement) {
  const invoke = /** @type {any} */ (window).__TAURI__?.core?.invoke;
  const navigation = createNavigation(root, nav, invoke ? managementApi(invoke) : null);
  void navigation.select(pages[0]);
}
