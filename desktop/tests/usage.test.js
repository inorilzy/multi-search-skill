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
const total = (overrides = {}) => ({
  remaining: 600, limit: 1000, percent: 60, unit: 'credits', relative: false, ...overrides,
});
const account = (overrides = {}) => ({
  id: 'default', name: '默认账号', source: 'manual', total: total(),
  keys: [{ key_fingerprint: 'fp-one', report: report() }], ...overrides,
});
const provider = (overrides = {}) => {
  const current = overrides.current || [report()];
  return {
    id: 'tavily', label: 'Tavily', balance_supported: true, balance_note: '', current,
    accounts: [account({ keys: current.filter(row => row.key_fingerprint)
      .map(row => ({ key_fingerprint: row.key_fingerprint, report: row })) })], total: total(), alert: null,
    totals: [{ scope: 'key', unit: 'credits', key_count: 1, remaining: 600, limit: 1000, message: '' }],
    history: [point(), point({ remaining: 600, fetched_at: '2026-11-12T00:00:00Z' })], pace: [pace()],
    calls: { today: counts, last_7_days: { search: 12, scrape: 5, failures: 2 }, daily: [] }, ...overrides,
  };
};
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

test('T06: collapsed rows contain only the provider summary and the page has one footer note', async () => {
  const { window, root } = setup();
  const mounted = await mountUsage(root, { usageView: async () => view() });
  const row = card(root);
  assert.equal(row.tagName, 'DETAILS');
  assert.equal(row.open, false);
  const summary = row.querySelector('summary');
  assert.deepEqual([...summary.children].map(node => node.className), [
    'provider-icon', 'provider-identity', 'provider-meter', 'provider-status', 'provider-expand',
  ]);
  assert.equal(summary.querySelector('.provider-icon').textContent, 't');
  assert.equal(summary.querySelector('.provider-name').textContent, 'Tavily');
  assert.equal(summary.querySelector('.provider-counts').textContent, '1 个独立 Key');
  assert.equal(summary.querySelector('.meter-value').textContent, '60%');
  assert.equal(summary.querySelector('.provider-status').textContent, '重置时间：2026-12-01 00:00 UTC');
  assert.doesNotMatch(summary.textContent, /本机|配速|走势|刷新|去设置|手动添加|默认账号/);
  assert.equal(summary.querySelector('button, .account-list, .usage-chart'), null);
  assert.equal(row.querySelector('.provider-details').parentNode, row);
  assert.equal(row.querySelector('[data-action="refresh-provider"]').closest('.provider-details'),
    row.querySelector('.provider-details'));
  assert.deepEqual([...root.querySelector('.usage-head').children].map(node => node.textContent),
    ['刷新全部', root.querySelector('[data-updated]').textContent]);
  assert.equal(root.querySelectorAll('[data-footnote]').length, 1);
  assert.equal(root.querySelector('.usage-page').lastElementChild, root.querySelector('[data-footnote]'));
  assert.equal(root.querySelector('[data-footnote]').textContent,
    '刷新遵守服务商缓存时长。本机统计不等于服务商计费次数；历史只保留 30 天。');
  mounted.dispose();
  window.close();
});

test('T06: expanded account and Key meters use supplied totals and keep missing reports unknown', async () => {
  const { window, root } = setup();
  const personal = account({ id: 'acc_personal', name: '个人', source: 'oauth',
    total: total({ remaining: 300, percent: 30 }), keys: [
      { key_fingerprint: 'fp-one', report: report({ remaining: 100, limit: 500 }) },
      { key_fingerprint: 'fp-two', report: report({ remaining: 200, limit: 500 }) },
    ] });
  const work = account({ id: 'acc_work', name: '公司', source: 'manual',
    total: total({ remaining: 250, limit: 500, percent: 50 }),
    keys: [{ key_fingerprint: 'fp-missing', report: null }] });
  const mounted = await mountUsage(root, { usageView: async () => view([provider({
    total: total({ remaining: 550, limit: 1500, percent: 36.67 }),
    accounts: [account({ keys: [] }), personal, work],
  })]) });
  const row = card(root);
  assert.equal(row.querySelector('.provider-counts').textContent, '2 个账号 · 3 个 Key');
  assert.equal(row.querySelector('.provider-meter [role="progressbar"]').getAttribute('aria-valuenow'), '36.67');
  row.querySelector('summary').click();
  const accounts = [...row.querySelectorAll('.account-row')];
  assert.deepEqual(accounts.map(node => node.dataset.account), ['acc_personal', 'acc_work']);
  assert.deepEqual(accounts.map(node => node.querySelector('.account-name').textContent), ['个人', '公司']);
  assert.equal(row.querySelector('.account-source'), null);
  assert.deepEqual(accounts.map(node => node.querySelector('.account-summary [role="progressbar"]')
    .getAttribute('aria-valuenow')), ['30', '50']);
  assert.deepEqual(accounts.map(node => node.querySelector('.account-identity .quota-value').textContent),
    ['剩余 300 / 上限 1,000 credits', '剩余 250 / 上限 500 credits']);
  const keys = [...accounts[0].querySelectorAll('.account-keys > .key-row')];
  assert.deepEqual(keys.map(node => node.querySelector('[role="progressbar"]').getAttribute('aria-valuenow')), ['20', '40']);
  assert.deepEqual(keys.map(node => node.querySelector('.quota-value').textContent),
    ['剩余 100 / 上限 500 credits', '剩余 200 / 上限 500 credits']);
  assert.equal(keys[0].querySelector('[role="progressbar"]').getAttribute('aria-label'), 'Key 1剩余额度');
  const missing = accounts[1].querySelector('.key-row');
  assert.equal(missing.querySelector('.key-label').textContent, 'Key 3');
  assert.equal(missing.dataset.fingerprint, 'fp-missing');
  assert.equal(missing.querySelector('[role="progressbar"]'), null);
  assert.equal(missing.querySelector('.quota-value').textContent, '额度暂不可查询');
  assert.equal(missing.querySelectorAll('.quota-value').length, 1);
  assert.equal(missing.querySelector('.meter-value, .key-kind'), null);
  mounted.dispose();
  window.close();
});

