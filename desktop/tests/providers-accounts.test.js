import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { Window } from 'happy-dom';
import { mountSources } from '../ui/sources.js';
import { mountOAuthLogin } from '../ui/oauth-login.js';
import { mountProviderAccounts } from '../ui/credentials.js';

const fingerprint = key => `sha256:${createHash('sha256').update(key).digest('hex').slice(0, 8)}`;
const account = (id, name, keys = [], extra = {}) => ({ id, name, keys: keys.map(fingerprint), source: 'manual', balance_credentials: {}, ...extra });
const total = { remaining: 3, limit: 100, percent: 3, unit: 'credits', relative: false };
const flush = async () => { for (let i = 0; i < 5; i += 1) await new Promise(resolve => setTimeout(resolve, 0)); };

async function setup({ source = 'tavily', groups, keys = [], overrides = {} } = {}) {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  const calls = [];
  let revision = 1;
  groups ||= [account('default', '默认账号', keys)];
  const overview = () => ({ effective_source: keys.length ? 'file' : 'none', file_key_count: keys.length, store: { state: keys.length ? 'present' : 'absent', error: '' }, key_application_available: false });
  const mutation = () => ({ status: 'ready', message: '' });
  const api = {
    settingsView: async () => ({ route: 'default', timeout: 60, disabled_sources: [], twitter_cookies_path: null }),
    credentialStatus: async () => overview(),
    credentialRead: async () => { calls.push(['read']); return { value: keys.map(() => 'masked').join('\n'), snapshot: `s${revision}` }; },
    credentialReveal: async () => { calls.push(['reveal']); return { value: keys.join('\n'), snapshot: `s${revision}` }; },
    usageView: async (...args) => { calls.push(['usage', ...args]); return { status: 'ready', providers: [{ id: source, accounts: groups, total, alert: 'critical' }] }; },
    accountsView: async provider => { calls.push(['accounts', provider]); return { status: 'ready', accounts: { [source]: structuredClone(groups) } }; },
    accountsAdd: async (provider, name) => { calls.push(['add', provider, name]); groups.push(account('acc_New', name)); return mutation(); },
    accountsRename: async (provider, id, name) => { calls.push(['rename', provider, id, name]); groups.find(item => item.id === id).name = name; return mutation(); },
    accountsRemove: async (provider, id, deleteKeys) => {
      calls.push(['remove-account', provider, id, deleteKeys]);
      const removed = groups.find(item => item.id === id);
      groups = groups.filter(item => item.id !== id);
      if (deleteKeys) keys = keys.filter(key => !removed.keys.includes(fingerprint(key)));
      else groups.find(item => item.id === 'default').keys.push(...removed.keys);
      revision += 1;
      return mutation();
    },
    accountsMoveKey: async (provider, fp, id) => {
      calls.push(['move', provider, fp, id]);
      for (const group of groups) group.keys = group.keys.filter(item => item !== fp);
      groups.find(item => item.id === id).keys.push(fp);
      return mutation();
    },
    credentialAppend: async (provider, values) => {
      calls.push(['append', provider, values]); keys.push(...values); revision += 1;
      groups.find(item => item.id === 'default').keys.push(...values.map(fingerprint));
      return overview();
    },
    credentialRemove: async (provider, index, snapshot) => {
      calls.push(['remove-key', provider, index, snapshot]);
      const [removed] = keys.splice(index, 1); revision += 1;
      for (const group of groups) group.keys = group.keys.filter(fp => fp !== fingerprint(removed));
      return overview();
    },
    credentialTest: async (...args) => { calls.push(['test', ...args]); return { result: 'success', message: 'synthetic connection' }; },
    ...overrides,
  };
  const mounted = await mountSources(root, api);
  const row = root.querySelector(`[data-source-row="${source}"]`);
  const open = async () => { row.querySelector('[data-expand]').click(); await flush(); };
  return { window, root, row, calls, api, open, close() { mounted.dispose(); window.close(); } };
}

const groupFor = (ctx, id) => ctx.row.querySelector(`[data-account-id="${id}"]`);

test('opening a provider reuses the page account view for every account editor', async () => {
  const ctx = await setup({ groups: [account('default', '默认账号', ['tvly-one']), account('acc_A', 'A', ['tvly-two']),
    account('acc_B', 'B', ['tvly-three'])], keys: ['tvly-one', 'tvly-two', 'tvly-three'] });
  const before = ctx.calls.filter(([kind]) => kind === 'accounts').length;
  await ctx.open();
  assert.ok(groupFor(ctx, 'acc_B'), 'every account group rendered');
  // The dialog renders from the account groups the page already read: no extra list read on open.
  assert.equal(ctx.calls.filter(([kind]) => kind === 'accounts').length - before, 0);
  assert.equal(ctx.calls.filter(([kind]) => kind === 'read').length, 3);
  ctx.close();
});
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

test('T07 accounts: collapsed provider row uses T05 thin meter and alert, reads cache without secrets or refresh', async () => {
  const ctx = await setup({ keys: ['synthetic-default'] });
  assert.equal(ctx.root.querySelector('h1').textContent, '服务商');
  assert.match(ctx.root.querySelector('.eyebrow').textContent, /PROVIDERS/);
  assert.ok(ctx.root.querySelector('.provider-list > .provider-row > .provider-summary'));
  assert.equal(ctx.row.querySelector('.provider-counts').textContent, '1 个 Key');
  assert.equal(ctx.row.querySelector('.meter--thin').dataset.level, 'critical');
  assert.equal(ctx.row.querySelector('[role="progressbar"]').getAttribute('aria-valuenow'), '3');
  assert.equal(ctx.row.querySelector('.meter-alert').textContent, '余额即将用尽');
  assert.equal(ctx.row.querySelector('.provider-summary').textContent.match(/余额即将用尽/g).length, 1, 'the collapsed row has one prioritized reminder');
  assert.equal(ctx.row.querySelector('[data-provider-details]').hidden, true);
  assert.equal(ctx.row.querySelector('[data-row-test]').closest('[hidden]'), ctx.row.querySelector('[data-provider-details]'));
  assert.deepEqual(ctx.calls.filter(call => call[0] === 'usage'), [['usage']]);
  assert.equal(ctx.calls.some(call => call[0] === 'read' || call[0] === 'reveal'), false);
  ctx.close();
});

