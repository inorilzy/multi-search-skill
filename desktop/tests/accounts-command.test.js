import test from 'node:test';
import assert from 'node:assert/strict';
import { managementApi } from '../ui/api.js';
import { check } from '../ui/payloads.js';

const account = () => ({
  id: 'acc_A1', name: '公司', source: 'oauth', login_identity: 'owner@example.com',
  keys: ['sha256:1234abcd'], balance_credentials: { exa_admin: 'sha256:abcd1234' },
});
const view = () => ({ status: 'ready', message: '', accounts: { exa: [account()] } });
const mutation = () => ({ status: 'ready', message: '', provider: 'exa', account: account(), removed: false });

function recorder(payload) {
  const calls = [];
  return { calls, api: managementApi(async (command, args) => { calls.push([command, args]); return payload; }) };
}

test('T04: accountsView defaults to all providers and validates grouped account metadata', async () => {
  const payload = view();
  const { api, calls } = recorder(payload);
  assert.equal(await api.accountsView(), payload);
  assert.deepEqual(calls, [['accounts_view', { provider: null }]]);
});

test('T04: accountsView forwards only the provider filter', async () => {
  const { api, calls } = recorder(view());
  await api.accountsView('exa', '/untrusted/program');
  assert.deepEqual(calls, [['accounts_view', { provider: 'exa' }]]);
});

test('T04: accountsAdd returns the created account and forwards only provider and name', async () => {
  const payload = mutation();
  const { api, calls } = recorder(payload);
  assert.equal(await api.accountsAdd('exa', '公司', '/untrusted/program'), payload);
  assert.deepEqual(calls, [['accounts_add', { provider: 'exa', name: '公司' }]]);
});

test('T04: accountsRename sends the account id and new name', async () => {
  const { api, calls } = recorder(mutation());
  await api.accountsRename('exa', 'acc_A1', '个人');
  assert.deepEqual(calls, [['accounts_rename', { provider: 'exa', accountId: 'acc_A1', name: '个人' }]]);
});

test('T04: accountsRemove keeps keys by default', async () => {
  const { api, calls } = recorder({ ...mutation(), removed: true });
  await api.accountsRemove('exa', 'acc_A1');
  assert.deepEqual(calls, [['accounts_remove', { provider: 'exa', accountId: 'acc_A1', deleteKeys: false }]]);
});

test('T04: accountsRemove forwards an explicit request to delete keys', async () => {
  const payload = { ...mutation(), removed: true };
  const { api, calls } = recorder(payload);
  assert.equal(await api.accountsRemove('exa', 'acc_A1', true), payload);
  assert.deepEqual(calls, [['accounts_remove', { provider: 'exa', accountId: 'acc_A1', deleteKeys: true }]]);
});

test('T04: accountsMoveKey sends a fingerprint and destination account', async () => {
  const { api, calls } = recorder(mutation());
  await api.accountsMoveKey('exa', 'sha256:1234abcd', 'default');
  assert.deepEqual(calls, [['accounts_move_key', { provider: 'exa', fingerprint: 'sha256:1234abcd', accountId: 'default' }]]);
});

test('T04: account login identity may be absent', () => {
  const { login_identity, ...manual } = account();
  assert.equal(check('ProviderAccount', manual), null);
});

test('T04: account reads reject malformed provider maps', async () => {
  const { api } = recorder({ ...view(), accounts: { exa: account() } });
  await assert.rejects(api.accountsView(), error => error.code === 'INVALID_PAYLOAD' && /数据格式/.test(error.message));
});

test('T04: account reads validate balance-only credential fingerprints', async () => {
  const payload = view();
  payload.accounts.exa[0].balance_credentials.exa_admin = 42;
  const { api } = recorder(payload);
  await assert.rejects(api.accountsView(), error => error.code === 'INVALID_PAYLOAD');
});