test('T06: collapsed reminders follow Core priority and meter thresholds without repeating the reminder', async () => {
  const { window, root } = setup();
  const providers = [
    ['critical', 4.99, 'critical', '余额即将用尽'], ['wont_last', 10, 'low', '撑不到重置'],
    ['low', 19.99, 'low', '余额低'], ['needs_credential', 20, 'normal', '部分额度未提供'],
  ];
  const mounted = await mountUsage(root, { usageView: async () => view(providers.map(([alert, percent]) =>
    provider({ id: alert, total: total({ percent }), alert }))) });
  for (const [id, percent, level, text] of providers) {
    const summary = card(root, id).querySelector('summary');
    assert.equal(summary.querySelector('.meter').dataset.level, level, `${percent}%`);
    assert.equal(summary.querySelector('.provider-status').textContent, text);
    assert.equal(summary.querySelectorAll('.meter-alert').length, 1);
    assert.equal(summary.querySelector('.meter-alert').dataset.kind, id);
    assert.equal(summary.querySelector('.meter-state'), null);
    assert.doesNotMatch(summary.querySelector('.provider-status').textContent, /重置时间/);
  }
  mounted.dispose();
  window.close();
});

test('credential reminders describe partial quota availability while keeping account errors and unknown totals explicit', async () => {
  for (const remaining of [4.74, 0, null]) {
    const { window, root } = setup();
    const mounted = await mountUsage(root, { usageView: async () => view([provider({
      alert: 'needs_credential', total: total({ remaining, limit: remaining == null ? null : 5,
        percent: remaining == null ? null : remaining * 20, unit: 'usd' }),
      current: [report({ scope: 'account', status: 'needs_credential', remaining: null, limit: null, used: null,
        message: '请重新登录账号。' })],
    })]) });
    const row = card(root);
    const summary = row.querySelector('summary');
    assert.equal(summary.querySelector('.provider-status').textContent,
      remaining == null ? '需要凭据' : '部分额度未提供');
    assert.equal(summary.querySelector('.meter-alert').dataset.kind, 'needs_credential');
    if (remaining != null) assert.doesNotMatch(summary.textContent, /需要凭据/);
    assert.equal(row.querySelector('.usage-error').textContent, '请重新登录账号。');
    mounted.dispose();
    window.close();
  }
});

test('T06: relative provider and account totals use Core percent and no history invents no bar', async () => {
  const { window, root } = setup();
  const relative = total({ remaining: 12.5, limit: null, percent: 25, unit: 'usd', relative: true });
  const fresh = total({ remaining: 12.5, limit: null, percent: null, unit: 'usd', relative: true });
  const mounted = await mountUsage(root, { usageView: async () => view([
    provider({ total: relative, accounts: [account({ id: 'acc_relative', name: '个人', total: relative })], history: [] }),
    provider({ id: 'fresh', total: fresh, accounts: [account({ id: 'acc_fresh', name: '工作', total: fresh, keys: [] })], history: [] }),
  ]) });
  const summary = card(root).querySelector('summary');
  assert.equal(summary.querySelector('.meter-value').textContent, '剩余 12.5 美元');
  assert.equal(summary.querySelector('.meter-relative').textContent, '相对');
  assert.equal(summary.querySelector('[role="progressbar"]').getAttribute('aria-valuenow'), '25');
  assert.match(summary.querySelector('[role="progressbar"]').getAttribute('aria-valuetext'), /相对值 25%/);
  summary.click();
  assert.equal(card(root).querySelector('.account-summary .meter-relative').textContent, '相对');
  assert.equal(card(root).querySelector('.account-summary [role="progressbar"]').getAttribute('aria-valuenow'), '25');
  const freshSummary = card(root, 'fresh').querySelector('summary');
  assert.equal(freshSummary.querySelector('[role="progressbar"]'), null);
  assert.equal(freshSummary.querySelector('.meter-value').textContent, '剩余 12.5 美元');
  assert.equal(freshSummary.querySelector('.meter-empty'), null);
  assert.equal(card(root, 'fresh').querySelector('.account-summary .quota-value').textContent, '剩余 12.5 美元');
  assert.equal(freshSummary.querySelector('.provider-counts').textContent, '1 个账号 · 0 个 Key');
  mounted.dispose();
  window.close();
});

