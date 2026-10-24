import { pages } from './pages.js';
import { managementApi, normalizeError } from './api.js';

const RUNTIME_MISSING = '此页面需要在 Multi Search 桌面应用中打开。';
const MOUNT_FAILED = '页面加载失败';
export const APP_TITLE = 'Multi Search';

/// After a page mounts, keyboard and screen-reader users land on its heading and the window
/// title names the page. The initial load keeps focus where the browser put it.
export function announcePage(root, page, { moveFocus = true } = {}) {
  root.ownerDocument.title = `${page.label} · ${APP_TITLE}`;
  const heading = root.querySelector('h1');
  if (!heading) return;
  if (!heading.id) heading.id = `page-title-${page.id}`;
  root.setAttribute('aria-labelledby', heading.id);
  if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
  if (moveFocus) heading.focus();
}

export function createNavigation(root, nav, invoke, pageList = pages) {
  const doc = root.ownerDocument;
  let generation = 0;
  let mounted = null;
  let controller = null;

  function markCurrent(id) {
    for (const button of nav.children) button.setAttribute('aria-current', button.dataset.page === id ? 'page' : 'false');
  }

  function safeDispose(instance) {
    try { instance?.dispose?.(); } catch { /* a page must not break navigation */ }
  }

  function showMessage(message) {
    const section = doc.createElement('section');
    section.className = 'page-error panel';
    section.setAttribute('role', 'alert');
    const text = doc.createElement('p');
    text.textContent = message;
    section.append(text);
    root.replaceChildren(section);
  }

  function showMountFailure(page, error, retry) {
    controller?.abort();
    const section = doc.createElement('section');
    section.className = 'page-error panel';
    section.setAttribute('role', 'alert');
    const heading = doc.createElement('h2');
    heading.textContent = MOUNT_FAILED;
    const message = doc.createElement('p');
    message.textContent = `${page.label}无法显示：${normalizeError(error, '未知错误').message}`;
    const button = doc.createElement('button');
    button.type = 'button';
    button.className = 'primary';
    button.dataset.action = 'retry';
    button.textContent = '重新加载';
    button.addEventListener('click', retry);
    section.append(heading, message, button);
    root.replaceChildren(section);
  }

  async function select(page, { moveFocus = true } = {}) {
    const token = ++generation;
    controller?.abort();
    controller = new AbortController();
    safeDispose(mounted);
    mounted = null;
    markCurrent(page.id);
    if (!invoke) {
      showMessage(RUNTIME_MISSING);
      doc.title = APP_TITLE;
      return;
    }
    // Each navigation owns a detached container until it wins the race. A stale mount can
    // therefore write all it wants without replacing the page the user is looking at.
    const container = doc.createElement('div');
    container.className = 'page-view';
    container.dataset.page = page.id;
    root.replaceChildren(container);
    try {
      const instance = await page.mount(container, managementApi(invoke), { number: page.number, signal: controller.signal });
      if (token !== generation) {
        safeDispose(instance);
        return;
      }
      mounted = instance;
      announcePage(root, page, { moveFocus });
    } catch (error) {
      if (token !== generation) return;
      showMountFailure(page, error, () => { void select(page); });
    }
  }

  for (const page of pageList) {
    const button = doc.createElement('button');
    button.type = 'button';
    button.dataset.page = page.id;
    const number = doc.createElement('span');
    number.textContent = page.number;
    number.setAttribute('aria-hidden', 'true');
    button.append(number, doc.createTextNode(page.label));
    button.addEventListener('click', () => { void select(page); });
    nav.append(button);
  }

  return {
    select,
    dispose() {
      generation += 1;
      controller?.abort();
      safeDispose(mounted);
      mounted = null;
    },
  };
}

/// Alias kept for callers written against the accessibility branch's name.
export const createApp = createNavigation;

export async function start(root = document.querySelector('#page'), nav = document.querySelector('[data-navigation]')) {
  // withGlobalTauri is off: no global Tauri API object is injected. Only the IPC bridge Tauri always
  // injects is used, and the capability file limits it to this app's own typed commands.
  const bridge = window.__TAURI_INTERNALS__;
  const invoke = typeof bridge?.invoke === 'function' ? (cmd, args) => bridge.invoke(cmd, args) : null;
  const navigation = createNavigation(root, nav, invoke);
  await navigation.select(pages[0], { moveFocus: false });
  return navigation;
}

// Importing this module in a DOM test must not boot the application.
if (typeof document !== 'undefined' && typeof window !== 'undefined') await start();