for (const [label, invoke] of [
  ['add', api => api.accountsAdd('exa', '公司')],
  ['rename', api => api.accountsRename('exa', 'acc_A1', '个人')],
  ['remove', api => api.accountsRemove('exa', 'acc_A1')],
  ['move-key', api => api.accountsMoveKey('exa', 'sha256:1234abcd', 'default')],
]) {
  test(`T04: ${label} rejects malformed mutation account metadata`, async () => {
    const payload = mutation();
    payload.account.keys = [false];
    const { api } = recorder(payload);
    await assert.rejects(invoke(api), error => error.code === 'INVALID_PAYLOAD');
  });
}

test('T04: old CLI account read state remains recognizable', async () => {
  const payload = { status: 'cli_update_required', message: '当前 CLI 不支持账号管理，请更新 CLI 后重试。', accounts: {} };
  assert.equal(await recorder(payload).api.accountsView(), payload);
});

test('T04: old CLI mutation state accepts a null account', async () => {
  const payload = { ...mutation(), status: 'cli_update_required', message: '请更新 CLI', account: null };
  assert.equal(await recorder(payload).api.accountsAdd('exa', '公司'), payload);
});

for (const [code, invoke, message] of [
  ['accounts_view_failed', api => api.accountsView(), '账号读取失败，请重试。'],
  ['accounts_add_failed', api => api.accountsAdd('exa', '公司'), '账号新建失败，请重试。'],
  ['accounts_rename_failed', api => api.accountsRename('exa', 'acc_A1', '个人'), '账号重命名失败，请重试。'],
  ['accounts_remove_failed', api => api.accountsRemove('exa', 'acc_A1'), '账号删除失败，请重试。'],
  ['accounts_move_key_failed', api => api.accountsMoveKey('exa', 'sha256:1234abcd', 'default'), 'Key 移动失败，请重试。'],
]) {
  test(`T04: ${code} has Chinese display text`, async () => {
    const api = managementApi(async () => { throw { code, message: 'worker failed' }; });
    await assert.rejects(invoke(api), error => error.code === code && error.message === message);
  });
}

const total = () => ({ remaining: 10, limit: null, percent: 50, unit: 'usd', relative: true });
const usage = () => ({
  status: 'ready', message: '', schema_version: 1, retention_days: 30,
  providers: [{
    id: 'exa', label: 'Exa', balance_supported: true, balance_note: '', current: [], totals: [], history: [], pace: [],
    calls: { today: {}, last_7_days: {}, daily: [] },
    accounts: [{ id: 'acc_A1', name: '公司', source: 'manual', keys: [{ key_fingerprint: 'sha256:1234abcd', report: null }], total: total() }],
    total: total(), alert: 'wont_last',
  }],
});

test('T04: usageView preserves grouped accounts, unknown reports, relative totals and alerts', async () => {
  const payload = usage();
  assert.equal(await recorder(payload).api.usageView(), payload);
});

test('T04: usageView validates nested account totals', async () => {
  const payload = usage();
  payload.providers[0].accounts[0].total.relative = 'yes';
  await assert.rejects(recorder(payload).api.usageView(), error => error.code === 'INVALID_PAYLOAD');
});

test('T04: usageView validates non-null account key reports', async () => {
  const payload = usage();
  payload.providers[0].accounts[0].keys[0].report = { remaining: 0 };
  await assert.rejects(recorder(payload).api.usageView(), error => error.code === 'INVALID_PAYLOAD');
});

test('T04: usageView accepts unknown totals and a null alert', async () => {
  const payload = usage();
  payload.providers[0].total = { remaining: null, limit: null, percent: null, unit: null, relative: false };
  payload.providers[0].alert = null;
  assert.equal(await recorder(payload).api.usageView(), payload);
});

test('T04: usageView rejects a non-string alert', async () => {
  const payload = usage();
  payload.providers[0].alert = false;
  await assert.rejects(recorder(payload).api.usageView(), error => error.code === 'INVALID_PAYLOAD');
});