test('T06: unsupported providers keep actual call counts and use a compact quota label when unavailable', async () => {
  const { window, root } = setup();
  const mounted = await mountUsage(root, { usageView: async () => view([
    provider({ id: 'zero', balance_supported: false, calls: {
      today: { search: 0, scrape: 0, failures: 0 }, last_7_days: {}, daily: [],
    } }),
    provider({ id: 'unknown', balance_supported: false, accounts: [account({ keys: [] })],
      calls: { today: {}, last_7_days: {}, daily: [] } }),
  ]) });
  assert.equal(card(root, 'zero').querySelector('.provider-status').textContent, '今天调用 0 次');
  assert.equal(card(root, 'unknown').querySelector('.provider-status').textContent, '未提供额度');
  assert.equal(card(root, 'unknown').querySelector('.account-row'), null);
  assert.doesNotMatch(card(root, 'unknown').querySelector('[data-body] > .account-list').textContent, /独立 Key/);
  assert.equal(root.querySelector('[role="progressbar"]'), null);
  mounted.dispose();
  window.close();
});

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
  assert.equal(root.querySelector('.eyebrow').classList.contains('visually-hidden'), true);
  assert.equal(root.querySelector('h1').getAttribute('tabindex'), '-1');
  assert.equal(root.querySelector('h1').className, 'visually-hidden');
  card(root).querySelector('summary').click();
  assert.equal(card(root).open, true);
  assert.doesNotMatch(card(root).querySelector('[data-body]').textContent, /正常/);
  const extra = card(root).querySelector('.usage-extra');
  assert.equal(extra.tagName, 'DETAILS');
  assert.equal(extra.open, false);
  assert.equal(extra.querySelector('summary').textContent, '趋势与明细');
  assert.equal(card(root).querySelector('.usage-chart').closest('details'), extra);
  extra.querySelector('summary').click();
  assert.equal(extra.open, true);
  assert.match(card(root).textContent, /剩余 600 \/ 上限 1,000 credits/);
  assert.match(card(root).textContent, /重置时间：2026-12-01 00:00 UTC/);
  assert.match(card(root).textContent, /每天消耗 10 credits，能撑到重置/);
  assert.match(card(root).textContent, /本机调用 · 今天搜索 4 次，抓取 2 次，失败 1 次/);
  assert.match(card(root).textContent, /本机调用 · 近 7 天搜索 12 次，抓取 5 次，失败 2 次/);
  const progress = card(root).querySelector('[role="progressbar"]');
  assert.equal(progress.getAttribute('aria-valuenow'), '60');
  assert.equal(progress.getAttribute('aria-valuemax'), '100');
  assert.match(progress.getAttribute('aria-label'), /剩余额度/);
  const svg = card(root).querySelector('.usage-chart svg');
  assert.equal(svg.getAttribute('role'), 'img');
  assert.match(svg.getAttribute('aria-label'), /近 30 天剩余走势/);
  assert.equal(svg.querySelectorAll('polyline').length, 1);
  assert.equal(svg.querySelectorAll('circle').length, 2);
  assert.equal(root.querySelectorAll('.provider-list').length, 1);
  assert.equal(card(root).parentNode, root.querySelector('[data-providers]'));
  assert.match(root.querySelector('[data-footnote]').textContent, /本机统计不等于服务商计费次数/);
  mounted.dispose();
  window.close();
});

test('T06: credential, unsupported, error and insufficient-data states name their reasons', async () => {
  const { window, root } = setup();
  const providers = [
    provider({ id: 'exa', label: 'Exa', alert: 'needs_credential',
      current: [report({ status: 'needs_credential', message: '请配置管理 Key。' })] }),
    provider({ id: 'jina', label: 'Jina', current: [report({ status: 'error', message: '服务商查询超时。' })] }),
    provider({ id: 'new', label: 'New', current: [], totals: [], history: [], pace: [] }),
    provider({ id: 'brave', label: 'Brave', balance_supported: false, balance_note: '没有余额查询接口。',
      current: [report({ status: 'unsupported' })] }),
  ];
  const mounted = await mountUsage(root, { usageView: async () => view(providers) });
  assert.match(card(root, 'exa').textContent, /部分额度未提供.*请配置管理 Key/);
  assert.match(card(root, 'jina').textContent, /查询失败.*服务商查询超时/);
  assert.equal(card(root, 'new').querySelector('.account-row'), null);
  assert.equal(card(root, 'new').querySelector('.provider-meter .meter-value').textContent, '60%');
  assert.equal(card(root, 'new').querySelector('.usage-pace').closest('details').open, false);
  assert.equal(root.querySelectorAll('.provider-list').length, 1);
  assert.equal(card(root, 'brave').parentNode, root.querySelector('[data-providers]'));
  assert.equal(card(root, 'brave').querySelector('.provider-status').textContent, '今天调用 6 次');
  card(root, 'brave').querySelector('summary').click();
  assert.equal(card(root, 'brave').querySelector('.usage-extra .usage-note').textContent, '没有余额查询接口。');
  assert.equal(card(root, 'brave').querySelector('.usage-chart'), null);
  assert.equal(card(root, 'brave').querySelector('[role="progressbar"]'), null);
  mounted.dispose();
  window.close();
});

