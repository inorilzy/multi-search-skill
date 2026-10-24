import { pages } from './pages.js';
import { managementApi } from './api.js';

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

export function createApp(root, nav, invoke, pageList = pages) {
  const doc = root.ownerDocument;
  let mounted;
  async function select(page, { moveFocus = true } = {}) {
    mounted?.dispose();
    for (const button of nav.children) button.setAttribute('aria-current', button.dataset.page === page.id ? 'page' : 'false');
    if (!invoke) { root.textContent = '此页面需要在 Multi Search 桌面应用中打开。'; doc.title = APP_TITLE; return; }
    mounted = await page.mount(root, managementApi(invoke), { number: page.number });
    announcePage(root, page, { moveFocus });
  }
  for (const page of pageList) {
    const button = doc.createElement('button'); button.type = 'button'; button.dataset.page = page.id;
    const number = doc.createElement('span'); number.textContent = page.number; number.setAttribute('aria-hidden', 'true');
    button.append(number, doc.createTextNode(page.label)); button.addEventListener('click', () => select(page)); nav.append(button);
  }
  return { select };
}

// Importing this module in a DOM test must not boot the application.
if (typeof window !== 'undefined' && window.document?.querySelector('#page')) {
  const app = createApp(document.querySelector('#page'), document.querySelector('[data-navigation]'), window.__TAURI__?.core?.invoke);
  await app.select(pages[0], { moveFocus: false });
}
