import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountScrape } from '../ui/scrape.js';

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

const BUILTIN = ['jina', 'exa', 'tavily', 'firecrawl'];
const OPTIONS = [
  { name: 'jina', label: 'Jina Reader' },
  { name: 'exa', label: 'Exa' },
  { name: 'tavily', label: 'Tavily' },
  { name: 'firecrawl', label: 'Firecrawl' },
];

function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root };
}

function settingsView(overrides = {}) {
  return {
    config_path: 'C:/test/config.sqlite', path_source: 'user', file_present: true, read_source: 'sqlite',
    route: 'default', timeout: 60, timeout_configured: true, effective_timeout: 60,
    timeout_min: 1, timeout_max: 90, timeout_out_of_range: false, effective_timeouts: {},
    routes: {}, builtin_routes: {}, disabled_sources: [], unknown_disabled_sources: [],
    twitter_cookies_path: null,
    scrape_backends: [...BUILTIN], scrape_backends_invalid: false,
    builtin_scrape_backends: [...BUILTIN],
    scrape_backend_options: OPTIONS.map(option => ({ ...option })),
    active_sources: ['brave'], status: 'ok', message: '',
    ...overrides,
  };
}

function api(overrides = {}) {
  return {
    credentialStatus: async source => ({ source, store: { state: 'present', saved_at: null, error: '' } }),
    settingsView: async () => settingsView(),
    scrapeSettingsSave: async input => settingsView({ scrape_backends: input }),
    scrapeMemoryView: async () => ({ available: false, path: null, reason: '尚无抓取状态数据', rows: [] }),
    scrapeMemoryPin: async () => ({}),
    scrapeMemoryReset: async () => ({}),
    ...overrides,
  };
}

const chainNames = root => [...root.querySelectorAll('[data-chain-row]')].map(row => row.getAttribute('data-chain-row'));
const chainRow = (root, name) => root.querySelector(`[data-chain-row="${name}"]`);
const handle = (root, name) => chainRow(root, name).querySelector('.scrape-drag-handle');
const statusNode = root => root.querySelector('[data-sort-status]');

function press(window, node, key) {
  node.dispatchEvent(new window.KeyboardEvent('keydown', { bubbles: true, key }));
}

// happy-dom 无布局，getBoundingClientRect 全 0；落点用 stub 的 elementFromPoint 模拟。
// 真实 WebKit 下的几何命中（矩形中线、before/after 提示）需要集成测试覆盖。
function stubHit(root, name) {
  root.ownerDocument.elementFromPoint = () => chainRow(root, name) ?? null;
}

function pointer(window, node, type, x, y) {
  node.dispatchEvent(new window.PointerEvent(type, { bubbles: true, button: 0, pointerId: 1, clientX: x, clientY: y }));
}

test('keyboard drag reorders the draft and restores focus', async () => {
  const { window, root } = setup();
  const mounted = await mountScrape(root, api());
  const jina = handle(root, 'jina');
  press(window, jina, ' ');
  assert.ok(chainRow(root, 'jina').classList.contains('is-dragging'));
  press(window, jina, 'ArrowDown');
  press(window, jina, 'ArrowDown');
  press(window, jina, 'Enter');
  assert.deepEqual(chainNames(root), ['exa', 'tavily', 'jina', 'firecrawl']);
  assert.equal(mounted.dirty, true);
  assert.match(statusNode(root).textContent, /第 3 位/);
  assert.equal(root.ownerDocument.activeElement, handle(root, 'jina'), 'focus returns to the moved handle');
  window.close();
});

test('keyboard Escape reverts to the original order and announces it', async () => {
  const { window, root } = setup();
  const mounted = await mountScrape(root, api());
  const exa = handle(root, 'exa');
  press(window, exa, 'Enter');
  press(window, exa, 'ArrowDown');
  assert.deepEqual(chainNames(root), ['jina', 'tavily', 'exa', 'firecrawl']);
  press(window, exa, 'Escape');
  assert.deepEqual(chainNames(root), BUILTIN);
  assert.equal(mounted.dirty, false);
  assert.match(statusNode(root).textContent, /取消/);
  assert.ok(!chainRow(root, 'exa').classList.contains('is-dragging'));
  window.close();
});