test('T06: null quotas, timestamps, rate and missing call counts stay unknown, while real zero stays zero', async () => {
  const { window, root } = setup();
  const unknown = provider({
    current: [report({ remaining: null, limit: null, used: null, unit: '', resets_at: null, fetched_at: null })],
    total: total({ remaining: null, limit: null, percent: null, unit: null }),
    accounts: [account({ total: total({ remaining: null, limit: null, percent: null, unit: null }),
      keys: [{ key_fingerprint: 'fp-one', report: report({ remaining: null, limit: null, used: null, unit: '',
        resets_at: null, fetched_at: null }) }] })],
    totals: [{ scope: 'key', unit: '', key_count: 1, remaining: null, limit: null, message: '' }],
    history: [], pace: [pace({ rate_per_day: null, reason: null })],
    calls: { today: {}, last_7_days: { search: 0, scrape: 0, failures: 0 }, daily: [] },
  });
  const mounted = await mountUsage(root, { usageView: async () => view([unknown]) });
  card(root).querySelector('summary').click();
  assert.equal(card(root).querySelector('.account-name').textContent, '独立 Key');
  assert.equal(card(root).querySelector('.account-summary .quota-value, .account-summary .meter'), null);
  assert.equal(card(root).querySelector('.key-row').textContent, 'Key 1额度暂不可查询');
  assert.equal(card(root).querySelector('[role="progressbar"]'), null);
  assert.doesNotMatch(card(root).textContent, /默认账号|剩余 未知|上限 未知|暂无上限|重置时间：未知/);
  assert.match(root.querySelector('[data-updated]').textContent, /最近更新：未知/);
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
    card(root).querySelector('summary').click();
    assert.match(card(root).querySelector('.usage-pace').textContent, expected);
    mounted.dispose();
    window.close();
  }
});

test('T06: provider starts collapsed, uses Core totals and groups standalone Keys without a virtual account quota', async () => {
  const { window, root } = setup();
  const combined = total({ remaining: null, limit: 2000, percent: null });
  const reports = [report(), report({ key_fingerprint: 'fp-two', remaining: null })];
  const mounted = await mountUsage(root, { usageView: async () => view([provider({
    current: reports, total: combined,
    accounts: [account({ total: combined,
      keys: reports.map(row => ({ key_fingerprint: row.key_fingerprint, report: row })) })],
    totals: [{ scope: 'key', unit: 'credits', key_count: 2, remaining: null, limit: 2000, message: '部分 Key 未知' }],
  })]) });
  const details = card(root);
  assert.equal(details.open, false);
  const summary = details.querySelector('summary');
  assert.equal(summary.querySelector('.provider-counts').textContent, '2 个独立 Key');
  assert.equal(summary.querySelector('.meter-value').textContent, '上限 2,000 credits');
  assert.equal(summary.querySelector('[role="progressbar"]'), null);
  summary.click();
  await flush();
  assert.equal(details.open, true);
  assert.equal(details.querySelector('.account-summary .quota-value'), null);
  assert.match(details.querySelector('.usage-extra').textContent, /部分 Key 未知/);
  assert.deepEqual([...details.querySelectorAll('.account-keys .key-label')].map(node => node.textContent),
    ['Key 1', 'Key 2']);
  assert.deepEqual([...details.querySelectorAll('.key-row')].map(node => node.dataset.fingerprint), ['fp-one', 'fp-two']);
  assert.equal(details.querySelectorAll('.account-row').length, 1);
  assert.equal(details.querySelectorAll('.account-keys .key-row').length, 2);
  summary.click();
  await flush();
  assert.equal(details.open, false);
  mounted.dispose();
  window.close();
});

test('T06: shared team totals are displayed once and different units have separate charts', async () => {
  const { window, root } = setup();
  const mounted = await mountUsage(root, { usageView: async () => view([provider({
    current: [report({ scope: 'team' }), report({ scope: 'team', key_fingerprint: 'fp-two' })],
    accounts: [account({ id: 'acc_team', name: '团队', keys: ['fp-one', 'fp-two'].map(key_fingerprint =>
      ({ key_fingerprint, report: report({ key_fingerprint, scope: 'team' }) })) })],
    totals: [{ scope: 'team', unit: 'credits', key_count: 2, remaining: 600, limit: 1000, message: '' }],
    history: [point({ scope: 'team' }), point({ scope: 'team', remaining: 600, fetched_at: '2026-11-12T00:00:00Z' }),
      point({ unit: 'usd' }), point({ unit: 'usd', remaining: 200, fetched_at: '2026-11-12T00:00:00Z' })],
  })]) });
  card(root).querySelector('summary').click();
  assert.equal(card(root).querySelector('.account-summary .quota-value').textContent, '剩余 600 / 上限 1,000 credits');
  assert.equal(card(root).querySelectorAll('[data-body] .quota-value').length, 1);
  assert.equal(card(root).querySelector('[data-total]'), null);
  assert.deepEqual([...card(root).querySelectorAll('.key-kind')].map(node => node.textContent),
    ['使用账号额度', '使用账号额度']);
  assert.equal(card(root).querySelector('.provider-meter [role="progressbar"]').getAttribute('aria-valuenow'), '60');
  assert.equal(card(root).querySelectorAll('figure').length, 2);
  mounted.dispose();
  window.close();
});