test('T07 accounts: account metadata renders as text and balance credentials are a compact connection status', async () => {
  const malicious = '<img src=x onerror=alert(1)>';
  const ctx = await setup({ source: 'parallel', groups: [account('default', '默认账号'), account('acc_P', malicious, [], { source: 'oauth', login_identity: malicious, balance_credentials: { parallel_account: malicious } })] });
  await ctx.open();
  assert.equal(groupFor(ctx, 'default').querySelector('.account-name').textContent, '独立 Key');
  const group = groupFor(ctx, 'acc_P');
  assert.equal(group.querySelector('.account-name').textContent, malicious);
  assert.equal(group.querySelector('.account-balance-status').textContent, '额度已连接');
  assert.equal(group.querySelector('.key-fingerprint'), null);
  assert.equal(group.querySelector('.account-email'), null);
  assert.match(group.querySelector('.account-summary').textContent, /0 个 Key/);
  assert.ok(group.querySelector('[data-action="add"]'));
  assert.equal(group.querySelector('[data-saved-empty]').hidden, true, 'the healthy empty group needs no empty-state box');
  assert.equal(group.querySelector('img'), null);
  assert.equal(ctx.row.querySelector('.provider-counts').textContent, '1 个账号 · 0 个 Key');
  assert.equal(group.querySelector('[data-action="test"]').disabled, true);
  group.querySelector('[data-action="test"]').dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true })); await flush();
  assert.equal(ctx.calls.some(call => call[0] === 'test'), false, 'an empty account never tests another account’s key');
  assert.equal(group.querySelector('[data-info="error"]').textContent, '', 'a connected balance-only account is a valid idle state');
  ctx.close();
});

test('T07 accounts: rename sends provider, account id and literal name; default has neither destructive control', async () => {
  const ctx = await setup({ keys: ['synthetic-default'], groups: [account('default', '默认账号', ['synthetic-default']), account('acc_New', '登录账号', [], { source: 'oauth' })] });
  await ctx.open();
  assert.equal(ctx.row.querySelectorAll('[data-account-action="add"]').length, 1);
  assert.equal(ctx.row.querySelector('.account-form'), null, 'creation needs an explicit click');
  assert.equal(groupFor(ctx, 'default').querySelector('[data-account-action="rename"]'), null);
  assert.equal(groupFor(ctx, 'default').querySelector('[data-account-action="remove"]'), null);
  let group = groupFor(ctx, 'acc_New');
  assert.equal(group.querySelector('[data-account-action="rename"]').textContent, '重命名');
  assert.equal(group.querySelector('[data-account-action="remove"]').textContent, '删除');
  assert.equal(group.querySelector('[data-account-action="rename"]').getAttribute('aria-label'), '重命名账号 登录账号');
  assert.equal(group.querySelector('[data-account-action="remove"]').getAttribute('aria-label'), '删除账号 登录账号');
  group.querySelector('[data-account-action="rename"]').click();
  let form = group.querySelector('.account-form');
  assert.equal(ctx.window.document.activeElement, form.querySelector('input'));
  form.querySelector('input').value = '公司 <b>账号</b>';
  form.dispatchEvent(new ctx.window.Event('submit', { cancelable: true })); await flush();
  assert.deepEqual(ctx.calls.find(call => call[0] === 'rename'), ['rename', 'tavily', 'acc_New', '公司 <b>账号</b>']);
  group = groupFor(ctx, 'acc_New');
  assert.equal(group.querySelector('b'), null);
  assert.equal(group.querySelector('.account-name').textContent, '公司 <b>账号</b>');
  group.querySelector('[data-account-action="rename"]').click();
  form = group.querySelector('.account-form'); form.querySelector('input').value = '个人';
  form.dispatchEvent(new ctx.window.Event('submit', { cancelable: true })); await flush();
  assert.deepEqual(ctx.calls.filter(call => call[0] === 'rename').at(-1), ['rename', 'tavily', 'acc_New', '个人']);
  assert.equal(groupFor(ctx, 'acc_New').querySelector('.account-name').textContent, '个人');
  ctx.close();
});

for (const deleteKeys of [false, true]) test(`T07 accounts: deleting an account explicitly chooses deleteKeys=${deleteKeys}`, async () => {
  const ctx = await setup({ keys: ['synthetic-first', 'synthetic-company'], groups: [account('default', '默认账号', ['synthetic-first']), account('acc_C', '公司', ['synthetic-company'])] });
  await ctx.open();
  const group = groupFor(ctx, 'acc_C');
  const trigger = group.querySelector('[data-account-action="remove"]');
  trigger.click();
  const cancel = group.querySelector('[data-action="cancel-account-remove"]');
  assert.equal(ctx.window.document.activeElement, cancel);
  cancel.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(group.querySelector('[data-account-confirm]'), null);
  assert.equal(ctx.window.document.activeElement, trigger);
  assert.equal(ctx.calls.some(call => call[0] === 'remove-account'), false);
  trigger.click();
  group.querySelector(`[data-account-action="${deleteKeys ? 'delete-keys' : 'keep-keys'}"]`).click(); await flush();
  assert.deepEqual(ctx.calls.find(call => call[0] === 'remove-account'), ['remove-account', 'tavily', 'acc_C', deleteKeys]);
  assert.equal(groupFor(ctx, 'acc_C'), null);
  assert.equal(ctx.row.querySelector('.provider-counts').textContent, `${deleteKeys ? 1 : 2} 个 Key`);
  ctx.close();
});

