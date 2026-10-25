// 抓取链排序交互：Pointer Events 拖动 + 键盘拾取。
// 说明：不用 HTML5 drag-and-drop，用 pointer capture 统一鼠标/触摸；
// 拖动中 DOM 保持稳定，只用 .drop-before/.drop-after 标记落点，drop 才提交。
// 外部拖动载荷不会触发 pointerdown，天然被忽略。
// happy-dom 等无布局环境下 getBoundingClientRect 全为 0，此时退回 elementFromPoint；
// 两者都无法命中时视为无落点，drop 为 no-op。

const ITEM = '[data-chain-row]';
const HANDLE = '.scrape-drag-handle';

/**
 * @param {object} options
 * @param {HTMLElement} options.list
 * @param {Document} options.doc
 * @param {() => boolean} options.isEnabled
 * @param {(from: number, to: number, name?: string) => void} options.onCommit
 * @param {(message: string) => void} [options.announce]
 */
export function createChainSorter({ list, doc, isEnabled, onCommit, announce = (/** @type {string} */ message) => {} }) {
  let drag = null; // { mode, pointerId, row, handle, from }
  let pointerMove = null;
  let pointerUp = null;

  const rows = () => [...list.querySelectorAll(ITEM)];
  const indexOf = row => rows().indexOf(row);
  const labelOf = row => row?.querySelector('.scrape-backend-title strong')?.textContent || row?.getAttribute('data-chain-row') || '';

  function clearDropHints() {
    for (const row of rows()) row.classList.remove('drop-before', 'drop-after');
  }

  function detachPointer() {
    if (drag?.handle && pointerMove) {
      drag.handle.removeEventListener('pointermove', pointerMove);
      drag.handle.removeEventListener('pointerup', pointerUp);
      drag.handle.removeEventListener('pointercancel', pointerUp);
    }
    pointerMove = null;
    pointerUp = null;
  }

  function cleanup() {
    if (!drag) return;
    detachPointer();
    drag.row.classList.remove('is-dragging');
    drag.handle?.setAttribute('aria-pressed', 'false');
    clearDropHints();
    drag = null;
  }

  // 键盘模式把行真实移回原位；指针模式从未动过 DOM。
  function revertKeyboard() {
    if (!drag || drag.mode !== 'keyboard') return;
    const target = rows()[drag.from];
    if (target && target !== drag.row) list.insertBefore(drag.row, target);
    else if (!target) list.append(drag.row);
  }

  function cancel(message = '已取消拖动，顺序未变化') {
    if (!drag) return;
    revertKeyboard();
    cleanup();
    announce(message);
  }

  // 键盘 drop：当前 DOM 位置即目标位置。
  function commitKeyboard() {
    const { from } = drag;
    const to = indexOf(drag.row);
    const label = labelOf(drag.row);
    const handle = drag.handle;
    const name = drag.row.getAttribute('data-chain-row');
    cleanup();
    if (to === from) {
      announce(`${label} 仍在第 ${from + 1} 位，顺序未变化`);
      handle?.focus?.();
      return;
    }
    onCommit(from, to, name);
  }

  // 指针 drop：把落点行折算成移除源行后的目标下标。
  function commitPointer(target) {
    const { from, row } = drag;
    const label = labelOf(row);
    cleanup();
    if (!target) {
      announce(`${label} 已放回第 ${from + 1} 位，顺序未变化`);
      return;
    }
    let to = indexOf(target.row) + (target.before ? 0 : 1);
    if (to > from) to -= 1;
    if (to === from) {
      announce(`${label} 仍在第 ${from + 1} 位，顺序未变化`);
      return;
    }
    onCommit(from, to, row.getAttribute('data-chain-row'));
  }

  function start(row, handle, mode, pointerId) {
    if (drag || !isEnabled() || handle.disabled) return false;
    const from = indexOf(row);
    if (from < 0) return false;
    drag = { mode, pointerId, row, handle, from };
    row.classList.add('is-dragging');
    handle.setAttribute('aria-pressed', 'true');
    return true;
  }

  // 落点解析：优先按各行矩形中线；布局缺省（全 0 矩形）时退回 elementFromPoint。
  function dropTarget(x, y) {
    const rs = rows().filter(row => row !== drag.row);
    if (!rs.length) return null;
    let measurable = false;
    for (const row of rs) {
      const rect = row.getBoundingClientRect();
      if (rect.height > 0 || rect.top !== 0 || rect.bottom !== 0) measurable = true;
      if (y < rect.top + rect.height / 2) return { row, before: true };
    }
    if (measurable) return { row: rs[rs.length - 1], before: false };
    const el = doc.elementFromPoint?.(x, y);
    const hit = el?.closest?.(ITEM);
    if (hit && hit !== drag.row && list.contains(hit)) {
      const rect = hit.getBoundingClientRect();
      return { row: hit, before: rect.height ? y < rect.top + rect.height / 2 : true };
    }
    return null;
  }

  function onPointerDown(event) {
    const handle = event.target?.closest?.(HANDLE);
    if (!handle || !list.contains(handle)) return;
    // 只认主按钮；happy-dom 的 PointerEvent.isPrimary 恒为 false，不能据此拒绝。
    if ((event.button ?? 0) !== 0) return;
    const row = handle.closest(ITEM);
    if (!row || !start(row, handle, 'pointer', event.pointerId)) return;
    event.preventDefault();
    try { handle.setPointerCapture?.(event.pointerId); } catch { /* 无布局测试环境 */ }
    pointerMove = moveEvent => {
      if (!drag || moveEvent.pointerId !== drag.pointerId) return;
      const target = dropTarget(moveEvent.clientX, moveEvent.clientY);
      clearDropHints();
      if (target) target.row.classList.add(target.before ? 'drop-before' : 'drop-after');
    };
    pointerUp = upEvent => {
      if (!drag || upEvent.pointerId !== drag.pointerId) return;
      if (upEvent.type === 'pointercancel') { cancel(); return; }
      commitPointer(dropTarget(upEvent.clientX, upEvent.clientY));
    };
    drag.handle.addEventListener('pointermove', pointerMove);
    drag.handle.addEventListener('pointerup', pointerUp);
    drag.handle.addEventListener('pointercancel', pointerUp);
    announce(`已拿起 ${labelOf(row)}，拖动到目标位置后松开`);
  }

  function moveDragged(delta) {
    const rs = rows();
    const at = rs.indexOf(drag.row);
    const to = Math.min(rs.length - 1, Math.max(0, at + delta));
    if (to === at) return;
    if (to < at) list.insertBefore(drag.row, rs[to]);
    else list.insertBefore(drag.row, rs[to].nextSibling);
    announce(`${labelOf(drag.row)} 移到第 ${to + 1} 位，回车放下，Escape 取消`);
  }

  function onKeyDown(event) {
    const handle = event.target?.closest?.(HANDLE);
    if (!handle || !list.contains(handle)) return;
    const key = event.key;
    if (!drag) {
      if (key !== ' ' && key !== 'Enter') return;
      const row = handle.closest(ITEM);
      if (!row || !start(row, handle, 'keyboard', null)) return;
      event.preventDefault();
      announce(`已拿起 ${labelOf(row)}，用方向键调整位置，回车放下，Escape 取消`);
      return;
    }
    if (drag.mode !== 'keyboard' || handle !== drag.handle) return;
    if (key === 'ArrowUp' || key === 'ArrowDown') {
      event.preventDefault();
      moveDragged(key === 'ArrowUp' ? -1 : 1);
    } else if (key === 'Home' || key === 'End') {
      event.preventDefault();
      const rs = rows();
      if (key === 'Home' && rs[0] !== drag.row) list.insertBefore(drag.row, rs[0]);
      if (key === 'End' && rs[rs.length - 1] !== drag.row) list.append(drag.row);
      announce(`${labelOf(drag.row)} 移到第 ${indexOf(drag.row) + 1} 位，回车放下，Escape 取消`);
    } else if (key === 'Enter' || key === ' ') {
      event.preventDefault();
      droppingOn = handle;
      commitKeyboard();
      droppingOn = null;
    } else if (key === 'Escape') {
      event.preventDefault();
      cancel();
    }
  }

  // keydown Enter 用于拾取和放下。某些环境（happy-dom）中 handle.click() /
  // 键盘激活会同步派发额外的 Enter 事件；“正在放下”的 Enter 按下期间用
  // droppingOn 把回声挡在捕获阶段，避免重复提交。
  let droppingOn = null;
  function onKeyDownCapture(event) {
    if (droppingOn && event.key === 'Enter' && event.target === droppingOn) event.stopPropagation();
  }

  list.addEventListener('pointerdown', onPointerDown);
  list.addEventListener('keydown', onKeyDownCapture, true);
  list.addEventListener('keydown', onKeyDown);

  return {
    cancel,
    get dragging() { return Boolean(drag); },
    dispose() {
      cancel('已结束排序');
      list.removeEventListener('pointerdown', onPointerDown);
      list.removeEventListener('keydown', onKeyDownCapture, true);
      list.removeEventListener('keydown', onKeyDown);
    },
  };
}