test('Home and End move the picked row during keyboard drag', async () => {
  const { window, root } = setup();
  await mountScrape(root, api());
  const fire = handle(root, 'firecrawl');
  press(window, fire, 'Enter');
  press(window, fire, 'Home');
  assert.equal(chainNames(root)[0], 'firecrawl');
  press(window, fire, 'End');
  assert.equal(chainNames(root).at(-1), 'firecrawl');
  press(window, fire, 'Escape');
  assert.deepEqual(chainNames(root), BUILTIN);
  window.close();
});

test('keyboard pick-up without movement is a no-op', async () => {
  const { window, root } = setup();
  const mounted = await mountScrape(root, api());
  const tav = handle(root, 'tavily');
  press(window, tav, 'Enter');
  press(window, tav, 'Enter');
  assert.deepEqual(chainNames(root), BUILTIN);
  assert.equal(mounted.dirty, false);
  assert.match(statusNode(root).textContent, /未变化/);
  window.close();
});

test('pointer drag drops before the hovered row', async () => {
  const { window, root } = setup();
  const mounted = await mountScrape(root, api());
  stubHit(root, 'tavily');
  const fire = handle(root, 'firecrawl');
  pointer(window, fire, 'pointerdown', 10, 10);
  assert.ok(chainRow(root, 'firecrawl').classList.contains('is-dragging'));
  pointer(window, fire, 'pointermove', 10, 40);
  assert.ok(chainRow(root, 'tavily').classList.contains('drop-before'));
  pointer(window, fire, 'pointerup', 10, 40);
  assert.deepEqual(chainNames(root), ['jina', 'exa', 'firecrawl', 'tavily']);
  assert.equal(mounted.dirty, true);
  window.close();
});

test('pointer drop outside any row is a no-op', async () => {
  const { window, root } = setup();
  const mounted = await mountScrape(root, api());
  stubHit(root, null);
  const exa = handle(root, 'exa');
  pointer(window, exa, 'pointerdown', 10, 10);
  pointer(window, exa, 'pointerup', 10, 10);
  assert.deepEqual(chainNames(root), BUILTIN);
  assert.equal(mounted.dirty, false);
  assert.match(statusNode(root).textContent, /未变化/);
  window.close();
});

test('pointercancel reverts without committing', async () => {
  const { window, root } = setup();
  const mounted = await mountScrape(root, api());
  stubHit(root, 'firecrawl');
  const jina = handle(root, 'jina');
  pointer(window, jina, 'pointerdown', 10, 10);
  pointer(window, jina, 'pointermove', 10, 90);
  pointer(window, jina, 'pointercancel', 10, 90);
  assert.deepEqual(chainNames(root), BUILTIN);
  assert.equal(mounted.dirty, false);
  window.close();
});

test('refresh cancels an in-flight keyboard drag without mutating order', async () => {
  const { window, root } = setup();
  await mountScrape(root, api());
  const exa = handle(root, 'exa');
  press(window, exa, 'Enter');
  press(window, exa, 'ArrowDown');
  root.querySelector('[data-action="refresh-chain"]').click();
  await flush();
  assert.deepEqual(chainNames(root), BUILTIN);
  assert.ok(![...root.querySelectorAll('.is-dragging')].length);
  window.close();
});

test('drag is disabled while settings are read-only', async () => {
  const { window, root } = setup();
  await mountScrape(root, api({ settingsView: async () => settingsView({ status: 'config_unreadable', message: '坏配置' }) }));
  const jina = handle(root, 'jina');
  assert.equal(jina.disabled, true);
  press(window, jina, 'Enter');
  assert.ok(!chainRow(root, 'jina').classList.contains('is-dragging'));
  window.close();
});