test('Tavily account credits own the balance while identical key credits do not create another pool', async () => {
  const { window, root } = setup();
  const shared = report({ scope: 'account' });
  const data = provider({ current: [report(), shared], accounts: [account({ id: 'acc_personal', name: '个人' })], totals: [
    { scope: 'key', unit: 'credits', key_count: 1, remaining: 600, limit: 1000, message: '' },
    { scope: 'account', unit: 'credits', key_count: 1, remaining: 600, limit: 1000, message: '' },
  ], history: [point(), point({ remaining: 600, fetched_at: '2026-11-12T00:00:00Z' }),
    point({ scope: 'account' }), point({ scope: 'account', remaining: 600, fetched_at: '2026-11-12T00:00:00Z' })],
  pace: [pace(), pace({ scope: 'account' })] });
  const before = JSON.stringify(data);
  const mounted = await mountUsage(root, { usageView: async () => view([data]) });
  const row = card(root);
  assert.equal(row.querySelector('.provider-meter .meter-value').textContent, '60%');
  assert.equal(row.querySelector('.account-summary [role="progressbar"]').getAttribute('aria-valuenow'), '60');
  const key = row.querySelector('.key-row');
  assert.equal(key.querySelector('.key-kind').textContent, '共享账户余额');
  assert.equal(key.querySelector('.meter, .quota-value'), null);
  assert.doesNotMatch(key.textContent, /剩余|上限|已用/);
  assert.deepEqual([...row.querySelectorAll('[data-body] .quota-value')].map(node => node.textContent),
    ['剩余 600 / 上限 1,000 credits']);
  assert.equal(row.querySelector('[data-total], .usage-status'), null);
  assert.equal(row.querySelectorAll('.usage-pace').length, 1);
  assert.deepEqual([...row.querySelectorAll('figcaption')].map(node => node.textContent),
    ['近 30 天剩余走势 · 账户 · credits']);
  assert.equal(row.querySelectorAll('.usage-chart circle').length, 2);
  assert.equal(JSON.stringify(data), before, 'presentation must preserve every public report and total');
  mounted.dispose();
  window.close();
});

test('Tavily keeps distinct key limits and usage as details of the shared account balance, including zero', async () => {
  const { window, root } = setup();
  const reports = [report({ remaining: 250, limit: 300, used: 50 }), report({ scope: 'account' }),
    report({ key_fingerprint: 'fp-two', remaining: 0, limit: 0, used: 0 }),
    report({ key_fingerprint: 'fp-two', scope: 'account' }),
    report({ key_fingerprint: 'fp-three', remaining: 100, limit: 500 }),
    report({ key_fingerprint: 'fp-three', scope: 'account' })];
  const mounted = await mountUsage(root, { usageView: async () => view([provider({ current: reports,
    accounts: [account({ id: 'acc_main', name: '个人', keys: [0, 2, 4].map(index => ({ key_fingerprint: reports[index].key_fingerprint,
      report: reports[index] })) })] })]) });
  const keys = [...card(root).querySelectorAll('.key-row')];
  assert.deepEqual(keys.map(node => node.querySelector('.quota-value').textContent),
    ['Key 上限 300 credits；Key 已用 50 credits', 'Key 上限 0 credits；Key 已用 0 credits',
      'Key 上限 500 credits；Key 已用 400 credits']);
  assert.ok(keys.every(node => node.querySelector('.meter') === null));
  assert.ok(keys.every(node => node.querySelector('.key-kind').textContent === '共享账户余额'));
  mounted.dispose();
  window.close();
});

test('Tavily only merges successful credit reports for the same key with a known account quota', async () => {
  const cases = [
    [report({ scope: 'account', key_fingerprint: 'fp-other' })],
    [report({ scope: 'account', remaining: null, limit: null, used: null })],
    [report({ scope: 'account', status: 'error' })],
    [report({ scope: 'account', unit: 'usd' })],
    [report({ scope: 'account' }), 'exa'],
  ];
  for (const [shared, id = 'tavily'] of cases) {
    const { window, root } = setup();
    const mounted = await mountUsage(root, { usageView: async () => view([provider({ id,
      current: [report(), shared] })]) });
    assert.equal(card(root, id).querySelector('.key-row [role="progressbar"]').getAttribute('aria-valuenow'), '60');
    assert.equal(card(root, id).querySelector('.key-row .quota-value').textContent, '剩余 600 / 上限 1,000 credits');
    assert.equal(card(root, id).querySelector('.key-kind'), null);
    assert.equal(card(root, id).querySelector('[data-total]'), null);
    mounted.dispose();
    window.close();
  }
});

