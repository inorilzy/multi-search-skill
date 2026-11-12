import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountUsage } from '../ui/usage.js';
import { pages } from '../ui/pages.js';
import { createNavigation } from '../ui/app.js';

const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const report = (overrides = {}) => ({
  provider: 'tavily', status: 'ok', scope: 'key', unit: 'credits', remaining: 600, limit: 1000,
  used: 400, resets_at: '2026-12-01T00:00:00Z', period: 'month', key_fingerprint: 'fp-one',
  error_kind: null, message: '', fetched_at: '2026-11-12T00:00:00Z', ...overrides,
});
const pace = (overrides = {}) => ({
  key_fingerprint: 'fp-one', scope: 'key', unit: 'credits', rate_per_day: 10,
  projected_empty_at: '2027-01-11T00:00:00Z', lasts_until_reset: true, reason: null, ...overrides,
});
const point = (overrides = {}) => ({
  key_fingerprint: 'fp-one', scope: 'key', unit: 'credits', remaining: 800, limit: 1000,
  fetched_at: '2026-11-10T00:00:00Z', ...overrides,
});
const counts = { search: 4, scrape: 2, failures: 1 };
const provider = (overrides = {}) => ({
  id: 'tavily', label: 'Tavily', balance_supported: true, balance_note: '', current: [report()],
  accounts: [], total: { remaining: 600, limit: 1000, percent: 60, unit: 'credits', relative: false }, alert: null,
  totals: [{ scope: 'key', unit: 'credits', key_count: 1, remaining: 600, limit: 1000, message: '' }],
  history: [point(), point({ remaining: 600, fetched_at: '2026-11-12T00:00:00Z' })], pace: [pace()],
  calls: { today: counts, last_7_days: { search: 12, scrape: 5, failures: 2 }, daily: [] }, ...overrides,
});
const view = (providers = [provider()], overrides = {}) => ({
  status: 'ready', message: '', schema_version: 1, retention_days: 30, providers, ...overrides,
});
function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root };
}
const card = (root, id = 'tavily') => root.querySelector(`[data-provider="${id}"]`);

test('T06: sidebar places 04 服务商 and 05 用量 before renumbered settings', () => {
  assert.deepEqual(pages.slice(3).map(({ id, label, number }) => [id, label, number]), [
    ['sources', '服务商', '04'], ['usage', '用量', '05'], ['settings', '搜索设置', '06'],
    ['scrape', '抓取设置', '07'], ['cookies', 'Cookie 导入', '08'],
  ]);
});

test('T06: quota, reset, pace, accessible static chart and local calls render together', async () => {
  const { window, root } = setup();
  const mounted = await mountUsage(root, { usageView: async () => view() });
  assert.match(root.querySelector('.eyebrow').textContent, /^05 \/ /);
  assert.equal(root.querySelector('h1').getAttribute('tabindex'), '-1');
  assert.match(card(root).textContent, /正常/);
  assert.match(card(root).textContent, /剩余 600 \/ 上限 1,000 credits/);
  assert.match(card(root).textContent, /重置时间：2026-12-01 00:00 UTC/);
  assert.match(card(root).textContent, /每天消耗 10 credits，能撑到重置/);
  assert.match(card(root).textContent, /本机调用 · 今天搜索 4 次，抓取 2 次，失败 1 次/);
  assert.match(card(root).textContent, /本机调用 · 近 7 天搜索 12 次，抓取 5 次，失败 2 次/);
  const progress = card(root).querySelector('progress');
  assert.equal(progress.value, 600);
  assert.equal(progress.max, 1000);
  assert.match(progress.getAttribute('aria-label'), /剩余额度/);
  const svg = card(root).querySelector('svg');
  assert.equal(svg.getAttribute('role'), 'img');
  assert.match(svg.getAttribute('aria-label'), /近 30 天剩余走势/);
  assert.equal(svg.querySelectorAll('polyline').length, 1);
  assert.equal(svg.querySelectorAll('circle').length, 2);
  assert.equal(root.querySelector('[data-local-only]').hidden, true);
  assert.match(root.textContent, /本机统计不等于服务商计费次数/);
  mounted.dispose();
  window.close();
});

