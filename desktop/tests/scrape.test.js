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
    config_path: 'C:/Users/test/.multi-search/config.sqlite',
    path_source: 'user',
    file_present: true,
    read_source: 'sqlite',
    route: 'default',
    timeout: 60,
    timeout_configured: true,
    effective_timeout: 60,
    effective_timeouts: { default: 60 },
    routes: { default: { label: '默认', sources: ['brave'], timeout: null } },
    builtin_routes: { default: { label: '默认', sources: ['brave'], timeout: null } },
    disabled_sources: [],
    twitter_cookies_path: null,
    scrape_backends: [...BUILTIN],
    scrape_backends_invalid: false,
    builtin_scrape_backends: [...BUILTIN],
    scrape_backend_options: OPTIONS.map(option => ({ ...option })),
    active_sources: ['brave'],
    status: 'ok',
    message: '',
    ...overrides,
  };
}

function memoryRow(overrides = {}) {
  return {
    site: 'github.com/repo',
    scraper: 'jina',
    success_count: 3,
    failure_count: 1,
    blocked_count: 0,
    timeout_count: 0,
    avg_content_length: 1200,
    last_success_at: '2026-10-22T10:00:00+08:00',
    last_failure_at: null,
    last_error_type: null,
    last_error_message: null,
    cooldown_until: '2026-10-22T11:00:00+08:00',
    sample_url: 'https://github.com/x/y',
    manually_pinned: false,
    manual_priority: null,
    in_cooldown: true,
    ...overrides,
  };
}

function memoryView(overrides = {}) {
  return {
    available: true,
    path: 'C:/Users/test/.multi-search/state.sqlite',
    reason: '',
    rows: [memoryRow()],
    ...overrides,
  };
}

const chainNames = root => [...root.querySelectorAll('[data-chain-row]')].map(row => row.getAttribute('data-chain-row'));
const chainRow = (root, name) => root.querySelector(`[data-chain-row="${name}"]`);
const chainButton = (root, name, label) => [...chainRow(root, name).querySelectorAll('button')].find(button => button.textContent === label);

function api(overrides = {}) {
  return {
    credentialStatus: async source => ({ source, store: { state: 'absent', saved_at: null, error: '' }, effective_source: 'none', key_application_available: true }),
    settingsView: async () => settingsView(),
    settingsSave: async input => settingsView({ scrape_backends: input.scrape_backends }),
    scrapeMemoryView: async () => memoryView(),
    scrapeMemoryPin: async () => memoryView(),
    scrapeMemoryReset: async () => memoryView({ rows: [] }),
    ...overrides,
  };
}

test('renders the saved chain in order with labels and backend ids', async () => {
  const { window, root } = setup();
  await mountScrape(root, api());
  assert.deepEqual(chainNames(root), BUILTIN);
  const first = chainRow(root, 'jina');
  assert.match(first.textContent, /Jina Reader/);
  assert.match(first.textContent, /01/);
  assert.match(first.textContent, /jina/);
  window.close();
});

test('moving a backend up and down rewrites the draft order', async () => {
  const { window, root } = setup();
  const mounted = await mountScrape(root, api());
  chainButton(root, 'tavily', '上移').click();
  assert.deepEqual(chainNames(root), ['jina', 'tavily', 'exa', 'firecrawl']);
  assert.equal(mounted.dirty, true);
  chainButton(root, 'tavily', '下移').click();
  assert.deepEqual(chainNames(root), BUILTIN);
  assert.equal(chainButton(root, 'jina', '上移').disabled, true);
  assert.equal(chainButton(root, 'firecrawl', '下移').disabled, true);
  window.close();
});