test('Tavily preserves unpaired key balances, trends and failed reports beside shared credits', async () => {
  const { window, root } = setup();
  const keyOnly = report({ key_fingerprint: 'fp-key-only', remaining: 100, limit: 500 });
  const failed = report({ key_fingerprint: 'fp-failed', status: 'error', remaining: null, limit: null, used: null,
    message: 'Key 查询失败。' });
  const mounted = await mountUsage(root, { usageView: async () => view([provider({
    current: [report(), report({ scope: 'account' }), keyOnly, failed,
      report({ key_fingerprint: 'fp-failed', scope: 'account' })],
    accounts: [account({ id: 'acc_main', name: '个人', keys: [report(), keyOnly, failed].map(row => ({
      key_fingerprint: row.key_fingerprint, report: row,
    })) })],
    history: [point(), point({ scope: 'account' }),
      point({ key_fingerprint: 'fp-key-only' }),
      point({ key_fingerprint: 'fp-key-only', remaining: 100, fetched_at: '2026-11-12T00:00:00Z' })],
    pace: [pace(), pace({ scope: 'account' }), pace({ key_fingerprint: 'fp-key-only' })],
  })]) });
  const row = card(root);
  const keys = [...row.querySelectorAll('.key-row')];
  assert.equal(keys[0].querySelector('.meter'), null);
  assert.equal(keys[1].querySelector('[role="progressbar"]').getAttribute('aria-valuenow'), '20');
  assert.equal(keys[2].querySelector('.quota-value').textContent, '额度暂不可查询');
  assert.match(row.textContent, /Key 查询失败。/);
  assert.equal(row.querySelectorAll('.usage-error').length, 1);
  assert.equal(row.textContent.split('Key 查询失败。').length - 1, 1);
  assert.equal(row.querySelectorAll('.usage-pace').length, 2);
  const keyChart = [...row.querySelectorAll('.usage-chart')].find(node => /· Key · credits/.test(node.textContent));
  assert.equal(keyChart.querySelectorAll('circle').length, 2);
  assert.ok([...keyChart.querySelectorAll('circle title')].every(node => node.textContent.startsWith('Key 2：')));
  mounted.dispose();
  window.close();
});

test('account lists keep standalone and named Key quotas without repeating unavailable amounts', async () => {
  const { window, root } = setup();
  const standalone = report({ key_fingerprint: 'sha256:standalone', remaining: 0, limit: 50, used: 50 });
  const usd = report({ key_fingerprint: 'sha256:standalone', unit: 'usd', remaining: 2, limit: null, used: null });
  const bound = report({ key_fingerprint: 'sha256:bound', remaining: 8, limit: 10, used: 2, unit: 'usd' });
  const mounted = await mountUsage(root, {
    usageView: async () => view([provider({ id: 'exa', label: 'Exa', current: [standalone, usd, bound],
      accounts: [account({ total: total({ remaining: 9999 }), keys: [
        { key_fingerprint: standalone.key_fingerprint, report: standalone },
        { key_fingerprint: 'sha256:missing', report: null },
      ] }), account({ id: 'acc_personal', name: '个人', source: 'oauth',
        total: total({ remaining: 4.74, limit: 5, unit: 'usd', percent: 94.8 }),
        keys: [{ key_fingerprint: bound.key_fingerprint, report: bound }] })] })]),
    accountsView: () => assert.fail('usage presentation must use its supplied offline view'),
  });
  const row = card(root, 'exa');
  assert.equal(row.querySelector('.provider-counts').textContent, '1 个账号 · 3 个 Key');
  const [independent, personal] = row.querySelectorAll('.account-row');
  assert.equal(independent.dataset.standalone, 'true');
  assert.equal(independent.querySelector('.account-name').textContent, '独立 Key');
  assert.equal(independent.querySelector('.account-summary .quota-value, .account-summary .meter'), null);
  const keys = independent.querySelectorAll('.key-row');
  assert.deepEqual([...keys[0].querySelectorAll('.quota-value')].map(node => node.textContent),
    ['剩余 0 / 上限 50 credits', '剩余 2 美元']);
  assert.equal(keys[0].querySelector('[role="progressbar"]').getAttribute('aria-valuenow'), '0');
  assert.equal(keys[1].textContent, 'Key 2额度暂不可查询');
  assert.equal(personal.querySelector('.account-summary .quota-value').textContent, '剩余 4.74 / 上限 5 美元');
  assert.equal(personal.querySelector('.key-row .quota-value').textContent, '剩余 8 / 上限 10 美元');
  assert.equal(personal.querySelector('.key-row').closest('.account-row'), personal);
  assert.equal(row.querySelector('.account-source, [data-total], .usage-status, .meter-empty'), null);
  assert.doesNotMatch(row.querySelector('[data-body]').textContent, /9,999|默认账号|剩余 未知|上限 未知|暂无上限/);
  mounted.dispose();
  window.close();
});