test('T07 accounts: account-local test and remove resolve the current global index and snapshot', async () => {
  const ctx = await setup({ keys: ['synthetic-first', 'synthetic-company'], groups: [account('default', '默认账号', ['synthetic-first']), account('acc_C', '公司', ['synthetic-company'])] });
  await ctx.open();
  const group = groupFor(ctx, 'acc_C');
  assert.equal(group.querySelector('.key-label').textContent, 'Key 1');
  assert.doesNotMatch(group.textContent, /sha256:/);
  assert.equal(group.querySelector('[data-saved-input]').value, '••••••••');
  assert.equal(group.querySelector('[data-saved-input]').type, 'password');
  assert.equal(ctx.calls.some(call => call[0] === 'reveal'), false);
  group.querySelector('[data-action="test"]').click(); await flush();
  assert.deepEqual(ctx.calls.find(call => call[0] === 'test'), ['test', 'tavily', { index: 1, expected: 's1' }]);
  assert.match(group.querySelector('[data-status="test"]').textContent, /测试成功/);
  group.querySelector('[data-action="remove"]').click();
  group.querySelector('[data-action="confirm-remove"]').click(); await flush();
  assert.deepEqual(ctx.calls.find(call => call[0] === 'remove-key'), ['remove-key', 'tavily', 1, 's1']);
  assert.equal(groupFor(ctx, 'acc_C').querySelectorAll('[data-saved-index]').length, 0);
  assert.equal(groupFor(ctx, 'default').querySelectorAll('[data-saved-index]').length, 1);
  ctx.close();
});

test('T07 accounts: append assigns the new fingerprint to the selected account and updates row counts', async () => {
  const ctx = await setup({ keys: ['synthetic-first'], groups: [account('default', '默认账号', ['synthetic-first']), account('acc_C', '公司')] });
  await ctx.open();
  const group = groupFor(ctx, 'acc_C');
  group.querySelector('[data-action="add"]').click();
  group.querySelector('[data-draft-input]').value = 'synthetic-new';
  group.querySelector('[data-save-form]').dispatchEvent(new ctx.window.Event('submit', { cancelable: true })); await flush();
  assert.deepEqual(ctx.calls.find(call => call[0] === 'append'), ['append', 'tavily', ['synthetic-new']]);
  assert.deepEqual(ctx.calls.find(call => call[0] === 'move'), ['move', 'tavily', fingerprint('synthetic-new'), 'acc_C']);
  assert.equal(groupFor(ctx, 'acc_C').querySelector('.key-label').textContent, 'Key 1');
  assert.equal(groupFor(ctx, 'acc_C').querySelector('[data-key-fingerprint]').dataset.keyFingerprint, fingerprint('synthetic-new'));
  assert.doesNotMatch(ctx.row.textContent, /sha256:/);
  assert.match(groupFor(ctx, 'acc_C').querySelector('.account-summary').textContent, /1 个 Key/);
  assert.equal(ctx.row.querySelector('.provider-counts').textContent, '1 个账号 · 2 个 Key');
  assert.equal(ctx.calls.filter(call => call[0] === 'usage').every(call => call.length === 1), true);
  ctx.close();
});

test('T07 accounts: stale key snapshots reject tests before backend execution', async () => {
  const ctx = await setup({ keys: ['synthetic-first'], overrides: { credentialReveal: async () => ({ value: 'synthetic-changed', snapshot: 'changed' }) } });
  await ctx.open();
  const group = groupFor(ctx, 'default');
  group.querySelector('[data-action="test"]').click(); await flush();
  assert.equal(ctx.calls.some(call => call[0] === 'test'), false);
  assert.match(group.querySelector('[data-info="error"]').textContent, /凭据已变化/);
  ctx.close();
});

test('T07 accounts: browser login rebuilds account groups, keeps row expanded and reads only cached usage', async () => {
  const groups = [account('default', '默认账号')];
  const started = [];
  const ctx = await setup({ source: 'parallel', groups, overrides: {
    oauthLoginStart: async provider => { started.push(provider); return 7; },
    oauthLoginPoll: async () => { groups.push(account('acc_Login', '<b>登录身份</b>', [], { source: 'oauth', balance_credentials: { parallel_account: 'sha256:12345678' } })); return { id: 7, phase: 'complete', needs_search_key: true }; },
    oauthLoginCancel: async () => assert.fail('completed login must not be cancelled'),
  } });
  await ctx.open();
  ctx.row.querySelector('[data-action="oauth-start"]').click(); await flush();
  assert.deepEqual(started, ['parallel']);
  assert.equal(ctx.row.dataset.expanded, 'true');
  assert.match(groupFor(ctx, 'acc_Login').querySelector('.account-summary').textContent, /0 个 Key/);
  assert.ok(groupFor(ctx, 'acc_Login').querySelector('[data-action="add"]'));
  assert.equal(groupFor(ctx, 'acc_Login').querySelector('b'), null);
  assert.match(ctx.row.querySelector('[data-oauth-status]').textContent, /请为这个账号添加搜索 Key/);
  assert.ok(ctx.calls.filter(call => call[0] === 'usage').every(call => call.length === 1));
  ctx.close();
});

test('T07 accounts: OAuth needs_search_key hint also works outside the providers page', async () => {
  const window = new Window();
  const root = window.document.createElement('div');
  window.document.body.append(root);
  let completed;
  const mounted = await mountOAuthLogin(root, {
    oauthLoginStart: async () => 1,
    oauthLoginPoll: async () => ({ id: 1, phase: 'complete', needs_search_key: true }),
    oauthLoginCancel: async () => {},
  }, { source: 'parallel', onComplete: status => { completed = status; } });
  root.querySelector('[data-action="oauth-start"]').click(); await flush();
  assert.match(root.querySelector('[data-oauth-status]').textContent, /请为这个账号添加搜索 Key/);
  assert.equal(completed.needs_search_key, true);
  mounted.dispose(); window.close();
});


test('T07 accounts: GitHub has one provider row and its switch updates both search channels', async () => {
  const window = new Window(), root = window.document.createElement('main');
  window.document.body.append(root);
  let saved;
  const mounted = await mountSources(root, {
    settingsView: async () => ({ route: 'default', timeout: 60, disabled_sources: ['github_code', 'exa'], twitter_cookies_path: null }),
    settingsSave: async input => { saved = input; return input; },
    credentialStatus: async () => ({ effective_source: 'none', store: { state: 'absent' } }),
    accountsView: async () => ({ status: 'ready', accounts: { github: [account('default', '默认账号', ['synthetic-github'])] } }),
    usageView: async () => ({ providers: [] }),
  });
  const row = root.querySelector('[data-source-row="github_repos"]');
  assert.equal(root.querySelector('[data-source-row="github_code"]'), null);
  assert.equal(row.querySelector('.provider-name').textContent, 'GitHub');
  assert.equal(row.querySelector('.provider-counts').textContent, '1 个 Key');
  const toggle = row.querySelector('[data-toggle]');
  assert.equal(toggle.checked, false);
  toggle.checked = true; toggle.dispatchEvent(new window.Event('change')); await flush();
  assert.deepEqual(saved.disabled_sources, ['exa']);
  assert.equal(saved.timeout, null);
  toggle.checked = false; toggle.dispatchEvent(new window.Event('change')); await flush();
  assert.deepEqual(saved.disabled_sources, ['github_code', 'exa', 'github_repos']);
  mounted.dispose(); window.close();
});