test('T06: credential, unsupported, error and insufficient-data states name their reasons', async () => {
  const { window, root } = setup();
  const providers = [
    provider({ id: 'exa', label: 'Exa', current: [report({ status: 'needs_credential', message: '请配置管理 Key。' })] }),
    provider({ id: 'jina', label: 'Jina', current: [report({ status: 'error', message: '服务商查询超时。' })] }),
    provider({ id: 'new', label: 'New', current: [], totals: [], history: [], pace: [] }),
    provider({ id: 'brave', label: 'Brave', balance_supported: false, balance_note: '没有余额查询接口。',
      current: [report({ status: 'unsupported' })] }),
  ];
  const mounted = await mountUsage(root, { usageView: async () => view(providers) });
  assert.match(card(root, 'exa').textContent, /需要凭据.*请配置管理 Key/);
  assert.match(card(root, 'jina').textContent, /查询失败.*服务商查询超时/);
  assert.match(card(root, 'new').textContent, /数据不足/);
  assert.equal(root.querySelector('[data-local-only]').hidden, false);
  assert.equal(card(root, 'brave').parentNode, root.querySelector('[data-local-providers]'));
  assert.match(card(root, 'brave').textContent, /不支持余额查询.*没有余额查询接口/);
  assert.equal(card(root, 'brave').querySelector('svg'), null);
  assert.equal(card(root, 'brave').querySelector('progress'), null);
  mounted.dispose();
  window.close();
});

test('T06: null quotas, timestamps, rate and missing call counts stay unknown, while real zero stays zero', async () => {
  const { window, root } = setup();
  const unknown = provider({
    current: [report({ remaining: null, limit: null, unit: '', resets_at: null, fetched_at: null })],
    totals: [{ scope: 'key', unit: '', key_count: 1, remaining: null, limit: null, message: '' }],
    history: [], pace: [pace({ rate_per_day: null, reason: null })],
    calls: { today: {}, last_7_days: { search: 0, scrape: 0, failures: 0 }, daily: [] },
  });
  const mounted = await mountUsage(root, { usageView: async () => view([unknown]) });
  assert.equal(card(root).querySelector('.usage-amount').textContent, '剩余 未知 / 上限 未知 未知');
  assert.equal(card(root).querySelector('progress'), null);
  assert.match(card(root).textContent, /重置时间：未知；更新时间：未知/);
  assert.match(card(root).textContent, /配速未知/);
  const values = [...card(root).querySelectorAll('.usage-calls dd')].map(node => node.textContent);
  assert.deepEqual(values, ['搜索 未知 次，抓取 未知 次，失败 未知 次', '搜索 0 次，抓取 0 次，失败 0 次']);
  mounted.dispose();
  window.close();
});

test('T06: pace shows projected exhaustion and insufficient data without deriving its own forecast', async () => {
  for (const [value, expected] of [
    [pace({ lasts_until_reset: false, projected_empty_at: '2026-11-15T00:00:00Z' }), /预计 2026-11-15 00:00 UTC 用完/],
    [pace({ rate_per_day: null, reason: 'insufficient_data' }), /^数据不足$/],
    [pace({ rate_per_day: 0, projected_empty_at: null, lasts_until_reset: true }), /每天消耗 0 credits，能撑到重置/],
    [pace({ projected_empty_at: null, lasts_until_reset: null }), /预计用完时间未知/],
  ]) {
    const { window, root } = setup();
    const mounted = await mountUsage(root, { usageView: async () => view([provider({ pace: [value] })]) });
    assert.match(card(root).querySelector('.usage-pace').textContent, expected);
    mounted.dispose();
    window.close();
  }
});

test('T06: multiple keys start collapsed, use Core totals and expand to fingerprint-only rows', async () => {
  const { window, root } = setup();
  const total = { scope: 'key', unit: 'credits', key_count: 2, remaining: null, limit: 2000, message: '部分 Key 未知' };
  const mounted = await mountUsage(root, { usageView: async () => view([provider({
    current: [report(), report({ key_fingerprint: 'fp-two', remaining: null })], totals: [total],
  })]) });
  assert.equal(card(root).querySelector('.usage-amount').textContent, '剩余 未知 / 上限 2,000 credits');
  assert.match(card(root).textContent, /部分 Key 未知/);
  const details = card(root).querySelector('details');
  assert.equal(details.open, false);
  assert.equal(details.querySelector('summary').textContent, '展开 2 个 Key');
  assert.deepEqual([...details.querySelectorAll('strong')].map(node => node.textContent), ['fp-one', 'fp-two']);
  details.querySelector('summary').click();
  await flush();
  assert.equal(details.open, true);
  assert.equal(details.querySelector('summary').textContent, '收起 2 个 Key');
  details.querySelector('summary').click();
  await flush();
  assert.equal(details.open, false);
  assert.equal(details.querySelector('summary').textContent, '展开 2 个 Key');
  mounted.dispose();
  window.close();
});