test('a shared Tavily balance remains available for standalone Keys and accounts without a usable total', async () => {
  for (const overrides of [{}, { id: 'acc_mixed', name: '个人',
    total: total({ remaining: null, limit: null, percent: null, unit: null }) }]) {
    const { window, root } = setup();
    const mounted = await mountUsage(root, { usageView: async () => view([provider({
      current: [report(), report({ scope: 'account' })], accounts: [account(overrides)],
    })]) });
    const row = card(root);
    assert.equal(row.querySelector('.account-summary .quota-value'), null);
    assert.equal(row.querySelector('.key-row .quota-value').textContent, '剩余 600 / 上限 1,000 credits');
    assert.equal(row.querySelectorAll('[data-body] .quota-value').length, 1);
    assert.equal(row.querySelector('.key-row [role="progressbar"]').getAttribute('aria-valuenow'), '60');
    mounted.dispose();
    window.close();
  }
});

test('Tavily pairing stays inside a fingerprint and never borrows another named account balance', async () => {
  const { window, root } = setup();
  const first = report({ key_fingerprint: 'sha256:first', remaining: 20, limit: 100, used: 80 });
  const second = report({ key_fingerprint: 'sha256:second', remaining: 10, limit: 50, used: 40 });
  const mounted = await mountUsage(root, { usageView: async () => view([provider({
    current: [first, second, report({ scope: 'account', key_fingerprint: first.key_fingerprint })],
    accounts: [account({ id: 'acc_first', name: '个人', keys: [{ key_fingerprint: first.key_fingerprint, report: first }] }),
      account({ id: 'acc_second', name: '公司', total: total({ remaining: 10, limit: 50, percent: 20 }),
        keys: [{ key_fingerprint: second.key_fingerprint, report: second }] })],
  })]) });
  const [firstAccount, secondAccount] = card(root).querySelectorAll('.account-row');
  assert.equal(firstAccount.querySelector('.key-kind').textContent, '共享账户余额');
  assert.equal(firstAccount.querySelector('.key-quota').textContent, 'Key 上限 100 credits；Key 已用 80 credits');
  assert.equal(secondAccount.querySelector('.key-kind'), null);
  assert.equal(secondAccount.querySelector('.key-row .quota-value').textContent, '剩余 10 / 上限 50 credits');
  assert.equal(secondAccount.querySelector('.key-row [role="progressbar"]').getAttribute('aria-valuenow'), '20');
  mounted.dispose();
  window.close();
});

test('internal identities never appear in visible text, accessible labels, warnings or historical legends', async () => {
  const { window, root } = setup();
  const fingerprint = 'sha256:7567831d';
  const oldFingerprint = 'sha256:inactive';
  const error = `oauth-login acc_private fingerprint=${fingerprint}：查询超时，请重试。`;
  const key = report({ key_fingerprint: fingerprint, status: 'error', remaining: null, limit: null, used: null, message: error });
  let listener;
  const mounted = await mountUsage(root, { usageView: async () => view([provider({ current: [key, key],
    accounts: [account({ id: 'acc_private', name: '个人', total: total({ unit: 'sha256:unit' }),
      keys: [{ key_fingerprint: fingerprint, report: key }] })],
    total: total({ unit: 'sha256:unit', relative: true }),
    totals: [{ scope: 'key', unit: 'credits', message: error, remaining: null, limit: null, key_count: 1 }],
    history: [point({ key_fingerprint: fingerprint }),
      point({ key_fingerprint: fingerprint, fetched_at: '2026-11-12T00:00:00Z' }),
      point({ key_fingerprint: oldFingerprint }),
      point({ key_fingerprint: oldFingerprint, fetched_at: '2026-11-12T00:00:00Z' })],
    pace: [pace({ key_fingerprint: fingerprint }), pace({ key_fingerprint: oldFingerprint })],
  })], { usage_error: `acc_private：${fingerprint} 缓存不可读` }) },
  { usageRefresh: { subscribe(callback) { listener = callback; return () => {}; } } });
  const row = card(root);
  const extra = row.querySelector('.usage-extra');
  assert.equal(extra.open, false);
  assert.equal(row.querySelectorAll('.usage-error').length, 1);
  assert.equal(row.textContent.split('查询超时，请重试。').length - 1, 1);
  assert.match(row.querySelector('.usage-legend').textContent, /Key 1.*历史 Key 1/);
  const userAttributes = () => [...root.querySelectorAll('*')].flatMap(node => [...node.attributes]
    .filter(attr => attr.name.startsWith('aria-') || attr.name === 'title').map(attr => attr.value)).join('\n');
  assert.doesNotMatch(`${root.textContent}\n${userAttributes()}`, /sha256|fingerprint|oauth-login|acc_private/);
  assert.equal(row.querySelector('.key-row').dataset.fingerprint, fingerprint);
  extra.open = true;
  const extraSummary = extra.querySelector('summary');
  extraSummary.focus();
  listener(view([provider()]), 'tavily');
  assert.equal(card(root).querySelector('.usage-extra'), extra);
  assert.equal(extra.open, true);
  assert.equal(window.document.activeElement, extraSummary);
  mounted.dispose();
  window.close();
});

