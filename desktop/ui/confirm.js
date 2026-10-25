// Keyboard and screen-reader behaviour shared by every in-page confirmation panel:
// - the panel is a labelled group whose message is announced when it opens;
// - focus moves to the safe choice (cancel) so a destructive action is never one Enter away;
// - Esc cancels;
// - closing returns focus to the control that opened the panel, unless the user already
//   moved focus somewhere else on purpose.
let sequence = 0;

/**
 * @param {HTMLElement} panel
 * @param {{ trigger?: HTMLElement & { disabled?: boolean }, cancel?: HTMLElement, onCancel?: () => void, message?: HTMLElement }} [options]
 */
export function openConfirm(panel, { trigger, cancel, onCancel, message } = {}) {
  const doc = panel.ownerDocument;
  const messageNode = message || panel.querySelector('p');
  if (messageNode) {
    if (!messageNode.id) messageNode.id = `confirm-message-${++sequence}`;
    panel.setAttribute('aria-labelledby', messageNode.id);
  }
  panel.setAttribute('role', 'group');
  panel.setAttribute('aria-live', 'assertive');
  panel.hidden = false;
  const onKey = event => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    onCancel?.();
  };
  panel.addEventListener('keydown', onKey);
  (cancel || panel.querySelector('button'))?.focus();
  let closed = false;
  return function close({ restoreFocus = true } = {}) {
    if (closed) return;
    closed = true;
    panel.removeEventListener('keydown', onKey);
    const active = doc.activeElement;
    const focusWasInside = !active || active === doc.body || panel.contains(active);
    if (restoreFocus && focusWasInside && trigger?.isConnected && !trigger.disabled) trigger.focus();
  };
}