test('T07 accounts: failed assignment reports saved keys, clears drafts and never repeats the append', async () => {
  const ctx = await setup({ keys: ['synthetic-first'], groups: [account('default', '默认账号', ['synthetic-first']), account('acc_C', '公司')], overrides: {
    accountsMoveKey: async () => { throw { code: 'accounts_move_key_failed', message: 'synthetic failure' }; },
  } });
  await ctx.open();
  const group = groupFor(ctx, 'acc_C');
  group.querySelector('[data-action="add"]').click();
  group.querySelector('[data-draft-input]').value = 'synthetic-new';
  group.querySelector('[data-save-form]').dispatchEvent(new ctx.window.Event('submit', { cancelable: true })); await flush();
  assert.match(ctx.row.querySelector('[data-account-error]').textContent, /Key 已保存.*归属更新失败/);
  assert.equal(groupFor(ctx, 'acc_C').querySelector('[data-draft-input]'), null);
  assert.equal(groupFor(ctx, 'default').querySelectorAll('[data-saved-index]').length, 2);
  assert.equal(ctx.calls.filter(call => call[0] === 'append').length, 1);
  ctx.close();
});

test('T07 accounts: an account write error keeps the name draft and permits a single retry', async () => {
  let tries = 0;
  const ctx = await setup({ groups: [account('default', '默认账号'), account('acc_C', '公司')],
    overrides: { accountsRename: async () => { tries += 1; throw new Error('账号新建失败'); } } });
  await ctx.open();
  groupFor(ctx, 'acc_C').querySelector('[data-account-action="rename"]').click();
  const form = groupFor(ctx, 'acc_C').querySelector('.account-form');
  form.querySelector('input').value = '保留草稿';
  form.dispatchEvent(new ctx.window.Event('submit', { cancelable: true })); await flush();
  assert.equal(form.querySelector('input').value, '保留草稿');
  assert.match(ctx.row.querySelector('[data-account-error]').textContent, /账号新建失败/);
  assert.equal(form.querySelector('button').disabled, false);
  assert.equal(tries, 1);
  ctx.close();
});

test('T07 accounts: Exa balance editor is inside its owning account and preserves exa_admin operations', async () => {
  const appended = [], removed = [];
  let adminKeys = ['synthetic-admin'];
  const ctx = await setup({ source: 'exa', keys: ['synthetic-search'], groups: [account('default', '默认账号', ['synthetic-search']), account('acc_C', '公司', [], { balance_credentials: { exa_admin: fingerprint('synthetic-admin') } })], overrides: {
    credentialRead: async source => ({ value: source === 'exa_admin' ? adminKeys.map(() => 'masked').join('\n') : 'masked', snapshot: 'admin-s' }),
    credentialAppend: async (source, values) => { appended.push([source, values]); adminKeys.push(...values); return { effective_source: 'file', store: { state: 'present', error: '' } }; },
    credentialRemove: async (...args) => { removed.push(args); adminKeys.splice(args[1], 1); return { effective_source: 'file', store: { state: 'present', error: '' } }; },
  } });
  await ctx.open();
  assert.equal(groupFor(ctx, 'default').querySelector('.exa-admin-key'), null);
  const group = groupFor(ctx, 'acc_C'), admin = group.querySelector('.exa-admin-key');
  assert.equal(group.querySelector('.account-balance-status').textContent, '额度已连接');
  assert.equal(admin.querySelector('summary').textContent, '管理额度凭据');
  assert.equal(admin.open, false);
  assert.doesNotMatch(group.textContent, /sha256:/);
  assert.equal(admin.querySelector('[data-action="test"]').hidden, true);
  admin.querySelector('[data-action="add"]').click();
  admin.querySelector('[data-draft-input]').value = 'synthetic-new-admin';
  admin.querySelector('[data-save-form]').dispatchEvent(new ctx.window.Event('submit', { cancelable: true })); await flush();
  assert.deepEqual(appended, [['exa_admin', ['synthetic-new-admin']]]);
  admin.querySelector('[data-action="remove"]').click();
  admin.querySelector('[data-action="confirm-remove"]').click(); await flush();
  assert.deepEqual(removed, [['exa_admin', 0, 'admin-s']]);
  ctx.close();
});

test('T07 accounts: Exa can explicitly open management-key editing in standalone keys', async () => {
  const ctx = await setup({ source: 'exa', groups: [account('default', '默认账号'), account('acc_C', '公司')] });
  await ctx.open();
  assert.equal(groupFor(ctx, 'default').querySelector('.account-name').textContent, '独立 Key');
  assert.equal(groupFor(ctx, 'default').querySelector('.exa-admin-key').open, false);
  const add = ctx.row.querySelector('[data-account-action="add-admin"]');
  assert.equal(add.hidden, false);
  add.click(); await flush();
  assert.equal(groupFor(ctx, 'default').querySelector('.exa-admin-key').open, true);
  assert.equal(groupFor(ctx, 'acc_C').querySelector('.exa-admin-key'), null);
  ctx.close();
});


for (const [search, scrape, count] of [[0, 0, 0], [2, 3, 5], [undefined, 0, '未知']]) test(`T07 accounts: unsupported balance uses one concise state even with local calls (${count})`, async () => {
  const ctx = await setup({ overrides: { usageView: async () => ({ providers: [{ id: 'tavily', balance_supported: false, calls: { today: { search, scrape, failures: 9 } } }] }) } });
  assert.equal(ctx.row.querySelector('.provider-meter').textContent, '未提供额度');
  assert.equal(ctx.row.querySelector('[role="progressbar"]'), null);
  ctx.close();
});

