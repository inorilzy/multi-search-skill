// @ts-check
// Shared DOM helpers for the modular pages.
//
// Confirmation panels have exactly one keyboard contract in this UI (see `confirm.js`): the safe
// choice gets focus, Escape cancels, and focus returns to the control that opened the panel.
// `confirmInline` is the shorthand the ported pages use, so they all inherit that contract instead
// of implementing their own.
import { openConfirm } from './confirm.js';

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

/**
 * Wire an inline confirmation panel to the shared keyboard contract.
 * @param {HTMLElement} panel
 * @param {() => void} close called for Escape and after the panel is dismissed
 * @param {HTMLElement|null} [trigger]
 */
export function confirmInline(panel, close, trigger = /** @type {HTMLElement|null} */ (panel.ownerDocument.activeElement)) {
  activeConfirms.get(panel)?.();
  // The safe choice is any cancel/keep control; a panel without one focuses its first button.
  const cancel = /** @type {HTMLElement|null} */ (panel.querySelector('button[data-action*="cancel"], button[data-action*="keep"]'))
    || /** @type {HTMLElement|null} */ (panel.querySelector('button'));
  const restore = openConfirm(panel, { trigger: trigger || undefined, cancel: cancel || undefined, onCancel: close });
  const wrapped = () => { restore(); activeConfirms.delete(panel); };
  activeConfirms.set(panel, wrapped);
  return wrapped;
}

/**
 * A page owns its child container: late callbacks can never query a successor page.
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
        // A panel the page already wired explicitly keeps its own contract; never wire it twice.
        if (confirmations.has(panel) || activeConfirms.has(panel)) continue;
        const restore = confirmInline(/** @type {HTMLElement} */ (panel), () => panel.querySelector('button[data-action*="cancel"], button[data-action*="keep"]')?.dispatchEvent(new win.MouseEvent('click', { bubbles: true })));
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
    enhance();
  }
  return root;
}
