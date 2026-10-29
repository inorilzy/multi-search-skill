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

// 实际键盘：按键发给当前焦点元素，而不是固定的旧手柄。
function pressFocused(window, key) {
  const target = window.document.activeElement;
  assert.ok(target?.classList?.contains('scrape-drag-handle'), `focus is on a drag handle before ${key}`);
  press(window, target, key);
  return target;
}

test('arrow moves keep real focus on the same handle across three backends', async () => {
  const { window, root } = setup();
  const mounted = await mountScrape(root, api());
  handle(root, 'exa').focus();
  pressFocused(window, 'Enter');
  assert.equal(root.ownerDocument.activeElement, handle(root, 'exa'));
  pressFocused(window, 'ArrowDown');
  assert.deepEqual(chainNames(root), ['jina', 'tavily', 'exa', 'firecrawl']);
  assert.equal(root.ownerDocument.activeElement, handle(root, 'exa'), 'focus follows the moved row after first step');
  pressFocused(window, 'ArrowDown');
  assert.deepEqual(chainNames(root), ['jina', 'tavily', 'firecrawl', 'exa']);
  assert.equal(root.ownerDocument.activeElement, handle(root, 'exa'), 'focus follows the moved row after second step');
  pressFocused(window, 'ArrowUp');
  assert.deepEqual(chainNames(root), ['jina', 'tavily', 'exa', 'firecrawl']);
  assert.equal(root.ownerDocument.activeElement, handle(root, 'exa'), 'focus follows after moving back up');
  // 不再移动的边界键也不应让焦点丢失。
  pressFocused(window, 'ArrowDown');
  pressFocused(window, 'ArrowDown');
  assert.equal(root.ownerDocument.activeElement, handle(root, 'exa'));
  pressFocused(window, 'Enter');
  assert.deepEqual(chainNames(root), ['jina', 'tavily', 'firecrawl', 'exa']);
  assert.equal(mounted.dirty, true);
  assert.equal(root.ownerDocument.activeElement, handle(root, 'exa'), 'focus remains on the dropped handle');
  window.close();
});

test('arrow moves keep visible order numbers and position hints in step', async () => {
  const { window, root } = setup();
  await mountScrape(root, api());
  handle(root, 'jina').focus();
  pressFocused(window, ' ');
  pressFocused(window, 'ArrowDown');
  assert.equal(chainRow(root, 'jina').querySelector('.scrape-order').textContent, '02');
  assert.equal(chainRow(root, 'exa').querySelector('.scrape-order').textContent, '01');
  assert.match(statusNode(root).textContent, /第 2 位/);
  pressFocused(window, 'ArrowDown');
  assert.equal(chainRow(root, 'jina').querySelector('.scrape-order').textContent, '03');
  assert.match(statusNode(root).textContent, /第 3 位/);
  pressFocused(window, 'Enter');
  assert.deepEqual(chainNames(root), ['exa', 'tavily', 'jina', 'firecrawl']);
  assert.equal(chainRow(root, 'jina').querySelector('.scrape-order').textContent, '03');
  assert.equal(chainRow(root, 'firecrawl').querySelector('.scrape-order').textContent, '04');
  assert.equal(root.ownerDocument.activeElement, handle(root, 'jina'));
  window.close();
});