test('T07 accounts: relative totals and wont_last reminders come directly from cached usage', async () => {
  const ctx = await setup({ overrides: { usageView: async () => ({ providers: [{ id: 'tavily', total: { remaining: 12, limit: null, percent: 60, unit: 'usd', relative: true }, alert: 'wont_last' }] }) } });
  assert.equal(ctx.row.querySelector('.meter-relative').textContent, '相对');
  assert.equal(ctx.row.querySelector('[role="progressbar"]').getAttribute('aria-valuenow'), '60');
  assert.match(ctx.row.querySelector('.meter-value').textContent, /12 美元/);
  assert.equal(ctx.row.querySelector('.meter-alert').textContent, '撑不到重置');
  ctx.close();
});

test('T07 accounts: an outdated CLI keeps its update message visible instead of inventing accounts', async () => {
  const ctx = await setup({ overrides: { accountsView: async () => ({ status: 'cli_update_required', message: '请更新 CLI <b>后重试</b>', accounts: {} }) } });
  assert.equal(ctx.root.querySelector('[data-cache-error]').textContent, '请更新 CLI <b>后重试</b>');
  await ctx.open();
  assert.equal(ctx.row.querySelectorAll('[data-account-id]').length, 0);
  assert.equal(ctx.row.querySelector('[data-account-error]').textContent, '请更新 CLI <b>后重试</b>');
  assert.equal(ctx.row.querySelector('b'), null);
  ctx.close();
});

test('account list labels never expose fingerprints, internal login identities or balance references', async () => {
  const ctx = await setup({ source: 'parallel', keys: ['synthetic-personal', 'synthetic-work'], groups: [
    account('default', '默认账号', ['synthetic-personal']),
    account('acc_Work', '工作账号', ['synthetic-work'], { login_identity: 'person@example.test', balance_credentials: { parallel_account: 'opaque-balance-reference' } }),
    account('acc_Old', 'oauth-login:opaque-login', [], { source: 'oauth', login_identity: 'sha256:11223344' }),
    account('acc_Brave', '另一账号', [], { login_identity: 'brave-user:12345' }),
    account('acc_Hash', '历史账号', [], { login_identity: 'cafebabecafebabecafebabecafebabe' }),
  ] });
  await ctx.open();
  const manager = ctx.row.querySelector('.provider-account-manager');
  assert.ok(manager.querySelector('.account-list > .named-account .account-keys .key-row'));
  assert.equal(groupFor(ctx, 'acc_Work').querySelector('.account-email').textContent, 'person@example.test');
  assert.equal(groupFor(ctx, 'acc_Old').querySelector('.account-name').textContent, '账号 2');
  assert.equal(groupFor(ctx, 'default').classList.contains('standalone-keys'), true);
  assert.equal(groupFor(ctx, 'default').querySelector('.account-name').textContent, '独立 Key');
  assert.doesNotMatch(manager.textContent, /sha256:|oauth-login:|brave-user:|cafebabe|opaque-balance-reference/);
  assert.equal(manager.querySelector('.credential-intro, .cred-status, .config-details'), null);
  assert.equal(manager.querySelectorAll('[data-provider-login] h3').length, 0);
  assert.ok([...manager.querySelectorAll('[data-saved-input]')].every(input => input.type === 'password' && input.value === '••••••••'));
  assert.equal(ctx.calls.some(call => call[0] === 'reveal' || call[0] === 'move'), false);
  ctx.close();
});

test('standalone keys stay available beside empty named accounts and can save without assigning an account', async () => {
  const ctx = await setup({ groups: [account('default', '默认账号'), account('acc_Work', '工作账号')] });
  await ctx.open();
  const standalone = groupFor(ctx, 'default');
  assert.equal(standalone.querySelector('[data-saved-empty]').hidden, true);
  standalone.querySelector('[data-action="add"]').click();
  standalone.querySelector('[data-draft-input]').value = 'synthetic-standalone';
  standalone.querySelector('[data-save-form]').dispatchEvent(new ctx.window.Event('submit', { cancelable: true })); await flush();
  assert.deepEqual(ctx.calls.find(call => call[0] === 'append'), ['append', 'tavily', ['synthetic-standalone']]);
  assert.equal(ctx.calls.some(call => call[0] === 'move'), false);
  assert.equal(groupFor(ctx, 'default').querySelectorAll('.key-row').length, 1);
  assert.equal(groupFor(ctx, 'acc_Work').querySelectorAll('.key-row').length, 0);
  assert.equal(ctx.row.querySelector('[data-action="oauth-start"], [data-dashboard-start]'), null, 'API-only providers never invent browser login');
  ctx.close();
});

test('new grouping is explicit, cancellable and submits the literal name once', async () => {
  const ctx = await setup();
  await ctx.open();
  assert.equal(ctx.row.querySelector('.account-form'), null);
  assert.equal(ctx.calls.some(call => call[0] === 'add'), false);
  const add = ctx.row.querySelector('[data-account-action="add"]');
  add.click(); add.click();
  assert.equal(ctx.row.querySelectorAll('.account-form').length, 1);
  ctx.row.querySelector('[data-action="cancel-name"]').click();
  assert.equal(ctx.row.querySelector('.account-form'), null);
  assert.equal(ctx.calls.some(call => call[0] === 'add'), false);
  add.click();
  const form = ctx.row.querySelector('.account-form');
  form.querySelector('input').value = '团队 <b>分组</b>';
  form.dispatchEvent(new ctx.window.Event('submit', { cancelable: true }));
  form.dispatchEvent(new ctx.window.Event('submit', { cancelable: true })); await flush();
  assert.deepEqual(ctx.calls.filter(call => call[0] === 'add'), [['add', 'tavily', '团队 <b>分组</b>']]);
  assert.equal(groupFor(ctx, 'acc_New').querySelector('.account-name').textContent, '团队 <b>分组</b>');
  assert.equal(groupFor(ctx, 'acc_New').querySelector('b'), null);
  ctx.close();
});