test('T06: initial read, refresh all and single-card refresh use the API and preserve unrelated cards', async () => {
  const { window, root } = setup();
  const calls = [];
  const other = provider({ id: 'exa', label: 'Exa' });
  const mounted = await mountUsage(root, { usageView: async (id, refresh) => {
    calls.push([id, refresh]);
    return view(id ? [provider({ total: total({ remaining: 500, percent: 50 }),
      accounts: [account({ keys: [{ key_fingerprint: 'fp-one', report: report({ remaining: 500 }) }] })],
      totals: [{ scope: 'key', unit: 'credits', key_count: 1, remaining: 500, limit: 1000, message: '' }] })]
      : [provider(), other]);
  } });
  assert.deepEqual(calls, [[null, true]]);
  card(root).querySelector('summary').click();
  card(root, 'exa').querySelector('summary').click();
  const otherChart = card(root, 'exa').querySelector('.usage-chart svg');
  const extra = card(root).querySelector('.usage-extra');
  extra.open = true;
  const refresh = card(root).querySelector('[data-action="refresh-provider"]');
  refresh.focus();
  refresh.click();
  await flush();
  assert.deepEqual(calls.at(-1), ['tavily', true]);
  assert.equal(card(root, 'exa').querySelector('.usage-chart svg'), otherChart);
  assert.match(card(root).querySelector('.key-row .quota-value').textContent, /剩余 500/);
  assert.equal(card(root).querySelector('.usage-extra'), extra);
  assert.equal(extra.open, true);
  assert.equal(card(root).querySelector('.provider-meter .meter-value').textContent, '50%');
  assert.equal(card(root).open, true);
  assert.equal(card(root, 'exa').open, true);
  assert.equal(window.document.activeElement, refresh);
  root.querySelector('[data-action="refresh-all"]').click();
  await flush();
  assert.deepEqual(calls, [[null, true], ['tavily', true], [null, true]]);
  assert.equal(card(root).open, true);
  assert.equal(card(root, 'exa').open, true);
  assert.equal(card(root).querySelector('[data-action="refresh-provider"]'), refresh);
  card(root, 'exa').querySelector('summary').click();
  root.querySelector('[data-action="refresh-all"]').click();
  await flush();
  assert.equal(card(root).open, true);
  assert.equal(card(root, 'exa').open, false);
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
  const svg = card(root).querySelector('.usage-chart svg');
  assert.equal(svg.querySelectorAll('polyline').length, 2, 'unknown observations break a line');
  const markup = svg.outerHTML;
  await flush();
  await flush();
  assert.equal(card(root).querySelector('.usage-chart svg'), svg);
  assert.equal(svg.outerHTML, markup);
  assert.equal(svg.querySelector('animate'), null);
  mounted.dispose();
  window.close();
});

test('T06: provider text and CLI notices are literal text, including chart tooltips and key rows', async () => {
  const { window, root } = setup();
  const malicious = '<img src=x onerror="alert(1)"><script>alert(1)</script>';
  const mounted = await mountUsage(root, { usageView: async () => view([
    provider({ label: malicious, current: [report({ message: malicious, key_fingerprint: 'sha256:abc123' }),
      report({ key_fingerprint: 'fp-two' })],
    total: total({ unit: malicious, relative: true }),
    accounts: [account({ id: 'acc_literal', name: malicious, source: malicious,
      keys: [{ key_fingerprint: 'sha256:abc123', report: report({ key_fingerprint: 'sha256:abc123', unit: malicious }) }] })],
    totals: [{ scope: malicious, unit: malicious, key_count: 2, remaining: 1, limit: 2, message: malicious }],
    history: [point({ key_fingerprint: 'sha256:abc123' }), point({ key_fingerprint: 'sha256:abc123', fetched_at: '2026-11-12T00:00:00Z' })] }),
    provider({ id: 'unsupported', balance_supported: false, balance_note: malicious }),
  ], { usage_error: malicious }) });
  assert.ok(root.textContent.includes(malicious));
  assert.equal(root.querySelectorAll('img, script').length, 0);
  card(root).querySelector('summary').click();
  assert.ok(card(root).querySelector('.usage-chart svg title').textContent.includes('走势'));
  assert.ok(card(root).querySelector('circle title').textContent.startsWith('Key 1：'));
  assert.equal(card(root).querySelector('.account-name').textContent, malicious);
  assert.equal(card(root).querySelector('.account-source'), null);
  assert.equal(card(root).querySelector('.key-label').textContent, 'Key 1');
  assert.doesNotMatch(root.textContent, /sha256|fingerprint|acc_literal/);
  assert.equal(card(root).querySelector('.provider-name').textContent, malicious);
  assert.ok(card(root).querySelector('.provider-meter .meter-value').textContent.includes(malicious));
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
  assert.equal(root.querySelectorAll('.provider-row').length, 0);
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
  card(root).querySelector('summary').click();
  assert.equal(card(root).querySelector('.usage-chart svg'), null);
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
  assert.equal(root.querySelectorAll('.provider-row').length, 0);
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
  card(root).querySelector('summary').click();
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
