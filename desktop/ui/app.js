import { pages } from './pages.js';
import { managementApi } from './api.js';
const root = document.querySelector('#page');
const nav = document.querySelector('[data-navigation]');
// withGlobalTauri is off: no global Tauri API object is injected. Only the IPC bridge Tauri always
// injects is used, and the capability file limits it to this app's own typed commands.
const bridge = window.__TAURI_INTERNALS__;
const invoke = typeof bridge?.invoke === 'function' ? (cmd, args) => bridge.invoke(cmd, args) : null;
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