test('saved order matches exact drop result', async () => {
  const { window, root } = setup();
  let sent = null;
  await mountScrape(root, api({ scrapeSettingsSave: async input => { sent = input; return settingsView({ scrape_backends: input }); } }));
  const exa = handle(root, 'exa');
  press(window, exa, 'Enter');
  press(window, exa, 'ArrowDown');
  press(window, exa, 'Enter');
  root.querySelector('[data-scrape-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.deepEqual(sent, ['jina', 'tavily', 'exa', 'firecrawl']);
  window.close();
});

test('warnings stay single-visible: hidden node keeps text, non-empty warns show', async () => {
  const { window, root } = setup();
  await mountScrape(root, api({ credentialStatus: async () => ({ store: { state: 'absent' } }) }));
  const draft = root.querySelector('[data-info="chain-warning"]');
  const saved = root.querySelector('[data-info="saved-chain-warning"]');
  // 草稿与已保存为同一条链且同一警告：草稿隐藏但保留文案，已保存照常显示。
  assert.equal(draft.hidden, true, 'duplicate draft warning collapses');
  assert.match(draft.textContent, /缺少可用 Key/);
  assert.equal(saved.hidden, false);
  assert.match(saved.textContent, /已保存的抓取链.*缺少可用 Key/);
  // 草稿顺序一旦与已保存不同，草稿提示恢复显示。
  root.querySelector('[data-chain-row="jina"] [data-chain-action="down"]').click();
  assert.equal(draft.hidden, false);
  assert.match(draft.textContent, /缺少可用 Key/);
  window.close();
});

test('teardown disposes the sorter and cancels drags', async () => {
  const { window, root } = setup();
  const mounted = await mountScrape(root, api());
  const jina = handle(root, 'jina');
  press(window, jina, 'Enter');
  assert.ok(chainRow(root, 'jina').classList.contains('is-dragging'));
  mounted.dispose();
  assert.match(statusNode(root).textContent, /已结束排序/);
  // 之后不再响应按键。
  press(window, jina, 'ArrowDown');
  press(window, jina, 'Enter');
  assert.equal(mounted.dirty, false);
  window.close();
});

test('row markup follows the new contract', async () => {
  const { window, root } = setup();
  await mountScrape(root, api({ credentialStatus: async source => ({ store: { state: source === 'exa' ? 'present' : 'absent' } }) }));
  assert.ok(root.querySelector('.scrape-page-head'));
  assert.match(root.querySelector('.eyebrow').textContent, /06 \/ SCRAPING/);
  assert.match(root.querySelector('.scrape-intro').textContent, /拖动左侧手柄/);
  assert.equal(root.querySelector('[data-chain-count]').textContent, '4 个后端');
  const jina = chainRow(root, 'jina');
  assert.equal(jina.getAttribute('role'), 'listitem');
  assert.equal(handle(root, 'jina').getAttribute('aria-label'), '拖动调整 Jina Reader 的顺序');
  assert.equal(handle(root, 'jina').getAttribute('aria-describedby'), 'scrape-sort-instructions');
  assert.equal(jina.querySelector('.scrape-provider-mark').textContent, 'J');
  assert.equal(jina.querySelector('.scrape-primary-badge').textContent, '优先');
  assert.equal(jina.querySelector('[data-kind]').getAttribute('data-kind'), 'ready');
  assert.equal(jina.querySelector('[data-kind]').textContent, '可匿名使用');
  assert.equal(chainRow(root, 'exa').querySelector('[data-kind]').textContent, 'Key 已配置');
  assert.equal(chainRow(root, 'tavily').querySelector('[data-kind]').textContent, '待配置 Key');
  assert.equal(chainRow(root, 'tavily').querySelector('[data-kind]').getAttribute('data-kind'), 'warning');
  // 上移/下移按钮：图标 aria-hidden + sr-only 文案，不再裸文本。
  const up = jina.querySelector('[data-chain-action="down"]');
  assert.match(up.textContent, /下移/);
  assert.equal(up.querySelector('[aria-hidden="true"]').textContent, '↓');
  // 无 route-row 碰撞。
  assert.ok(!jina.classList.contains('route-row'));
  window.close();
});