test('existing keys move only after confirmation, from standalone to an account and back', async () => {
  const ctx = await setup({ keys: ['synthetic-moving'], groups: [account('default', '默认账号', ['synthetic-moving']), account('acc_Work', '工作账号')] });
  await ctx.open();
  let key = groupFor(ctx, 'default').querySelector('.key-row');
  const trigger = key.querySelector('[data-action="edit-owner"]');
  assert.equal(key.querySelector('.key-owner-control').hidden, true);
  trigger.click();
  const cancel = key.querySelector('[data-action="cancel-owner"]');
  assert.equal(ctx.window.document.activeElement, cancel);
  const select = key.querySelector('[data-key-owner]');
  select.value = 'acc_Work'; select.dispatchEvent(new ctx.window.Event('change', { bubbles: true }));
  assert.equal(ctx.calls.some(call => call[0] === 'move'), false);
  cancel.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(key.querySelector('.key-owner-control').hidden, true);
  assert.equal(ctx.window.document.activeElement, trigger);
  assert.equal(ctx.calls.some(call => call[0] === 'move'), false);
  trigger.click(); select.value = 'acc_Work';
  key.querySelector('[data-action="move-key"]').click(); await flush();
  assert.equal(groupFor(ctx, 'default').querySelector('.key-row'), null);
  key = groupFor(ctx, 'acc_Work').querySelector('.key-row');
  assert.equal(key.dataset.keyFingerprint, fingerprint('synthetic-moving'));
  key.querySelector('[data-action="edit-owner"]').click();
  key.querySelector('[data-key-owner]').value = 'default';
  key.querySelector('[data-action="move-key"]').click(); await flush();
  assert.deepEqual(ctx.calls.filter(call => call[0] === 'move'), [
    ['move', 'tavily', fingerprint('synthetic-moving'), 'acc_Work'],
    ['move', 'tavily', fingerprint('synthetic-moving'), 'default'],
  ]);
  assert.equal(ctx.calls.some(call => call[0] === 'reveal'), false, 'moving uses read snapshots without revealing secrets');
  assert.doesNotMatch(ctx.row.textContent, /sha256:/);
  assert.ok(groupFor(ctx, 'default').querySelector('.key-row'));
  ctx.close();
});

for (const changed of ['snapshot', 'ownership', 'target']) test(`moving rejects stale ${changed} before the backend write`, async () => {
  const groups = [account('default', '默认账号', ['synthetic-moving']), account('acc_Work', '工作账号')];
  let snapshot = 's1';
  const ctx = await setup({ keys: ['synthetic-moving'], groups, overrides: { credentialRead: async () => ({ value: 'masked', snapshot }) } });
  await ctx.open();
  const key = groupFor(ctx, 'default').querySelector('.key-row');
  key.querySelector('[data-action="edit-owner"]').click();
  key.querySelector('[data-key-owner]').value = 'acc_Work';
  if (changed === 'snapshot') snapshot = 's2';
  if (changed === 'ownership') { groups[0].keys = []; groups[1].keys.push(fingerprint('synthetic-moving')); }
  if (changed === 'target') groups.splice(1, 1);
  key.querySelector('[data-action="move-key"]').click(); await flush();
  assert.equal(ctx.calls.some(call => call[0] === 'move'), false);
  const error = groupFor(ctx, 'default').querySelector('[data-info="error"]');
  assert.match(error.textContent, /已变化/);
  assert.equal(error.hidden, false);
  assert.equal(groupFor(ctx, 'default').querySelector('[data-action="refresh"]').hidden, false);
  ctx.close();
});

test('account key order preserves reveal, selection and deletion at the original global indices', async () => {
  const ctx = await setup({ keys: ['synthetic-a', 'synthetic-b', 'synthetic-c'], groups: [account('default', '默认账号', ['synthetic-b']), account('acc_Work', '工作账号', ['synthetic-c', 'synthetic-a'])] });
  await ctx.open();
  const group = groupFor(ctx, 'acc_Work');
  const inputs = () => [...group.querySelectorAll('[data-saved-input]')];
  group.querySelectorAll('[data-action="reveal"]')[0].click(); await flush();
  assert.deepEqual(inputs().map(input => input.value), ['synthetic-c', '••••••••']);
  assert.equal(inputs()[0].type, 'text');
  assert.ok(!group.innerHTML.includes('synthetic-c'), 'revealed values stay in input properties');
  group.querySelectorAll('[data-action="reveal"]')[0].click();
  assert.deepEqual(inputs().map(input => input.value), ['••••••••', '••••••••']);
  assert.equal(group.querySelectorAll('[data-action="copy"]')[0].disabled, true);
  assert.equal(group.querySelector('[data-test-key]').value, '1');
  group.querySelector('[data-action="test"]').click(); await flush();
  assert.deepEqual(ctx.calls.find(call => call[0] === 'test'), ['test', 'tavily', { index: 0, expected: 's1' }]);
  const trigger = group.querySelectorAll('[data-action="remove"]')[1];
  trigger.click();
  group.querySelector('[data-action="cancel-remove"]').click();
  assert.equal(ctx.calls.some(call => call[0] === 'remove-key'), false);
  trigger.click(); group.querySelector('[data-action="confirm-remove"]').click(); await flush();
  assert.deepEqual(ctx.calls.find(call => call[0] === 'remove-key'), ['remove-key', 'tavily', 0, 's1']);
  assert.equal(groupFor(ctx, 'acc_Work').querySelectorAll('.key-row').length, 1);
  assert.equal(groupFor(ctx, 'default').querySelectorAll('.key-row').length, 1);
  ctx.close();
});

for (const action of ['reveal', 'remove', 'test']) test(`late ${action} resolution cannot mutate or reveal after the manager closes`, async () => {
  const read = deferred(), started = deferred();
  const ctx = await setup({ keys: ['synthetic-late'], overrides: { credentialReveal: async () => { started.resolve(); return read.promise; } } });
  await ctx.open();
  const group = groupFor(ctx, 'default');
  group.querySelector(`[data-action="${action}"]`).click();
  if (action === 'remove') group.querySelector('[data-action="confirm-remove"]').click();
  await started.promise;
  ctx.row.querySelector('[data-dialog-close]').click();
  read.resolve({ value: 'synthetic-late', snapshot: 's1' }); await flush();
  assert.equal(ctx.calls.some(call => call[0] === 'remove-key' || call[0] === 'test'), false);
  assert.equal(ctx.row.querySelector('[data-saved-input]'), null);
  assert.ok(!ctx.row.innerHTML.includes('synthetic-late'));
  ctx.close();
});

