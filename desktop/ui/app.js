import { pages } from './pages.js';
import { managementApi } from './api.js';
const root = document.querySelector('#page');
const nav = document.querySelector('[data-navigation]');
const invoke = window.__TAURI__?.core?.invoke;
let mounted;
async function select(page) {
  mounted?.dispose();
  for (const button of nav.children) button.setAttribute('aria-current', button.dataset.page === page.id ? 'page' : 'false');
  if (!invoke) { root.textContent = '此页面需要在 Multi Search 桌面应用中打开。'; return; }
  mounted = await page.mount(root, managementApi(invoke));
}
for (const page of pages) {
  const button = document.createElement('button'); button.dataset.page = page.id;
  const number = document.createElement('span'); number.textContent = page.number;
  button.append(number, document.createTextNode(page.label)); button.addEventListener('click', () => select(page)); nav.append(button);
}
await select(pages[0]);
