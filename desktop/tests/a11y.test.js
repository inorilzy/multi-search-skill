import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Window } from 'happy-dom';
import { createApp, announcePage } from '../ui/app.js';
import { mountInstall } from '../ui/install.js';
import { mountCredentialBody } from '../ui/credentials.js';
import { mountSources, shortcutLabel } from '../ui/sources.js';
import { pages } from '../ui/pages.js';

const css = readFileSync(new URL('../ui/styles.css', import.meta.url), 'utf8');
const tauri = JSON.parse(readFileSync(new URL('../src-tauri/tauri.conf.json', import.meta.url), 'utf8'));
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root };
}

// WCAG 2.x relative luminance and contrast ratio.
function luminance(hex) {
  const channels = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}
function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
function tokens() {
  const blocks = [...css.matchAll(/:root\s*\{([^}]*)\}/g)];
  return { count: blocks.length, values: Object.fromEntries([...blocks[0][1].replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/--([\w-]+):\s*(#[0-9a-f]{6}|#[0-9a-f]{3})\b/gi)].map(m => [m[1], m[2].length === 4 ? `#${[...m[2].slice(1)].map(c => c + c).join('')}` : m[2]])) };
}

test('stylesheet has one token set, no !important and no long single-line rules', () => {
  assert.equal(tokens().count, 1, 'exactly one :root token block');
  assert.equal(css.includes('!important'), false);
  const longest = Math.max(...css.split('\n').map(line => line.length));
  assert.ok(longest <= 120, `longest line is ${longest} characters`);
  assert.match(css, /\[hidden\]\s*\{\s*display:\s*none;\s*\}/, 'hidden still wins, via the unlayered rule');
});

test('secondary and status text colours meet WCAG AA 4.5:1', () => {
  const { values } = tokens();
  for (const background of [values.panel, values.paper]) {
    for (const name of ['ink', 'muted', 'teal', 'red', 'amber']) {
      assert.ok(contrast(values[name], background) >= 4.5, `--${name} on ${background} is ${contrast(values[name], background).toFixed(2)}`);
    }
  }
  assert.ok(contrast('#ffffff', values.teal) >= 4.5, 'primary button text');
  assert.ok(contrast('#ffffff', values.red) >= 4.5, 'danger button text');
  // Every literal text colour inside light-surface rules must reach 4.5:1 against white.
  const darkSurfaces = /sidebar|nav button|brand|stat-symbol|source-icon|icon-|test-state-symbol|result-symbol|toggle-track/;
  let selector = '';
  for (const line of css.split('\n')) {
    const open = line.match(/^\s*(.+) \{$/);
    if (open) selector = open[1];
    const color = line.match(/^\s*color:\s*(#[0-9a-f]{6});/i);
    if (color && !darkSurfaces.test(selector)) {
      assert.ok(contrast(color[1], '#ffffff') >= 4.5, `${selector} color ${color[1]} is ${contrast(color[1], '#ffffff').toFixed(2)}`);
    }
  }
});

test('no text is smaller than 12px', () => {
  const sizes = [...css.matchAll(/font(?:-size)?:\s*(?:\d+\s+)?(\d+(?:\.\d+)?)px/g)].map(m => Number(m[1]));
  assert.ok(sizes.length > 20);
  assert.deepEqual(sizes.filter(size => size < 12), []);
});

test('minimum window width stays clear of every max-width breakpoint and the sidebar scrolls', () => {
  const window = tauri.app.windows[0];
  const breakpoints = [...css.matchAll(/@media \(max-width:\s*(\d+)px\)/g)].map(m => Number(m[1]));
  // The viewport is a little narrower than the outer window; keep at least 40px of margin.
  for (const breakpoint of breakpoints) {
    assert.ok(Math.abs(window.minWidth - breakpoint) >= 40, `minWidth ${window.minWidth} overlaps the ${breakpoint}px breakpoint`);
  }
  assert.ok(window.minWidth > 880, 'the narrow sidebar layout is never reachable at the minimum width');
  assert.match(css, /\.sidebar \{[^}]*overflow-y: auto;/);
});

test('uninstall confirmation focuses cancel, closes on Esc and returns focus to its trigger', async () => {
  const { window, root } = setup();
  let uninstalls = 0;
  await mountInstall(root, {
    installPlan: async () => ({ status: 'installed', root: 'C:/ms', bin: 'C:/ms/multi-search.exe', version: '0.4.0', path_hint: '' }),
    uninstall: async () => { uninstalls += 1; return { status: 'uninstalled', steps: [] }; },
  });
  const trigger = root.querySelector('[data-action="uninstall"]');
  trigger.focus();
  trigger.click();
  const panel = root.querySelector('[data-confirm]');
  assert.equal(panel.hidden, false);
  assert.equal(panel.getAttribute('role'), 'group');
  assert.match(window.document.getElementById(panel.getAttribute('aria-labelledby')).textContent, /配置、凭据和 Skill 会保留/);
  assert.equal(window.document.activeElement, root.querySelector('[data-action="uninstall-cancel"]'), 'the safe choice has focus');
  window.document.activeElement.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  assert.equal(panel.hidden, true);
  assert.equal(window.document.activeElement, trigger);
  assert.equal(uninstalls, 0, 'Esc never confirms');
  window.close();
});

test('PATH confirmation supports Esc and cancel with focus restore', async () => {
  const { window, root } = setup();
  await mountInstall(root, {
    installPlan: async () => ({ status: 'installed' }),
    userPathPlan: async () => ({ directory: 'C:/ms/bin', reason: '', can_add: true, can_remove: false }),
  });
  await flush();
  const add = root.querySelector('[data-action="path-add"]');
  add.click();
  const panel = root.querySelector('[data-path-confirm]');
  assert.equal(window.document.activeElement, root.querySelector('[data-action="path-cancel"]'));
  panel.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(panel.hidden, true);
  assert.equal(window.document.activeElement, add);
  window.close();
});

test('credential delete and save confirmations are keyboard operable', async () => {
  const { window, root } = setup();
  const overview = { store: { state: 'present', saved_at: 1, error: null }, effective_source: 'credential_store', env_overrides_store: false, env_var: '', file_key_count: 2 };
  let deletes = 0;
  await mountCredentialBody(root, {
    credentialStatus: async () => overview,
    credentialDelete: async () => { deletes += 1; return { ...overview, store: { state: 'absent' }, effective_source: 'file' }; },
    credentialSave: async () => overview,
  }, { source: 'tavily' });
  const remove = root.querySelector('[data-action="delete"]');
  remove.focus();
  remove.click();
  const panel = root.querySelector('[data-confirm="delete"]');
  assert.equal(panel.getAttribute('role'), 'group');
  assert.equal(window.document.activeElement, panel.querySelector('[data-action="cancel-delete"]'));
  panel.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(root.querySelector('[data-confirm="delete"]'), null);
  assert.equal(window.document.activeElement, remove);
  assert.equal(deletes, 0);

  remove.click();
  root.querySelector('[data-action="confirm-delete"]').click();
  await flush();
  assert.equal(deletes, 1);
  assert.equal(window.document.activeElement, remove, 'focus returns after the delete finishes');

  root.querySelector('[data-field="key"]').value = 'synthetic-a11y-key';
  root.querySelector('[data-save-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  const save = root.querySelector('[data-confirm="save"]');
  assert.match(save.textContent, /保存后使用凭据库 Key，文件中的 2 个 Key/);
  assert.equal(window.document.activeElement, save.querySelector('[data-action="cancel-save"]'));
  save.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(root.querySelector('[data-confirm="save"]'), null);
  assert.equal(window.document.activeElement, root.querySelector('[data-action="save"]'));
  window.close();
});

test('changing page focuses the new heading and updates the document title', async () => {
  const { window } = setup();
  const doc = window.document;
  const nav = doc.createElement('nav');
  const main = doc.createElement('main');
  doc.body.append(nav, main);
  const fake = (id, label, number) => ({ id, label, number, mount: async (root, _api, options) => {
    root.innerHTML = `<section class="heading"><p class="eyebrow">${options.number} / ${id.toUpperCase()}</p><h1>${label}</h1></section>`;
    return { dispose() {} };
  } });
  const list = [fake('one', '第一页', '01'), fake('two', '第二页', '02')];
  const app = createApp(main, nav, async () => null, list);
  await app.select(list[0], { moveFocus: false });
  assert.equal(doc.title, '第一页 · Multi Search');
  nav.querySelector('[data-page="two"]').focus();
  await app.select(list[1]);
  const heading = main.querySelector('h1');
  assert.equal(doc.activeElement, heading, 'focus moves from the nav to the page heading');
  assert.equal(heading.getAttribute('tabindex'), '-1');
  assert.equal(main.getAttribute('aria-labelledby'), heading.id);
  assert.equal(doc.title, '第二页 · Multi Search');
  assert.match(main.querySelector('.eyebrow').textContent, /^02 \//, 'eyebrow number comes from the page entry');
  assert.equal(nav.querySelector('[data-page="two"]').getAttribute('aria-current'), 'page');
  announcePage(main, list[0], { moveFocus: false });
  assert.equal(doc.title, '第一页 · Multi Search');
  window.close();
});

test('every page eyebrow uses its navigation number', async () => {
  const stubs = {
    detect: async () => ({ app: { status: 'missing' }, user: { status: 'missing' } }),
    installPlan: async () => ({ status: 'ready' }),
    skillPlan: async () => ({}),
    settingsView: async () => { throw 'offline'; },
    credentialStatus: async () => ({ store: { state: 'absent' }, effective_source: 'none' }),
  };
  for (const page of pages) {
    const { window, root } = setup();
    const mounted = await page.mount(root, stubs, { number: page.number });
    assert.match(root.querySelector('.eyebrow').textContent, new RegExp(`^${page.number} / `), page.id);
    assert.equal(root.querySelector('h1').getAttribute('tabindex'), '-1', `${page.id} heading is focusable`);
    mounted?.dispose?.();
    window.close();
  }
});

test('sources page expands nothing on entry and sends no extra status request', async () => {
  const { window, root } = setup();
  const statusCalls = [];
  const mounted = await mountSources(root, {
    settingsView: async () => ({ route: 'default', timeout: 60, disabled_sources: [], twitter_cookies_path: null }),
    credentialStatus: async source => { statusCalls.push(source); return { store: { state: 'absent' }, effective_source: 'none', env_var: '', file_key_count: 0 }; },
  });
  await flush();
  assert.equal(root.querySelectorAll('[data-source-row][data-expanded="true"]').length, 0);
  assert.equal(statusCalls.length, 8, 'one status read per keyed source, no automatic detail read');
  assert.equal(new Set(statusCalls).size, 8);
  mounted.dispose();
  window.close();
});

test('the credential summary has a real accessible text instead of an aria-label on a div', async () => {
  const { window, root } = setup();
  const mounted = await mountSources(root, {
    settingsView: async () => ({ route: 'default', timeout: 60, disabled_sources: [], twitter_cookies_path: null }),
    credentialStatus: async source => source === 'brave'
      ? { store: { state: 'present', saved_at: 1 }, effective_source: 'credential_store', env_var: '', file_key_count: 0 }
      : { store: { state: 'absent' }, effective_source: 'none', env_var: '', file_key_count: 0 },
  });
  for (const node of root.querySelectorAll('div[aria-label], span[aria-label]')) {
    assert.ok(node.getAttribute('role'), `${node.className} has aria-label without a role`);
  }
  const brave = root.querySelector('[data-source-row="brave"] .source-key');
  assert.equal(brave.querySelector('[data-key-summary]').getAttribute('aria-hidden'), 'true');
  assert.equal(brave.querySelector('.visually-hidden').textContent, 'API Key 已配置（不显示）');
  assert.equal(root.querySelector('[data-source-row="hackernews"] .visually-hidden').textContent, '无需配置');
  mounted.dispose();
  window.close();
});

test('shortcut hint follows the platform', async () => {
  assert.equal(shortcutLabel({ platform: 'MacIntel' }), '⌘ K');
  assert.equal(shortcutLabel({ userAgentData: { platform: 'macOS' } }), '⌘ K');
  assert.equal(shortcutLabel({ platform: 'Win32' }), 'Ctrl K');
  assert.equal(shortcutLabel({}), 'Ctrl K');
  const { window, root } = setup();
  const mounted = await mountSources(root, { settingsView: async () => { throw 'offline'; }, credentialStatus: async () => ({ store: { state: 'absent' }, effective_source: 'none' }) });
  const kbd = root.querySelector('.source-search kbd').textContent;
  assert.equal(kbd, shortcutLabel(window.navigator));
  assert.equal(root.querySelector('[data-search]').getAttribute('aria-keyshortcuts'), kbd === '⌘ K' ? 'Meta+K' : 'Control+K');
  mounted.dispose();
  window.close();
});

test('UI copy uses consistent Key/Cookie casing and spaces between Chinese and Latin text', () => {
  const files = ['credentials.js', 'sources.js', 'settings.js', 'migration.js', 'diagnostics.js', 'install.js', 'skill.js'];
  for (const file of files) {
    const source = readFileSync(new URL(`../ui/${file}`, import.meta.url), 'utf8');
    // Only user-facing strings: drop comments, then check text adjacent to CJK characters.
    const strings = source.replace(/^\s*\/\/.*$/gm, '').replace(/\$\{[^{}]*\}/g, '').match(/(['`])(?:\\.|(?!\1).)*\1/g) || [];
    for (const literal of strings.filter(text => /[\u4e00-\u9fff]/.test(text))) {
      assert.doesNotMatch(literal, /(^|[^\w-])key\b/, `${file}: lower-case "key" in ${literal}`);
      assert.doesNotMatch(literal, /(^|[^\w-])cookie\b/, `${file}: lower-case "cookie" in ${literal}`);
      assert.doesNotMatch(literal, /[\u4e00-\u9fff](?:Key|Cookie|Windows)|(?:Key|Cookie)[\u4e00-\u9fff]/, `${file}: missing space in ${literal}`);
    }
  }
});