test('environment key remains a read-only test option, never an owned or movable key', async () => {
  const ctx = await setup({ overrides: { credentialStatus: async () => ({ effective_source: 'env', env_var: 'TAVILY_API_KEY', store: { state: 'absent', error: '' } }) } });
  await ctx.open();
  const group = groupFor(ctx, 'default');
  assert.equal(group.querySelector('[data-environment-key]').hidden, false);
  assert.match(group.querySelector('[data-environment-key]').textContent, /只读/);
  assert.equal(group.querySelector('[data-saved-input], [data-key-owner], [data-action="remove"]'), null);
  assert.equal(group.querySelector('[data-test-key]').value, 'env');
  group.querySelector('[data-action="test"]').click(); await flush();
  assert.deepEqual(ctx.calls.find(call => call[0] === 'test'), ['test', 'tavily']);
  assert.equal(ctx.calls.some(call => call[0] === 'reveal' || call[0] === 'move'), false);
  ctx.close();
});

test('cached quota updates only quota nodes and preserves draft inputs and pending move selection', async () => {
  const keys = ['synthetic-standalone', 'synthetic-work'];
  const ctx = await setup({ keys, groups: [account('default', '默认账号', [keys[0]]), account('acc_Work', '工作账号', [keys[1]])] });
  const holder = ctx.window.document.createElement('div'); ctx.root.append(holder);
  const report = (key, extra) => ({ provider: 'tavily', status: 'ok', scope: 'key', unit: 'credits', remaining: 90, limit: 10, used: 2, key_fingerprint: fingerprint(key), ...extra });
  const cache = {
    id: 'tavily', balance_supported: true,
    accounts: [
      { id: 'default', total: { remaining: 90, limit: 100, unit: 'credits' }, keys: [{ key_fingerprint: fingerprint(keys[0]), report: report(keys[0], { limit: 100 }) }] },
      { id: 'acc_Work', total: { remaining: 90, limit: 100, unit: 'credits' }, keys: [{ key_fingerprint: fingerprint(keys[1]), report: report(keys[1], {}) }] },
    ],
    current: [report(keys[1], { scope: 'account', remaining: 90, limit: 100 })],
  };
  const mounted = await mountProviderAccounts(holder, ctx.api, { source: 'tavily', usageProvider: cache });
  const work = holder.querySelector('[data-account-id="acc_Work"]');
  const standalone = holder.querySelector('[data-account-id="default"]');
  assert.equal(work.querySelector('.account-quota').textContent, '剩余 90 / 上限 100 credits');
  assert.equal(work.querySelector('.key-quota').textContent, '已用 2 / Key 上限 10 credits');
  assert.doesNotMatch(work.querySelector('.key-quota').textContent, /剩余 90/);
  assert.equal(standalone.querySelector('.account-quota').hidden, true);
  assert.match(standalone.querySelector('.key-quota').textContent, /剩余 90/);
  work.querySelector('[data-action="add"]').click();
  const draft = work.querySelector('[data-draft-input]'); draft.value = 'synthetic-unsaved';
  work.querySelector('[data-action="edit-owner"]').click();
  const owner = work.querySelector('[data-key-owner]'); owner.value = 'default';
  const calls = ctx.calls.length;
  cache.accounts[1].total.remaining = 75;
  cache.accounts[1].keys[0].report.used = 5;
  mounted.updateUsage(cache);
  assert.match(work.querySelector('.account-quota').textContent, /剩余 75/);
  assert.match(work.querySelector('.key-quota').textContent, /已用 5/);
  assert.equal(work.querySelector('[data-draft-input]'), draft);
  assert.equal(draft.value, 'synthetic-unsaved');
  assert.equal(work.querySelector('[data-key-owner]'), owner);
  assert.equal(owner.value, 'default');
  assert.equal(work.querySelector('.key-owner-control').hidden, false);
  assert.equal(ctx.calls.length, calls, 'cache publication performs no API requests');
  mounted.dispose(); ctx.close();
});

for (const action of ['reveal', 'remove', 'test']) test(`account ${action} refuses changed ownership before reading secrets or executing a key action`, async () => {
  const groups = [account('default', '默认账号', ['synthetic-owned']), account('acc_Work', '工作账号')];
  const ctx = await setup({ keys: ['synthetic-owned'], groups });
  await ctx.open();
  groups[0].keys = []; groups[1].keys.push(fingerprint('synthetic-owned'));
  const group = groupFor(ctx, 'default');
  group.querySelector(`[data-action="${action}"]`).click();
  if (action === 'remove') group.querySelector('[data-action="confirm-remove"]').click();
  await flush();
  assert.equal(ctx.calls.some(call => ['reveal', 'remove-key', 'test'].includes(call[0])), false);
  assert.match(group.querySelector('[data-info="error"]').textContent, /归属已变化/);
  assert.equal(group.querySelector('[data-saved-input]').value, '••••••••');
  ctx.close();
});

test('manager browser login preserves cancellation and ignores a late completion', async () => {
  const poll = deferred(), polled = deferred();
  let cancelled = 0;
  const ctx = await setup({ source: 'parallel', overrides: {
    oauthLoginStart: async () => 7,
    oauthLoginPoll: async () => { polled.resolve(); return poll.promise; },
    oauthLoginCancel: async id => { assert.equal(id, 7); cancelled += 1; return { id, phase: 'cancelled' }; },
  } });
  await ctx.open();
  const login = ctx.row.querySelector('[data-provider-login]');
  const manager = ctx.row.querySelector('.provider-account-manager');
  assert.equal(login.classList.contains('account-logins'), true);
  assert.equal(login.parentElement, manager.querySelector('[data-account-tools]'));
  assert.equal(manager.querySelectorAll('.account-toolbar').length, 1);
  assert.equal(login.querySelector('h3, .oauth-login-sub'), null);
  login.querySelector('[data-action="oauth-start"]').click();
  await polled.promise;
  assert.equal(login.querySelector('[data-action="oauth-cancel"]').hidden, false);
  login.querySelector('[data-action="oauth-cancel"]').click(); await flush();
  assert.equal(cancelled, 1);
  assert.equal(login.querySelector('[data-oauth-status]').textContent, '已取消登录。');
  poll.resolve({ id: 7, phase: 'complete', needs_search_key: true }); await flush();
  assert.equal(login.querySelector('[data-oauth-status]').textContent, '已取消登录。');
  assert.equal(login.querySelector('[data-action="oauth-start"]').hidden, false);
  assert.equal(login.querySelector('[data-info="oauth-error"]').getAttribute('role'), 'alert');
  ctx.close();
});