test('T06: shared team totals are displayed once and different units have separate charts', async () => {
  const { window, root } = setup();
  const mounted = await mountUsage(root, { usageView: async () => view([provider({
    current: [report({ scope: 'team' }), report({ scope: 'team', key_fingerprint: 'fp-two' })],
    totals: [{ scope: 'team', unit: 'credits', key_count: 2, remaining: 600, limit: 1000, message: '' }],
    history: [point({ scope: 'team' }), point({ scope: 'team', remaining: 600, fetched_at: '2026-11-12T00:00:00Z' }),
      point({ unit: 'usd' }), point({ unit: 'usd', remaining: 200, fetched_at: '2026-11-12T00:00:00Z' })],
  })]) });
  assert.equal(card(root).querySelector('.usage-amount').textContent, '剩余 600 / 上限 1,000 credits');
  assert.equal(card(root).querySelectorAll('figure').length, 2);
  mounted.dispose();
  window.close();
});

test('T06: initial read, refresh all and single-card refresh use the API and preserve unrelated cards', async () => {
  const { window, root } = setup();
  const calls = [];
  const other = provider({ id: 'exa', label: 'Exa' });
  const mounted = await mountUsage(root, { usageView: async (id, refresh) => {
    calls.push([id, refresh]);
    return view(id ? [provider({ totals: [{ scope: 'key', unit: 'credits', key_count: 1, remaining: 500, limit: 1000, message: '' }] })]
      : [provider(), other]);
  } });
  assert.deepEqual(calls, [[null, true]]);
  const otherChart = card(root, 'exa').querySelector('svg');
  const refresh = card(root).querySelector('[data-action="refresh-provider"]');
  refresh.focus();
  refresh.click();
  await flush();
  assert.deepEqual(calls.at(-1), ['tavily', true]);
  assert.equal(card(root, 'exa').querySelector('svg'), otherChart);
  assert.match(card(root).querySelector('.usage-amount').textContent, /剩余 500/);
  assert.equal(window.document.activeElement, refresh);
  root.querySelector('[data-action="refresh-all"]').click();
  await flush();
  assert.deepEqual(calls, [[null, true], ['tavily', true], [null, true]]);
  mounted.dispose();
  window.close();
});

test('T06: charts never schedule animation, retain null gaps and remain unchanged while idle', async () => {
  const { window, root } = setup();
  window.matchMedia = () => ({ matches: true });
  window.requestAnimationFrame = () => { throw new Error('usage chart must stay static'); };
  window.setInterval = () => { throw new Error('usage chart must not poll'); };
  const mounted = await mountUsage(root, { usageView: async () => view([provider({ history: [
    point(), point({ remaining: null, fetched_at: '2026-11-11T00:00:00Z' }),
    point({ remaining: 600, fetched_at: '2026-11-12T00:00:00Z' }),
  ] })]) });
  const svg = card(root).querySelector('svg');
  assert.equal(svg.querySelectorAll('polyline').length, 2, 'unknown observations break a line');
  const markup = svg.outerHTML;
  await flush();
  await flush();
  assert.equal(card(root).querySelector('svg'), svg);
  assert.equal(svg.outerHTML, markup);
  assert.equal(svg.querySelector('animate'), null);
  mounted.dispose();
  window.close();
});

test('T06: provider text and CLI notices are literal text, including chart tooltips and key rows', async () => {
  const { window, root } = setup();
  const malicious = '<img src=x onerror="alert(1)"><script>alert(1)</script>';
  const mounted = await mountUsage(root, { usageView: async () => view([
    provider({ label: malicious, current: [report({ message: malicious, key_fingerprint: malicious }),
      report({ key_fingerprint: 'fp-two' })],
    totals: [{ scope: malicious, unit: malicious, key_count: 2, remaining: 1, limit: 2, message: malicious }],
    history: [point({ key_fingerprint: malicious }), point({ key_fingerprint: malicious, fetched_at: '2026-11-12T00:00:00Z' })] }),
    provider({ id: 'unsupported', balance_supported: false, balance_note: malicious }),
  ], { usage_error: malicious }) });
  assert.ok(root.textContent.includes(malicious));
  assert.equal(root.querySelectorAll('img, script').length, 0);
  assert.ok(card(root).querySelector('svg title').textContent.includes('走势'));
  assert.ok(card(root).querySelector('circle title').textContent.includes(malicious));
  mounted.dispose();
  window.close();
});

test('T06: old CLI has an update notice instead of a page error', async () => {
  const { window, root } = setup();
  const mounted = await mountUsage(root, { usageView: async () => view([], {
    status: 'cli_update_required', message: '当前 CLI 不支持用量查询，请更新 CLI 后重试。',
  }) });
  assert.match(root.querySelector('[data-notice]').textContent, /请更新 CLI/);
  assert.equal(root.querySelector('[data-error]').textContent, '');
  assert.equal(root.querySelectorAll('.usage-card').length, 0);
  mounted.dispose();
  window.close();
});

