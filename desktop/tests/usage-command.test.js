import test from 'node:test';
import assert from 'node:assert/strict';
import { managementApi } from '../ui/api.js';
import { check } from '../ui/payloads.js';

const provider = () => ({
  id: 'tavily', label: 'Tavily', balance_supported: true, balance_note: '',
  accounts: [], total: { remaining: null, limit: null, percent: null, unit: null, relative: false }, alert: null,
  current: [{
    provider: 'tavily', status: 'ok', scope: 'key', unit: 'credits', remaining: null,
    limit: 1000.5, used: 0, resets_at: null, period: 'month', key_fingerprint: null,
    error_kind: null, message: '', fetched_at: '2026-11-01T00:00:00+00:00',
  }],
  totals: [{ scope: 'key', unit: 'credits', key_count: 2, message: '部分 Key 未知', remaining: null, limit: 1000.5 }],
  history: [{ key_fingerprint: null, scope: 'key', unit: 'credits', remaining: null, limit: 1000.5, fetched_at: '2026-11-01T00:00:00+00:00' }],
  pace: [{ key_fingerprint: null, scope: 'key', unit: 'credits', rate_per_day: null, projected_empty_at: null, lasts_until_reset: null, reason: 'insufficient_data' }],
  calls: { today: { search: 0, scrape: 2, failures: 1 }, last_7_days: { search: 4, scrape: 3, failures: 1 }, daily: [{ day: '2026-11-01', search: 0, scrape: 2, failures: 1 }] },
});

const emptyUsage = () => ({ status: 'ready', message: '', schema_version: 1, retention_days: 30, providers: [] });

test('T05: usageView defaults to an offline read of all providers', async () => {
  const calls = [];
  const payload = emptyUsage();
  const api = managementApi(async (command, args) => { calls.push([command, args]); return payload; });
  assert.equal(await api.usageView(), payload);
  assert.deepEqual(calls, [['usage_view', { provider: null, refresh: false }]]);
});

test('T05: usageView sends only the provider and refresh flag', async () => {
  const calls = [];
  const api = managementApi(async (command, args) => { calls.push([command, args]); return emptyUsage(); });
  await api.usageView('exa', true, '/untrusted/program');
  assert.deepEqual(calls, [['usage_view', { provider: 'exa', refresh: true }]]);
});

test('T05: usageView accepts the full CLI report without replacing unknown values', async () => {
  const payload = { ...emptyUsage(), providers: [provider()] };
  const api = managementApi(async () => payload);
  assert.equal(await api.usageView(), payload);
  assert.equal(payload.providers[0].current[0].remaining, null);
  assert.equal(payload.providers[0].calls.today.search, 0);
});

test('T05: usageView accepts a recognizable CLI update state', async () => {
  const payload = { ...emptyUsage(), status: 'cli_update_required', message: '当前 CLI 不支持用量查询，请更新 CLI 后重试。' };
  const api = managementApi(async () => payload);
  assert.equal(await api.usageView(), payload);
});

test('T05: unreadable usage counts stay empty while usage_error is preserved', async () => {
  const row = { ...provider(), calls: { today: {}, last_7_days: {}, daily: [] } };
  const payload = { ...emptyUsage(), providers: [row], usage_error: 'unreadable' };
  const api = managementApi(async () => payload);
  assert.equal(await api.usageView(), payload);
  assert.deepEqual(row.calls.today, {});
});

test('T05: pace accepts null and both boolean reset outcomes', () => {
  for (const lasts_until_reset of [null, true, false]) {
    assert.equal(check('UsagePace', { ...provider().pace[0], lasts_until_reset, reason: null }), null);
  }
});

test('T05: pace rejects a string reset outcome', () => {
  assert.match(check('UsagePace', { ...provider().pace[0], lasts_until_reset: 'yes' }), /lasts_until_reset/);
});

test('T05: usageView rejects a malformed nested total with a Chinese payload error', async () => {
  const row = provider();
  row.totals[0].remaining = 'unknown';
  const api = managementApi(async () => ({ ...emptyUsage(), providers: [row] }));
  await assert.rejects(api.usageView(), error => error.code === 'INVALID_PAYLOAD' && /数据格式/.test(error.message));
});

test('T05: optional call counts reject strings when present', () => {
  assert.match(check('UsageCallCounts', { search: '0' }), /search/);
});

test('T05: usage worker failures are localized at the API boundary', async () => {
  const api = managementApi(async () => { throw JSON.stringify({ code: 'usage_view_failed', message: 'worker failed' }); });
  await assert.rejects(api.usageView(), error => error.code === 'usage_view_failed' && error.message === '用量读取失败，请重试。');
});