test('Enter drops directly and the saved readback matches the visible order', async () => {
  const { window, root } = setup();
  let sent = null;
  await mountScrape(root, api({
    scrapeSettingsSave: async input => { sent = input; return settingsView({ scrape_backends: input }); },
  }));
  handle(root, 'firecrawl').focus();
  pressFocused(window, 'Enter');
  pressFocused(window, 'ArrowUp');
  pressFocused(window, 'ArrowUp');
  pressFocused(window, 'Enter');
  assert.deepEqual(chainNames(root), ['jina', 'firecrawl', 'exa', 'tavily']);
  assert.equal(root.querySelector('[data-sort-status]').textContent.includes('顺序未变化'), false);
  assert.equal(sent, null, 'drop alone does not write the chain');
  root.querySelector('[data-scrape-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.deepEqual(sent, ['jina', 'firecrawl', 'exa', 'tavily']);
  assert.deepEqual(chainNames(root), ['jina', 'firecrawl', 'exa', 'tavily']);
  window.close();
});

// --- Ticket 04: Escape restores the pre-pick-up order after forward and backward moves. ---

function focusedRowName(window) {
  return window.document.activeElement?.closest?.('[data-chain-row]')?.getAttribute('data-chain-row') ?? null;
}

function orderNumbers(root) {
  return [...root.querySelectorAll('[data-chain-row]')].map(row => row.querySelector('.scrape-order').textContent);
}

const CASES = [
  { label: 'backward', direction: 'ArrowUp', name: 'tavily', preview: ['jina', 'tavily', 'exa', 'firecrawl'] },
  { label: 'forward', direction: 'ArrowDown', name: 'jina', preview: ['exa', 'jina', 'tavily', 'firecrawl'] },
];

for (const testCase of CASES) {
  test(`Escape restores order, numbers, focus and hint after a single ${testCase.label} move`, async () => {
    const { window, root } = setup();
    try {
      let saves = 0;
      const mounted = await mountScrape(root, api({
        scrapeSettingsSave: async input => { saves += 1; return settingsView({ scrape_backends: input }); },
      }));
      handle(root, testCase.name).focus();
      pressFocused(window, ' ');
      pressFocused(window, testCase.direction);
      assert.deepEqual(chainNames(root), testCase.preview, `${testCase.label} move shows the preview order`);

      pressFocused(window, 'Escape');

      assert.deepEqual(chainNames(root), BUILTIN, 'Escape restores the pre-pick-up order');
      assert.deepEqual(orderNumbers(root), ['01', '02', '03', '04'], 'row numbers match actual positions');
      assert.equal(saves, 0, 'cancel never calls save');
      assert.equal(mounted.dirty, false, 'clean draft stays clean after cancel');
      assert.equal(root.querySelector('[data-dirty]').hidden, true, 'no unsaved badge after cancel');
      assert.match(root.querySelector('[data-status="draft"]').textContent, /当前显示已保存设置/);
      assert.match(statusNode(root).textContent, /取消/);
      assert.equal(chainRow(root, testCase.name).classList.contains('is-dragging'), false, 'pick-up state cleared');
      assert.equal(handle(root, testCase.name).getAttribute('aria-pressed'), 'false', 'handle released');
      assert.equal(focusedRowName(window), testCase.name, 'focus stays on the same handle');
    } finally {
      window.close();
    }
  });
}

test('a keyboard move after Escape still acts on the same backend', async () => {
  const { window, root } = setup();
  try {
    let saves = 0;
    await mountScrape(root, api({
      scrapeSettingsSave: async input => { saves += 1; return settingsView({ scrape_backends: input }); },
    }));
    handle(root, 'tavily').focus();
    pressFocused(window, ' ');
    pressFocused(window, 'ArrowUp');
    pressFocused(window, 'Escape');
    assert.deepEqual(chainNames(root), BUILTIN);
    assert.equal(saves, 0);

    pressFocused(window, ' ');
    pressFocused(window, 'ArrowUp');
    assert.deepEqual(chainNames(root), ['jina', 'tavily', 'exa', 'firecrawl'], 'second pick-up moves tavily again');
    pressFocused(window, 'Enter');
    assert.deepEqual(chainNames(root), ['jina', 'tavily', 'exa', 'firecrawl'], 'drop commits the right row');
    assert.deepEqual(orderNumbers(root), ['01', '02', '03', '04']);
    assert.equal(saves, 0, 'dropping only edits the draft');
  } finally {
    window.close();
  }
});

// ---- 工单 03：放下排序区分真实变更与无变化 -------------------------------
// 验收矩阵：起点含“干净草稿 / 已有草稿”，操作含“未移动直接放下 / 移回原位 / 真实改变”，
// 并覆盖保存成功与失败两条分支。全部走页面公开边界（DOM 与 mountScrape 返回的脏标记），
// 不断言私有排序函数。

/** 带状态的假设置：保存成功时按提交顺序读回，失败时保持原值不变。 */
function statefulView(overrides = {}) {
  const current = settingsView(overrides);
  const state = { saves: 0, submitted: null, failNext: false, current };
  return {
    state,
    settingsView: async () => ({ ...state.current }),
    scrapeSettingsSave: async input => {
      state.saves += 1;
      state.submitted = [...input];
      if (state.failNext) throw new Error('synthetic save failure');
      state.current = settingsView({ scrape_backends: [...input] });
      return { ...state.current };
    },
  };
}

async function mountStateful(overrides = {}, extraApi = {}) {
  const { window, root } = setup();
  const fake = statefulView(overrides);
  const mounted = await mountScrape(root, api({
    settingsView: fake.settingsView,
    scrapeSettingsSave: fake.scrapeSettingsSave,
    ...extraApi,
  }));
  return { window, root, mounted, fake };
}

const dirtyBadge = root => root.querySelector('[data-dirty]');
const draftCopy = root => root.querySelector('[data-status="draft"]').textContent;
const saveCopy = root => root.querySelector('[data-status="save"]').textContent;
const rowButton = (root, name, action) => chainRow(root, name).querySelector(`[data-chain-action="${action}"]`);
/** 按钮移动会重建行，测试里重新取该后端的新手柄再聚焦。 */
function clickRowButton(window, root, name, action) {
  rowButton(root, name, action).click();
  handle(root, name).focus();
}

/** 真实键盘路径：按键始终发给当前焦点元素（工单 01 已保证焦点保持）。 */
function dragKeys(window, keys) {
  for (const key of keys) pressFocused(window, key);
}

test('03: a clean draft stays clean when a row is picked up and dropped in place', async () => {
  const { window, root, mounted, fake } = await mountStateful();
  handle(root, 'tavily').focus();
  dragKeys(window, [' ', 'Enter']);
  assert.deepEqual(chainNames(root), BUILTIN, 'order untouched');
  assert.equal(mounted.dirty, false, 'no false unsaved state');
  assert.equal(dirtyBadge(root).hidden, true, 'unsaved badge stays hidden');
  assert.match(draftCopy(root), /已保存设置/);
  assert.match(statusNode(root).textContent, /第 3 位.*未变化/);
  assert.equal(fake.state.saves, 0, 'no write to the chain');
  window.close();
});

test('03: a pointer pick-up dropped back on its own row is not a change', async () => {
  const { window, root, mounted, fake } = await mountStateful();
  stubHit(root, 'exa');
  const exa = handle(root, 'exa');
  pointer(window, exa, 'pointerdown', 10, 30);
  pointer(window, exa, 'pointermove', 10, 30);
  pointer(window, exa, 'pointerup', 10, 30);
  assert.deepEqual(chainNames(root), BUILTIN);
  assert.equal(mounted.dirty, false);
  assert.equal(dirtyBadge(root).hidden, true);
  assert.equal(fake.state.saves, 0);
  window.close();
});

test('03: an existing draft survives an unchanged drop without extra changes', async () => {
  const { window, root, mounted, fake } = await mountStateful();
  // 起点是“已有草稿”：先用按钮造一次真实改动。
  clickRowButton(window, root, 'jina', 'down');
  assert.deepEqual(chainNames(root), ['exa', 'jina', 'tavily', 'firecrawl']);
  assert.equal(mounted.dirty, true);
  assert.equal(fake.state.saves, 0, 'button move alone never writes');

  const before = chainNames(root);
  handle(root, 'firecrawl').focus();
  dragKeys(window, ['Enter', 'Escape']);   // 拿起后取消
  assert.deepEqual(chainNames(root), before, 'cancel keeps the draft order');
  assert.equal(mounted.dirty, true, 'pre-existing draft flag preserved');

  handle(root, 'firecrawl').focus();
  dragKeys(window, [' ', 'Enter']);         // 拿起后原地放下
  assert.deepEqual(chainNames(root), before);
  assert.equal(mounted.dirty, true);
  assert.equal(fake.state.saves, 0);
  assert.match(statusNode(root).textContent, /未变化/);
  window.close();
});

test('03: moving a row and returning it to the pick-up position creates no extra dirty state', async () => {
  const { window, root, mounted, fake } = await mountStateful();
  handle(root, 'exa').focus();
  dragKeys(window, [' ', 'ArrowUp', 'ArrowDown', 'Enter']);
  assert.deepEqual(chainNames(root), BUILTIN, 'final drop equals the pick-up order');
  assert.equal(mounted.dirty, false, 'no unsaved flag for a net-zero move');
  assert.equal(dirtyBadge(root).hidden, true);
  assert.match(draftCopy(root), /已保存设置/);
  assert.match(statusNode(root).textContent, /仍在第 2 位，顺序未变化/);
  assert.equal(fake.state.saves, 0);
  window.close();
});

test('03: an in-place drop after a long keyboard round trip stays clean', async () => {
  const { window, root, mounted, fake } = await mountStateful();
  // 每一步都按真实焦点按键（工单 01 保证方向键保持焦点）；整段移动最终回到拿起前的槽位。
  handle(root, 'tavily').focus();
  dragKeys(window, ['Enter', 'ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'Enter']);
  assert.deepEqual(chainNames(root), BUILTIN, 'net order equals the pick-up order');
  assert.equal(mounted.dirty, false, 'a long round trip never marks a change');
  assert.equal(dirtyBadge(root).hidden, true);
  assert.equal(fake.state.saves, 0);
  window.close();
});

test('03: a Home/End excursion that ends on a different slot is a real change', async () => {
  const { window, root, mounted, fake } = await mountStateful();
  // 工单 02 已让 Home/End 与方向键共用移动逻辑并保持焦点，这里直接断言焦点保持，不再逐步重新聚焦。
  handle(root, 'tavily').focus();
  pressFocused(window, 'Enter');   // 拿起
  pressFocused(window, 'Home');    // 移到 0，焦点仍在同一手柄
  assert.equal(root.ownerDocument.activeElement, handle(root, 'tavily'), 'focus stays on the picked handle after Home');
  pressFocused(window, 'Enter');   // 放下：真实变化
  assert.deepEqual(chainNames(root), ['tavily', 'jina', 'exa', 'firecrawl']);
  assert.equal(mounted.dirty, true, 'ending on another slot marks an unsaved draft');
  assert.equal(fake.state.saves, 0, 'the drop itself never writes');
  // 再次拿起并原地放下：相对已提交草稿没有新变化，脏状态不得再次新增或改变。
  const drafted = chainNames(root);
  pressFocused(window, 'Enter');
  pressFocused(window, 'Enter');
  assert.deepEqual(chainNames(root), drafted, 'in-place re-drop keeps the committed draft');
  assert.equal(mounted.dirty, true, 'the one real change is still the only unsaved draft');
  assert.match(statusNode(root).textContent, /仍在第 1 位，顺序未变化/);
  assert.equal(fake.state.saves, 0, 'still no write from any drop');
  // 保存后读回与显示一致。
  root.querySelector('[data-scrape-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.deepEqual(fake.state.submitted, drafted);
  assert.equal(mounted.dirty, false);
  assert.deepEqual(chainNames(root), drafted, 'readback matches the visible order');
  window.close();
});

test('03: dropping back to the saved order restores a clean draft state', async () => {
  const { window, root, mounted, fake } = await mountStateful();
  handle(root, 'jina').focus();
  dragKeys(window, [' ', 'ArrowDown', 'ArrowDown', 'Enter']);
  assert.deepEqual(chainNames(root), ['exa', 'tavily', 'jina', 'firecrawl']);
  assert.equal(mounted.dirty, true, 'the first drop is a real change');
  // 再放回去：与已保存顺序一致时仍显示有草稿（前一次放下已是真实变更），
  // 但绝不能凭空多出第二次写入。
  handle(root, 'jina').focus();
  dragKeys(window, ['Enter', 'ArrowUp', 'ArrowUp', 'Enter']);
  assert.deepEqual(chainNames(root), BUILTIN, 'order matches the saved chain again');
  assert.equal(mounted.dirty, true, 'the earlier real change is still an unsaved draft');
  assert.equal(fake.state.saves, 0, 'no save is ever triggered by dropping');
  assert.equal(root.querySelector('[data-status="save"]').textContent, '');
  // 直接保存该“已回到原位”的草稿：后端读回与显示一致。
  root.querySelector('[data-scrape-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.deepEqual(fake.state.submitted, BUILTIN);
  assert.equal(fake.state.saves, 1);
  assert.equal(mounted.dirty, false);
  assert.deepEqual(chainNames(root), BUILTIN);
  window.close();
});

test('03: a net-zero pointer drop back onto the original slot stays clean', async () => {
  const { window, root, mounted, fake } = await mountStateful();
  const fire = handle(root, 'firecrawl');
  pointer(window, fire, 'pointerdown', 10, 100);
  stubHit(root, 'jina');
  pointer(window, fire, 'pointermove', 10, 10);
  assert.ok(chainRow(root, 'jina').classList.contains('drop-before'), 'preview hint only');
  // 拖回原位：落点回到原槽位（jina 之前 / firecrawl 自己之外）。
  stubHit(root, null);
  pointer(window, fire, 'pointerup', 10, 100);
  assert.deepEqual(chainNames(root), BUILTIN);
  assert.equal(mounted.dirty, false);
  assert.equal(fake.state.saves, 0);
  window.close();
});

test('03: a real change shows unsaved only after the drop and never claims saved early', async () => {
  const { window, root, mounted, fake } = await mountStateful();
  handle(root, 'firecrawl').focus();
  dragKeys(window, [' ', 'ArrowUp']);
  assert.equal(mounted.dirty, false, 'a preview move is not a persisted change');
  assert.equal(dirtyBadge(root).hidden, true, 'no unsaved badge while still dragging');
  assert.match(draftCopy(root), /已保存设置/);
  dragKeys(window, ['ArrowUp', 'ArrowUp', 'Enter']);
  assert.deepEqual(chainNames(root), ['firecrawl', 'jina', 'exa', 'tavily']);
  assert.equal(mounted.dirty, true, 'drop with a real change marks unsaved');
  assert.equal(dirtyBadge(root).hidden, false);
  assert.match(draftCopy(root), /草稿/);
  assert.equal(saveCopy(root), '', 'no premature saved message before the save call');
  assert.equal(fake.state.saves, 0, 'the drop itself never writes');
  window.close();
});

test('03: after a real change the save payload, readback and badge all agree', async () => {
  const { window, root, mounted, fake } = await mountStateful();
  handle(root, 'jina').focus();
  dragKeys(window, [' ', 'ArrowDown', 'ArrowDown', 'Enter']);
  const visible = chainNames(root);
  assert.deepEqual(visible, ['exa', 'tavily', 'jina', 'firecrawl']);
  root.querySelector('[data-scrape-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.deepEqual(fake.state.submitted, visible, 'saved exactly what the user saw');
  assert.equal(fake.state.saves, 1);
  assert.equal(mounted.dirty, false, 'saved draft clears the unsaved flag');
  assert.equal(dirtyBadge(root).hidden, true);
  assert.match(draftCopy(root), /已保存设置/);
  assert.equal(saveCopy(root), '已保存。');
  assert.deepEqual(chainNames(root), visible, 'readback order matches the pre-save view');
  window.close();
});

test('03: the same rules apply to a draft that was already dirty before the drop', async () => {
  const { window, root, mounted, fake } = await mountStateful();
  clickRowButton(window, root, 'jina', 'down');
  // 点击会把焦点交给该按钮，因此放下前重新聚焦要操作的手柄。
  handle(root, 'firecrawl').focus();
  dragKeys(window, ['Enter', 'ArrowUp', 'ArrowUp', 'ArrowUp', 'Enter']);
  assert.deepEqual(chainNames(root), ['firecrawl', 'exa', 'jina', 'tavily']);
  assert.equal(mounted.dirty, true);
  root.querySelector('[data-scrape-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.deepEqual(fake.state.submitted, ['firecrawl', 'exa', 'jina', 'tavily']);
  assert.equal(mounted.dirty, false, 'one save covers both sources of change');
  assert.deepEqual(chainNames(root), ['firecrawl', 'exa', 'jina', 'tavily']);
  window.close();
});

test('03: a failed save keeps the editable draft and its unsaved flag', async () => {
  const { window, root, mounted, fake } = await mountStateful();
  handle(root, 'jina').focus();
  dragKeys(window, [' ', 'ArrowDown', 'Enter']);
  const drafted = chainNames(root);
  fake.state.failNext = true;
  root.querySelector('[data-scrape-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(saveCopy(root), '', 'failure never shows a saved message');
  assert.match(root.querySelector('[data-info="error"]').textContent, /保存失败，原配置未改变/);
  assert.equal(mounted.dirty, true, 'draft survives the failure');
  assert.equal(dirtyBadge(root).hidden, false);
  assert.deepEqual(chainNames(root), drafted, 'the page stays editable with the same draft');
  assert.notDeepEqual(mounted.saved.scrape_backends, drafted, 'persisted value is untouched');
  // 失败后继续编辑并成功保存：读回与显示一致。
  fake.state.failNext = false;
  clickRowButton(window, root, 'jina', 'down');
  root.querySelector('[data-scrape-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(mounted.dirty, false);
  assert.deepEqual(mounted.saved.scrape_backends, chainNames(root), 'readback matches the visible order');
  window.close();
});

test('03: only a real drop change can enable a save, in-place drops never dirty the draft', async () => {
  const { window, root, mounted, fake } = await mountStateful();
  for (const key of [[' ', 'Enter'], ['Enter', 'ArrowUp', 'ArrowDown', 'Enter'], [' ', 'Escape']]) {
    handle(root, 'exa').focus();
    dragKeys(window, key);
    assert.equal(mounted.dirty, false, `${key.join('+')} leaves no draft`);
    assert.equal(dirtyBadge(root).hidden, true);
  }
  handle(root, 'exa').focus();
  dragKeys(window, [' ', 'ArrowDown', 'Enter']);
  assert.equal(mounted.dirty, true, 'the changed drop is the first unsaved step');
  assert.equal(fake.state.saves, 0);
  window.close();
});

test('Home from a middle row moves to first and keeps focus on that handle', async () => {
  const { window, root } = setup();
  await mountScrape(root, api());
  handle(root, 'tavily').focus();
  pressFocused(window, ' ');
  pressFocused(window, 'Home');
  assert.deepEqual(chainNames(root), ['tavily', 'jina', 'exa', 'firecrawl']);
  assert.equal(root.ownerDocument.activeElement, handle(root, 'tavily'));
  assert.equal(chainRow(root, 'tavily').querySelector('.scrape-order').textContent, '01');
  assert.match(statusNode(root).textContent, /第 1 位/);
  window.close();
});

test('End from first row moves to last and keeps focus on that handle', async () => {
  const { window, root } = setup();
  await mountScrape(root, api());
  handle(root, 'jina').focus();
  pressFocused(window, 'Enter');
  pressFocused(window, 'End');
  assert.deepEqual(chainNames(root), ['exa', 'tavily', 'firecrawl', 'jina']);
  assert.equal(root.ownerDocument.activeElement, handle(root, 'jina'));
  assert.equal(chainRow(root, 'jina').querySelector('.scrape-order').textContent, '04');
  assert.match(statusNode(root).textContent, /第 4 位/);
  window.close();
});

test('repeated Home or End at a boundary neither drops nor duplicates rows', async () => {
  const { window, root } = setup();
  await mountScrape(root, api());
  handle(root, 'exa').focus();
  pressFocused(window, 'Enter');
  pressFocused(window, 'Home');
  pressFocused(window, 'Home');
  pressFocused(window, 'Home');
  assert.deepEqual(chainNames(root), ['exa', 'jina', 'tavily', 'firecrawl']);
  assert.equal(root.ownerDocument.activeElement, handle(root, 'exa'));
  pressFocused(window, 'End');
  pressFocused(window, 'End');
  assert.deepEqual(chainNames(root), ['jina', 'tavily', 'firecrawl', 'exa']);
  assert.equal(root.querySelectorAll('[data-chain-row]').length, 4);
  assert.equal(chainRow(root, 'exa').querySelector('.scrape-order').textContent, '04');
  assert.equal(root.ownerDocument.activeElement, handle(root, 'exa'));
  window.close();
});

test('Home/End mixed with arrows and Enter save the exact visible order', async () => {
  const { window, root } = setup();
  let sent = null;
  await mountScrape(root, api({
    scrapeSettingsSave: async input => { sent = input; return settingsView({ scrape_backends: input }); },
  }));
  handle(root, 'tavily').focus();
  pressFocused(window, ' ');
  pressFocused(window, 'End');
  pressFocused(window, 'ArrowUp');
  pressFocused(window, 'Home');
  pressFocused(window, 'ArrowDown');
  pressFocused(window, 'Enter');
  const visible = chainNames(root);
  assert.deepEqual(visible, ['jina', 'tavily', 'exa', 'firecrawl']);
  assert.equal(root.ownerDocument.activeElement, handle(root, 'tavily'));
  root.querySelector('[data-scrape-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.deepEqual(sent, visible);
  assert.deepEqual(chainNames(root), visible);
  window.close();
});
