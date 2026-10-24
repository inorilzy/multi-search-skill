import { pages } from './pages.js';
import { managementApi, errorReason } from './api.js';

const RUNTIME_MISSING = '此页面需要在 Multi Search 桌面应用中打开。';
const MOUNT_FAILED = '页面加载失败';

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
    message.textContent = `${page.label}无法显示：${errorReason(error, '未知错误')}`;
    const button = doc.createElement('button');
    button.type = 'button';
    button.className = 'primary';
    button.dataset.action = 'retry';
    button.textContent = '重新加载';
    button.addEventListener('click', retry);
    section.append(heading, message, button);
    root.replaceChildren(section);
  }

  async function select(page) {
    const token = ++generation;
    controller?.abort();
    controller = new AbortController();
    safeDispose(mounted);
    mounted = null;
    markCurrent(page.id);
    if (!invoke) {
      showMessage(RUNTIME_MISSING);
      return;
    }
    // Each navigation owns a detached container until it wins the race. A stale mount can
    // therefore write all it wants without replacing the page the user is looking at.
    const container = doc.createElement('div');
    container.className = 'page-view';
    container.dataset.page = page.id;
    root.replaceChildren(container);
    try {
      const instance = await page.mount(container, managementApi(invoke), { signal: controller.signal });
      if (token !== generation) {
        safeDispose(instance);
        return;
      }
      mounted = instance;
    } catch (error) {
      if (token !== generation) return;
      showMountFailure(page, error, () => { void select(page); });
    }
  }

  for (const page of pageList) {
    const button = doc.createElement('button');
    button.dataset.page = page.id;
    const number = doc.createElement('span');
    number.textContent = page.number;
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

export async function start(root = document.querySelector('#page'), nav = document.querySelector('[data-navigation]')) {
  // withGlobalTauri is off: no global Tauri API object is injected. Only the IPC bridge Tauri always
  // injects is used, and the capability file limits it to this app's own typed commands.
  const bridge = window.__TAURI_INTERNALS__;
  const invoke = typeof bridge?.invoke === 'function' ? (cmd, args) => bridge.invoke(cmd, args) : null;
  const navigation = createNavigation(root, nav, invoke);
  await navigation.select(pages[0]);
  return navigation;
}

// Importing this module in a DOM test must not boot the application.
if (typeof document !== 'undefined' && typeof window !== 'undefined') await start();