test('T06: updating an old CLI can be retried in place without navigating away', async () => {
  const { window, root } = setup();
  let old = true;
  const mounted = await mountUsage(root, { usageView: async () => old
    ? view([], { status: 'cli_update_required', message: '请更新 CLI。' }) : view() });
  assert.match(root.querySelector('[data-updated]').textContent, /未知/);
  const refresh = root.querySelector('[data-action="refresh-all"]');
  assert.equal(refresh.disabled, false);
  old = false;
  refresh.click();
  await flush();
  assert.ok(card(root));
  assert.equal(root.querySelector('[data-notice]').textContent, '');
  mounted.dispose();
  window.close();
});

test('T06: one point per key never invents a trend between different keys', async () => {
  const { window, root } = setup();
  const mounted = await mountUsage(root, { usageView: async () => view([provider({ history: [
    point(), point({ key_fingerprint: 'fp-two', fetched_at: '2026-11-12T00:00:00Z' }),
  ] })]) });
  assert.equal(card(root).querySelector('svg'), null);
  assert.match(card(root).querySelector('figure').textContent, /数据不足/);
  mounted.dispose();
  window.close();
});

test('T06: an initial IPC failure remains retryable', async () => {
  const { window, root } = setup();
  let fail = true;
  const mounted = await mountUsage(root, { usageView: async () => {
    if (fail) throw '读取用量超时';
    return view();
  } });
  assert.match(root.querySelector('[data-error]').textContent, /读取用量超时/);
  assert.equal(card(root), null);
  fail = false;
  root.querySelector('[data-action="refresh-all"]').click();
  await flush();
  assert.ok(card(root));
  assert.equal(root.querySelector('[data-error]').textContent, '');
  mounted.dispose();
  window.close();
});

test('T06: failures preserve previous cards and retry clears normalized errors', async () => {
  const { window, root } = setup();
  let fail = false;
  const mounted = await mountUsage(root, { usageView: async () => {
    if (fail) throw { code: 'usage_view_failed', message: 'worker failed' };
    return view();
  } });
  fail = true;
  root.querySelector('[data-action="refresh-all"]').click();
  await flush();
  assert.equal(root.querySelector('[data-error]').textContent, '用量读取失败，请重试。');
  assert.ok(card(root));
  fail = false;
  root.querySelector('[data-action="refresh-all"]').click();
  await flush();
  assert.equal(root.querySelector('[data-error]').textContent, '');
  mounted.dispose();
  window.close();
});

test('T06: duplicate refreshes are refused and disposal ignores late replies', async () => {
  const { window, root } = setup();
  let release;
  let calls = 0;
  const controller = new AbortController();
  const pending = mountUsage(root, { usageView: async () => {
    calls += 1;
    return new Promise(resolve => { release = resolve; });
  } }, { signal: controller.signal });
  root.querySelector('[data-action="refresh-all"]').dispatchEvent(new window.MouseEvent('click'));
  assert.equal(calls, 1);
  assert.equal(root.querySelector('.usage-page').getAttribute('aria-busy'), 'true');
  controller.abort();
  release(view());
  const mounted = await pending;
  assert.equal(root.querySelectorAll('.usage-card').length, 0);
  mounted.dispose();
  window.close();
});

test('T06: 去设置 navigates through the app, updates title and focus, and rejects stale navigation callbacks', async () => {
  const { window, root } = setup();
  const nav = window.document.createElement('nav');
  window.document.body.append(nav);
  let staleNavigate;
  const list = [
    { id: 'usage', label: '用量', number: '05', mount: async (node, api, options) => {
      staleNavigate = options.navigate;
      return mountUsage(node, api, options);
    } },
    { id: 'sources', label: '服务商', number: '04', mount: async node => {
      node.innerHTML = '<h1>服务商</h1>';
      return { dispose() {} };
    } },
    { id: 'other', label: '其他', number: '06', mount: async node => { node.innerHTML = '<h1>其他</h1>'; } },
  ];
  const app = createNavigation(root, nav, async (command, args) => {
    assert.equal(command, 'usage_view');
    assert.deepEqual(args, { provider: null, refresh: true });
    return view();
  }, list);
  await app.select(list[0]);
  root.querySelector('[data-action="settings"]').click();
  await flush();
  assert.equal(root.querySelector('h1').textContent, '服务商');
  assert.equal(window.document.title, '服务商 · Multi Search');
  assert.equal(window.document.activeElement, root.querySelector('h1'));
  assert.equal(nav.querySelector('[data-page="sources"]').getAttribute('aria-current'), 'page');
  await app.select(list[2]);
  staleNavigate('sources');
  await flush();
  assert.equal(root.querySelector('h1').textContent, '其他');
  app.dispose();
  window.close();
});