test('account errors preserve the reason without exposing fingerprints or balance references in text or title', async () => {
  const reference = 'opaque-account-balance-reference';
  const ctx = await setup({ groups: [account('default', '默认账号'), account('acc_Work', '工作账号', [], { balance_credentials: { parallel_account: reference } })], overrides: {
    accountsRename: async () => { throw new Error(`账号更名失败：${reference} sha256:deadbeef oauth-login:old-login`); },
  } });
  await ctx.open();
  groupFor(ctx, 'acc_Work').querySelector('[data-account-action="rename"]').click();
  const form = groupFor(ctx, 'acc_Work').querySelector('.account-form');
  form.querySelector('input').value = '新名称';
  form.dispatchEvent(new ctx.window.Event('submit', { cancelable: true })); await flush();
  const error = ctx.row.querySelector('[data-account-error]');
  assert.match(error.textContent, /账号更名失败/);
  assert.doesNotMatch(`${error.textContent} ${error.getAttribute('title')}`, /opaque-account-balance-reference|sha256:|oauth-login:/);
  assert.equal(form.querySelector('input').value, '新名称');
  assert.equal(error.hidden, false);
  ctx.close();
});

for (const action of ['reveal', 'remove', 'test']) test(`account ${action} rechecks ownership after a pending secret read`, async () => {
  const groups = [account('default', '默认账号', ['synthetic-race']), account('acc_Work', '工作账号')];
  const reveal = deferred(), started = deferred();
  const ctx = await setup({ keys: ['synthetic-race'], groups, overrides: { credentialReveal: async () => { started.resolve(); return reveal.promise; } } });
  await ctx.open();
  const group = groupFor(ctx, 'default');
  group.querySelector(`[data-action="${action}"]`).click();
  if (action === 'remove') group.querySelector('[data-action="confirm-remove"]').click();
  await started.promise;
  groups[0].keys = []; groups[1].keys.push(fingerprint('synthetic-race'));
  reveal.resolve({ value: 'synthetic-race', snapshot: 's1' }); await flush();
  assert.equal(ctx.calls.some(call => call[0] === 'remove-key' || call[0] === 'test'), false);
  assert.equal(group.querySelector('[data-saved-input]').value, '••••••••');
  assert.equal(group.querySelector('[data-action="copy"]').disabled, true);
  assert.match(group.querySelector('[data-info="error"]').textContent, /归属已变化/);
  ctx.close();
});

test('standalone and grouped keys render remaining-quota progress bars and omit empty bars without limits', async () => {
  const keys = ['synthetic-t1', 'synthetic-t2', 'synthetic-work'];
  const ctx = await setup({
    keys,
    groups: [account('default', '默认账号', [keys[0], keys[1]]), account('acc_Work', '工作账号', [keys[2]])],
  });
  const holder = ctx.window.document.createElement('div');
  ctx.root.append(holder);
  const cache = {
    id: 'tavily',
    balance_supported: true,
    accounts: [
      {
        id: 'default',
        total: null,
        keys: [
          { key_fingerprint: fingerprint(keys[0]), report: { provider: 'tavily', status: 'ok', scope: 'key', unit: 'credits', remaining: null, limit: null, used: 33, key_fingerprint: fingerprint(keys[0]) } },
          { key_fingerprint: fingerprint(keys[1]), report: { provider: 'tavily', status: 'ok', scope: 'key', unit: 'tokens', remaining: 5000, limit: null, used: null, key_fingerprint: fingerprint(keys[1]) } },
        ],
      },
      {
        id: 'acc_Work',
        total: { remaining: 180, limit: 1000, percent: 18, unit: 'credits', relative: false },
        keys: [
          { key_fingerprint: fingerprint(keys[2]), report: { provider: 'tavily', status: 'ok', scope: 'key', unit: 'credits', remaining: 40, limit: 100, used: 60, key_fingerprint: fingerprint(keys[2]) } },
        ],
      },
    ],
    current: [
      { provider: 'tavily', status: 'ok', scope: 'account', unit: 'credits', remaining: 967, limit: 1000, used: 33, key_fingerprint: fingerprint(keys[0]) },
    ],
  };
  const mounted = await mountProviderAccounts(holder, ctx.api, { source: 'tavily', usageProvider: cache });
  const standaloneRows = holder.querySelectorAll('[data-account-id="default"] .key-row');
  const firstBar = standaloneRows[0].querySelector('[data-key-meter] [role="progressbar"]');
  assert.ok(firstBar, 'Tavily standalone key inherits shared account remaining/limit for its bar');
  assert.equal(firstBar.getAttribute('aria-valuenow'), '96.7');
  assert.equal(standaloneRows[0].querySelector('[data-key-meter] .meter-fill').style.width, '96.7%');
  assert.equal(standaloneRows[0].querySelector('[data-key-meter] .meter-value').textContent, '96.7%');
  assert.equal(standaloneRows[1].querySelector('[data-key-meter]').hidden, true, 'unbounded quota never renders a fake 0% bar');
  assert.equal(standaloneRows[1].querySelector('[data-key-meter] [role="progressbar"]'), null);
  assert.match(standaloneRows[1].querySelector('[data-key-quota]').textContent, /剩余 5,000 tokens/);

  const work = holder.querySelector('[data-account-id="acc_Work"]');
  const accountBar = work.querySelector('[data-account-meter] [role="progressbar"]');
  assert.equal(accountBar.getAttribute('aria-valuenow'), '18');
  assert.equal(work.querySelector('[data-account-meter] .meter').dataset.level, 'low');
  const workKeyBar = work.querySelector('[data-key-meter] [role="progressbar"]');
  assert.equal(workKeyBar.getAttribute('aria-valuenow'), '40');
  mounted.dispose();
  ctx.close();
});
