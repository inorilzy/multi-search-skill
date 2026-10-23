// @ts-check
const pageObservers = new WeakMap();
const activeConfirms = new WeakMap();
/** @param {HTMLElement} root */
export function disposePage(root) { pageObservers.get(root)?.disconnect(); pageObservers.delete(root); }
/** @param {Document} doc @param {string} tag @param {Record<string, string>} [attrs] @param {string} [value] */
export function el(doc, tag, attrs = {}, value = '') {
  const node = doc.createElement(tag);
  for (const [key, val] of Object.entries(attrs)) node.setAttribute(key, val);
  node.textContent = value;
  return node;
}
/** @template {Element} T @param {ParentNode} root @param {string} selector @returns {T} */
export function q(root, selector) {
  const node = root.querySelector(selector);
  if (!node) throw new Error(`Missing UI element: ${selector}`);
  return /** @type {T} */ (node);
}
/** @param {Element} node @param {unknown} value */
export function text(node, value) { node.textContent = String(value ?? ''); }

/** Shared focus contract for both generated and static inline confirmation panels.
 * @param {HTMLElement} panel @param {() => void} close
 * @param {HTMLElement|null} [trigger]
 */
export function confirmInline(panel, close, trigger = /** @type {HTMLElement|null} */ (panel.ownerDocument.activeElement)) {
  activeConfirms.get(panel)?.();
  panel.setAttribute('role', 'group');
  panel.setAttribute('aria-label', '确认操作');
  const onKey = (/** @type {KeyboardEvent} */ event) => {
    if (event.key === 'Escape') { event.preventDefault(); close(); trigger?.focus(); }
  };
  const onClick = (/** @type {MouseEvent} */ event) => {
    const button = /** @type {Element} */ (event.target)?.closest('button');
    if (button && /cancel|keep/.test(button.getAttribute('data-action') || '')) trigger?.focus();
  };
  panel.addEventListener('keydown', onKey);
  panel.addEventListener('click', onClick);
  panel.querySelector('button')?.focus();
  const restore = () => {
    panel.removeEventListener('keydown', onKey); panel.removeEventListener('click', onClick);
    activeConfirms.delete(panel); if (trigger?.isConnected) trigger.focus();
  };
  activeConfirms.set(panel, restore);
  return restore;
}

/** A page owns its child container: late callbacks can never query a successor page.
 * @param {HTMLElement} parent
 */
export function pageRoot(parent) {
  const root = parent.ownerDocument.createElement('div');
  root.className = 'page-content';
  parent.replaceChildren(root);
  const win = parent.ownerDocument.defaultView;
  if (win) {
    const confirmations = new WeakMap();
    const enhance = () => {
      for (const node of root.querySelectorAll('div[aria-label]:not([role]), pre[aria-label]:not([role])')) node.setAttribute('role', 'group');
      for (const node of root.querySelectorAll('.status-text:not([role])')) node.setAttribute('role', 'status');
      for (const panel of root.querySelectorAll('.inline-confirm, .refresh-confirm')) {
        if (confirmations.has(panel)) continue;
        const restore = confirmInline(/** @type {HTMLElement} */ (panel), () => panel.querySelector('button[data-action^="cancel"], button[data-action^="keep"]')?.dispatchEvent(new win.MouseEvent('click', { bubbles: true })));
        confirmations.set(panel, restore);
      }
    };
    const observer = new win.MutationObserver(records => {
      enhance();
      for (const record of records) for (const node of record.removedNodes) {
        if (node.nodeType === 1) {
          const element = /** @type {Element} */ (node);
          confirmations.get(element)?.();
          for (const panel of element.querySelectorAll('.inline-confirm, .refresh-confirm')) confirmations.get(panel)?.();
        }
      }
    });
    observer.observe(root, { childList: true, subtree: true });
    pageObservers.set(root, observer);
  }
  return root;
}