test('disabling every backend warns and blocks save until one returns', async () => {
  const { window, root } = setup();
  let saves = 0;
  await mountScrape(root, api({ settingsSave: async input => { saves += 1; return settingsView({ scrape_backends: input.scrape_backends }); } }));
  for (const name of [...BUILTIN]) chainButton(root, name, '停用').click();
  assert.deepEqual(chainNames(root), []);
  assert.match(root.querySelector('[data-info="chain-warning"]').textContent, /抓取不会运行/);
  assert.equal(root.querySelector('[data-action="save"]').disabled, true);
  root.querySelector('[data-scrape-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(saves, 0);

  // 停用的后端保留在可选列表，可重新加入链尾。
  const add = [...root.querySelectorAll('[data-add-backend]')].find(node => node.getAttribute('data-add-backend') === 'firecrawl');
  add.click();
  assert.deepEqual(chainNames(root), ['firecrawl']);
  assert.equal(root.querySelector('[data-action="save"]').disabled, false);
  assert.equal(root.querySelector('[data-info="chain-warning"]').textContent, '');
  window.close();
});

test('required-key-only drafts block both save button and form submission', async () => {
  for (const names of [['exa'], ['tavily'], ['exa', 'tavily']]) {
    const { window, root } = setup();
    let saves = 0;
    await mountScrape(root, api({ settingsSave: async () => { saves++; return settingsView(); } }));
    for (const name of BUILTIN.filter(name => !names.includes(name))) chainButton(root, name, '停用').click();
    assert.equal(root.querySelector('[data-action="save"]').disabled, true);
    assert.match(root.querySelector('[data-info="chain-warning"]').textContent, /整条链无法运行/);
    root.querySelector('[data-scrape-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
    await flush();
    assert.equal(saves, 0);
    assert.equal(root.querySelector('[data-status="save"]').textContent, '未保存。');
    window.close();
  }
});

test('anonymous-only chains save without reading secrets or optional provider status', async () => {
  for (const name of ['jina', 'firecrawl']) {
    const { window, root } = setup();
    const queried = [];
    let saves = 0;
    await mountScrape(root, api({
      settingsView: async () => settingsView({ scrape_backends: [name] }),
      credentialStatus: async source => { queried.push(source); return { store: { state: 'absent' } }; },
      credentialRead: async () => { assert.fail('must never read secret values'); },
      settingsSave: async input => { saves++; return settingsView({ scrape_backends: input.scrape_backends }); },
    }));
    assert.equal(root.querySelector('[data-action="save"]').disabled, false);
    assert.equal(root.querySelector('[data-info="chain-warning"]').textContent, '');
    root.querySelector('[data-action="save"]').click();
    await flush();
    assert.equal(saves, 1);
    assert.deepEqual([...new Set(queried)].sort(), ['exa', 'tavily']);
    window.close();
  }
});

test('one configured required key permits a mixed chain regardless of site cooldown', async () => {
  const { window, root } = setup();
  await mountScrape(root, api({
    settingsView: async () => settingsView({ scrape_backends: ['exa', 'tavily'] }),
    credentialStatus: async source => ({ store: { state: source === 'exa' ? 'present' : 'absent' } }),
    scrapeMemoryView: async () => memoryView({ rows: [memoryRow({ scraper: 'exa', in_cooldown: true })] }),
  }));
  assert.equal(root.querySelector('[data-action="save"]').disabled, false);
  assert.match(root.querySelector('[data-info="chain-warning"]').textContent, /Tavily 缺少可用 Key/);
  assert.doesNotMatch(root.querySelector('[data-info="chain-warning"]').textContent, /整条链无法运行/);
  window.close();
});

test('saved chains warn when credentials disappear and recover on refresh', async () => {
  const { window, root } = setup();
  let state = 'unreadable';
  await mountScrape(root, api({
    settingsView: async () => settingsView({ scrape_backends: ['exa'] }),
    credentialStatus: async () => ({ store: { state, error: 'do not expose backend error' } }),
  }));
  assert.match(root.querySelector('[data-info="saved-chain-warning"]').textContent, /已保存.*整条链无法运行/);
  assert.doesNotMatch(root.textContent, /do not expose backend error/);
  state = 'present';
  root.querySelector('[data-action="refresh-chain"]').click();
  await flush();
  assert.equal(root.querySelector('[data-info="saved-chain-warning"]').textContent, '');
  assert.equal(root.querySelector('[data-action="save"]').disabled, false);
  window.close();
});

test('save rechecks credentials removed since mount', async () => {
  const { window, root } = setup();
  let state = 'present';
  let saves = 0;
  await mountScrape(root, api({
    settingsView: async () => settingsView({ scrape_backends: ['tavily'] }),
    credentialStatus: async () => ({ store: { state } }),
    settingsSave: async () => { saves++; return settingsView(); },
  }));
  state = 'absent';
  root.querySelector('[data-action="save"]').click();
  await flush();
  assert.equal(saves, 0);
  assert.equal(root.querySelector('[data-action="save"]').disabled, true);
  assert.match(root.querySelector('[data-info="saved-chain-warning"]').textContent, /整条链无法运行/);
  window.close();
});

test('failed or unavailable credential status is unknown rather than a permanent invalid chain', async () => {
  for (const state of ['unavailable', 'future-state', null]) {
    const { window, root } = setup();
    await mountScrape(root, api({
      settingsView: async () => settingsView({ scrape_backends: ['exa'] }),
      credentialStatus: async () => { if (state === null) throw new Error('offline'); return { store: { state } }; },
    }));
    assert.match(root.querySelector('[data-info="chain-warning"]').textContent, /暂时无法确认/);
    assert.equal(root.querySelector('[data-action="save"]').disabled, false);
    window.close();
  }
});

test('restore default order fills the draft and still requires saving', async () => {
  const { window, root } = setup();
  const mounted = await mountScrape(root, api());
  chainButton(root, 'jina', '停用').click();
  chainButton(root, 'exa', '停用').click();
  assert.deepEqual(chainNames(root), ['tavily', 'firecrawl']);
  root.querySelector('[data-action="restore-chain"]').click();
  assert.match(root.querySelector('[data-restore-confirm]').textContent, /仍需保存/);
  root.querySelector('[data-action="confirm-restore-chain"]').click();
  assert.deepEqual(chainNames(root), BUILTIN);
  assert.equal(mounted.dirty, true);
  assert.match(root.querySelector('[data-status="draft"]').textContent, /尚未保存/);
  window.close();
});

test('save submits the full settings payload with the draft chain', async () => {
  const { window, root } = setup();
  let sent = null;
  await mountScrape(root, api({ settingsSave: async input => { sent = input; return settingsView({ scrape_backends: input.scrape_backends }); } }));
  chainButton(root, 'jina', '停用').click();
  root.querySelector('[data-add-backend="jina"]').click();
  chainButton(root, 'jina', '上移').click();
  root.querySelector('[data-scrape-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.deepEqual(sent.scrape_backends, ['exa', 'tavily', 'jina', 'firecrawl']);
  assert.equal(sent.route, 'default');
  assert.equal(sent.timeout, 60);
  assert.deepEqual(sent.disabled_sources, []);
  assert.equal(sent.routes, null);
  assert.equal(sent.twitter_cookies_path, null);
  assert.equal(root.querySelector('[data-status="save"]').textContent, '已保存。');
  assert.equal(root.querySelector('[data-dirty]').hidden, true);
  window.close();
});

test('save failure keeps the draft and shows the error', async () => {
  const { window, root } = setup();
  await mountScrape(root, api({ settingsSave: async () => { throw new Error('synthetic failure'); } }));
  chainButton(root, 'exa', '上移').click();
  root.querySelector('[data-scrape-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.deepEqual(chainNames(root), ['exa', 'jina', 'tavily', 'firecrawl']);
  assert.equal(root.querySelector('[data-info="error"]').textContent, 'synthetic failure');
  assert.equal(root.querySelector('[data-dirty]').hidden, false);
  window.close();
});

test('memory table shows counts cooldown and caption, and supports site filtering', async () => {
  const { window, root } = setup();
  await mountScrape(root, api({
    scrapeMemoryView: async () => memoryView({
      rows: [
        memoryRow({ site: 'github.com/repo', scraper: 'jina' }),
        memoryRow({ site: 'zhihu.com', scraper: 'exa', manually_pinned: true, manual_priority: -1, in_cooldown: false, cooldown_until: null }),
      ],
    }),
  }));
  const rows = () => [...root.querySelectorAll('[data-memory-row]')].map(row => row.getAttribute('data-memory-row'));
  assert.equal(rows().length, 2);
  assert.match(root.querySelector('[data-memory-table]').textContent, /3 \/ 1 \/ 0 \/ 0/);
  assert.match(root.querySelector('[data-memory-table]').textContent, /冷却至 2026-10-22T11:00:00\+08:00/);
  assert.match(root.querySelector('[data-memory-table]').textContent, /手动固定 · -1/);
  const filter = root.querySelector('[data-field="site-filter"]');
  filter.value = 'zhihu';
  filter.dispatchEvent(new window.Event('input'));
  assert.deepEqual(rows(), ['zhihu.com|exa']);
  filter.value = 'none';
  filter.dispatchEvent(new window.Event('input'));
  assert.match(root.querySelector('[data-memory-empty]').textContent, /没有匹配该站点/);
  window.close();
});

test('empty and unavailable memory states stay readable and disable writes', async () => {
  const { window, root } = setup();
  let pins = 0;
  await mountScrape(root, api({
    scrapeMemoryView: async () => ({ available: false, path: null, reason: '尚无抓取状态数据', rows: [] }),
    scrapeMemoryPin: async () => { pins += 1; return memoryView(); },
  }));
  assert.equal(root.querySelector('[data-memory-table]').children.length, 0);
  assert.equal(root.querySelector('[data-memory-empty]').hidden, true);
  assert.match(root.querySelector('[data-info="memory-error"]').textContent, /尚无抓取状态数据/);

  const second = setup();
  await mountScrape(second.root, api({ scrapeMemoryView: async () => memoryView({ rows: [] }) }));
  assert.equal(second.root.querySelector('[data-memory-empty]').hidden, false);
  assert.match(second.root.querySelector('[data-memory-empty]').textContent, /还没有抓取记录/);
  assert.equal(pins, 0);
  second.window.close();
  window.close();
});

test('pin requires inline confirmation before calling the write command', async () => {
  const { window, root } = setup();
  const calls = [];
  const mounted = await mountScrape(root, api({
    scrapeMemoryPin: async (site, scraper) => { calls.push([site, scraper]); return memoryView({ rows: [memoryRow({ manually_pinned: true, manual_priority: -1 })] }); },
  }));
  const pinButton = root.querySelector('[data-memory-action="pin"]');
  assert.equal(calls.length, 0);
  pinButton.click();
  assert.equal(calls.length, 0, 'no write before confirmation');
  assert.match(root.querySelector('[data-memory-confirm="pin"]').textContent, /github\.com\/repo/);
  root.querySelector('[data-action="cancel-memory"]').click();
  assert.equal(calls.length, 0);
  assert.equal(root.querySelector('[data-memory-confirm]'), null);

  root.querySelector('[data-memory-action="pin"]').click();
  root.querySelector('[data-action="confirm-memory"]').click();
  await flush();
  assert.deepEqual(calls, [['github.com/repo', 'jina']]);
  assert.match(root.querySelector('[data-memory-table]').textContent, /手动固定/);
  assert.equal(mounted.memory.rows[0].manually_pinned, true);
  window.close();
});

test('reset requires confirmation and returns the refreshed view', async () => {
  const { window, root } = setup();
  const calls = [];
  await mountScrape(root, api({
    scrapeMemoryReset: async site => { calls.push(site); return memoryView({ rows: [] }); },
  }));
  root.querySelector('[data-memory-action="reset"]').click();
  assert.equal(calls.length, 0);
  assert.match(root.querySelector('[data-memory-confirm="reset"]').textContent, /不可撤销/);
  root.querySelector('[data-action="confirm-memory"]').click();
  await flush();
  assert.deepEqual(calls, ['github.com/repo']);
  assert.equal(root.querySelector('[data-memory-table]').children.length, 0);
  assert.equal(root.querySelector('[data-memory-empty]').hidden, false);
  window.close();
});

test('memory read failure is shown inline without crashing the chain', async () => {
  const { window, root } = setup();
  await mountScrape(root, api({ scrapeMemoryView: async () => { throw new Error('offline'); } }));
  assert.deepEqual(chainNames(root), BUILTIN);
  assert.match(root.querySelector('[data-info="memory-error"]').textContent, /尚无抓取状态数据/);
  assert.equal(root.querySelector('[data-memory-empty]').hidden, true);
  window.close();
});

test('failed memory writes keep the error visible after rerender and filtering', async () => {
  for (const action of ['pin', 'reset']) {
    const { window, root } = setup();
    const mounted = await mountScrape(root, api({
      scrapeMemoryPin: async () => { throw new Error('synthetic pin failure'); },
      scrapeMemoryReset: async () => { throw new Error('synthetic reset failure'); },
    }));
    root.querySelector(`[data-memory-action="${action}"]`).click();
    root.querySelector('[data-action="confirm-memory"]').click();
    await flush();
    assert.equal(root.querySelector('[data-info="memory-error"]').textContent, `synthetic ${action} failure`);
    assert.equal(mounted.memory.rows.length, 1);
    root.querySelector('[data-field="site-filter"]').dispatchEvent(new window.Event('input'));
    assert.equal(root.querySelector('[data-info="memory-error"]').textContent, `synthetic ${action} failure`);
    root.querySelector('[data-action="refresh-memory"]').click();
    await flush();
    assert.equal(root.querySelector('[data-info="memory-error"]').textContent, '');
    window.close();
  }
});

test('saving locks draft controls until the submitted chain is acknowledged', async () => {
  const { window, root } = setup();
  let finish;
  let submitted;
  await mountScrape(root, api({
    settingsSave: input => {
      submitted = input;
      return new Promise(resolve => { finish = resolve; });
    },
  }));
  chainButton(root, 'firecrawl', '停用').click();
  const expected = chainNames(root);
  root.querySelector('[data-scrape-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  for (const button of root.querySelectorAll('[data-chain-action], [data-add-backend], [data-action="restore-chain"]')) {
    assert.equal(button.disabled, true);
  }
  chainButton(root, 'jina', '下移').click();
  assert.deepEqual(chainNames(root), expected);
  finish(settingsView({ scrape_backends: submitted.scrape_backends }));
  await flush();
  assert.deepEqual(chainNames(root), expected);
  assert.equal(chainButton(root, 'jina', '下移').disabled, false);
  window.close();
});

test('unreadable settings keep the chain read-only and prevent saving', async () => {
  const { window, root } = setup();
  await mountScrape(root, api({ settingsView: async () => settingsView({ status: 'config_unreadable', message: '坏配置' }) }));
  assert.equal(root.querySelector('[data-action="save"]').disabled, true);
  assert.match(root.querySelector('[data-info="error"]').textContent, /坏配置/);
  assert.equal(chainButton(root, 'jina', '停用').disabled, true);
  window.close();
});

test('unreadable settings keep rebuilt chain controls and add-backends disabled', async () => {
  const { window, root } = setup();
  let reads = 0;
  await mountScrape(root, api({
    settingsView: async () => {
      reads += 1;
      return reads === 1
        ? settingsView()
        : settingsView({
            status: 'config_unreadable',
            message: '坏配置',
            scrape_backends: ['jina'],
            builtin_scrape_backends: [...BUILTIN],
          });
    },
  }));
  // 先制造草稿，再确认刷新丢弃；刷新结果只读，renderChain 会重建按钮。
  chainButton(root, 'jina', '停用').click();
  root.querySelector('[data-action="refresh-chain"]').click();
  await flush();
  root.querySelector('[data-action="confirm-refresh-chain"]').click();
  await flush();
  assert.equal(reads, 2);
  const buttons = [...root.querySelectorAll('[data-chain-list] button')];
  assert.ok(buttons.length > 0);
  for (const button of buttons) {
    assert.equal(button.disabled, true, `${button.textContent} must stay disabled`);
  }
  for (const chip of root.querySelectorAll('[data-add-backend]')) {
    assert.equal(chip.disabled, true, `${chip.getAttribute('data-add-backend')} add chip must stay disabled`);
  }
  assert.ok(root.querySelectorAll('[data-add-backend]').length > 0, 'inactive backends must still render');
  assert.equal(root.querySelector('[data-action="save"]').disabled, true);
  window.close();
});

test('platform scrapers show a note instead of a pin button but keep reset', async () => {
  const { window, root } = setup();
  let pins = 0;
  await mountScrape(root, api({
    scrapeMemoryView: async () => memoryView({
      rows: [
        memoryRow({ site: 'reddit.com', scraper: 'reddit' }),
        memoryRow({ site: 'x.com', scraper: 'twitter' }),
      ],
    }),
    scrapeMemoryPin: async () => { pins += 1; return memoryView(); },
  }));
  for (const scraper of ['reddit', 'twitter']) {
    const line = root.querySelector(`[data-memory-row$="|${scraper}"]`);
    assert.ok(line, `${scraper} row must render`);
    assert.equal(line.querySelector('[data-memory-action="pin"]'), null);
    assert.match(line.querySelector(`[data-memory-pin-note="${scraper}"]`).textContent, /平台抓取，按域名分派/);
    assert.equal(line.querySelector('[data-memory-action="reset"]').disabled, false);
  }
  assert.equal(pins, 0);
  window.close();
});

test('pin is disabled for a backend that is not in the saved chain', async () => {
  const { window, root } = setup();
  await mountScrape(root, api({
    settingsView: async () => settingsView({ scrape_backends: ['jina', 'exa'] }),
    scrapeMemoryView: async () => memoryView({
      rows: [
        memoryRow({ site: 'a.example', scraper: 'jina' }),
        memoryRow({ site: 'b.example', scraper: 'tavily' }),
      ],
    }),
  }));
  const jina = root.querySelector('[data-memory-row="a.example|jina"]');
  assert.equal(jina.querySelector('[data-memory-action="pin"]').disabled, false);

  const tavily = root.querySelector('[data-memory-row="b.example|tavily"]');
  const pin = tavily.querySelector('[data-memory-action="pin"]');
  assert.equal(pin.disabled, true);
  assert.match(pin.title, /该后端未在抓取链中，先加入链并保存/);
  assert.match(tavily.querySelector('[data-memory-pin-hint="tavily"]').textContent, /先加入链并保存/);
  // 未保存的草稿不改变 pin 资格：以已保存的链为准。
  root.querySelector('[data-chain-row="exa"] [data-chain-action="disable"]').click();
  assert.deepEqual(chainNames(root), ['jina']);
  assert.equal(root.querySelector('[data-memory-row="b.example|tavily"] [data-memory-action="pin"]').disabled, true);
  window.close();
});

test('invalid saved chain shows a warning that CLI scraping will fail', async () => {
  const { window, root } = setup();
  await mountScrape(root, api({ settingsView: async () => settingsView({ scrape_backends_invalid: true }) }));
  assert.match(root.querySelector('[data-info="saved-chain-warning"]').textContent, /已保存的抓取链无效/);
  assert.match(root.querySelector('[data-info="saved-chain-warning"]').textContent, /CLI 抓取将报配置错误/);
  // 保存按钮仍可用，允许用户保存覆盖无效值。
  assert.equal(root.querySelector('[data-action="save"]').disabled, false);
  window.close();
});

test('valid saved chain with configured keys hides the invalid warning', async () => {
  const { window, root } = setup();
  await mountScrape(root, api({ credentialStatus: async () => ({ store: { state: 'present' } }) }));
  assert.equal(root.querySelector('[data-info="saved-chain-warning"]').textContent, '');
  window.close();
});

test('refresh with an unsaved draft asks before discarding it', async () => {
  const { window, root } = setup();
  let reads = 0;
  await mountScrape(root, api({
    settingsView: async () => {
      reads += 1;
      return settingsView({ scrape_backends: reads === 1 ? BUILTIN : ['firecrawl', 'jina'] });
    },
  }));
  chainButton(root, 'exa', '停用').click();
  root.querySelector('[data-action="refresh-chain"]').click();
  await flush();
  assert.equal(reads, 1);
  assert.match(root.querySelector('[data-restore-confirm]').textContent, /丢弃未保存/);
  root.querySelector('[data-action="confirm-refresh-chain"]').click();
  await flush();
  assert.equal(reads, 2);
  assert.deepEqual(chainNames(root), ['firecrawl', 'jina']);
  window.close();
});
