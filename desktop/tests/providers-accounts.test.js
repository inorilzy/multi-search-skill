import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { Window } from 'happy-dom';
import { mountSources } from '../ui/sources.js';
import { mountOAuthLogin } from '../ui/oauth-login.js';

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

test('opening a provider reuses the page account groups instead of re-reading the list first', async () => {
  const ctx = await setup({ keys: ['synthetic-one', 'synthetic-two'],
    groups: [account('default', '默认账号', ['synthetic-one']), account('acc_A', 'A', ['synthetic-two'])] });
  const before = ctx.calls.filter(([kind]) => kind === 'accounts').length;
  await ctx.open();
  assert.ok(groupFor(ctx, 'default') && groupFor(ctx, 'acc_A'), 'both account groups rendered');
  // Only each editor's own ownership check reads accounts; the list itself comes from the page cache.
  assert.equal(ctx.calls.filter(([kind]) => kind === 'accounts').length - before, 2);
  ctx.close();
});

test('T07 accounts: collapsed provider row uses T05 thin meter and alert, reads cache without secrets or refresh', async () => {
  const ctx = await setup({ keys: ['synthetic-default'] });
  assert.equal(ctx.root.querySelector('h1').textContent, '服务商');
  assert.match(ctx.root.querySelector('.eyebrow').textContent, /PROVIDERS/);
  assert.ok(ctx.root.querySelector('.provider-list > .provider-row > .provider-summary'));
  assert.equal(ctx.row.querySelector('.provider-counts').textContent, '1 个账号 · 1 个 Key');
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

test('T07 accounts: account metadata and balance credentials render as text; empty default hides', async () => {
  const malicious = '<img src=x onerror=alert(1)>';
  const ctx = await setup({ source: 'parallel', groups: [account('default', '默认账号'), account('acc_P', malicious, [], { source: 'oauth', login_identity: malicious, balance_credentials: { parallel_account: malicious } })] });
  await ctx.open();
  assert.equal(groupFor(ctx, 'default'), null);
  const group = groupFor(ctx, 'acc_P');
  assert.equal(group.querySelector('.account-name').textContent, malicious);
  assert.ok(group.textContent.includes('Parallel 账户令牌 · 仅查余额'));
  assert.ok(group.textContent.includes('请为这个账号添加搜索 Key'));
  assert.equal(group.querySelector('img'), null);
  assert.equal(ctx.row.querySelector('.provider-counts').textContent, '1 个账号 · 0 个 Key');
  group.querySelector('[data-action="test"]').click(); await flush();
  assert.equal(ctx.calls.some(call => call[0] === 'test'), false, 'an empty account never tests another account’s key');
  assert.match(group.querySelector('[data-info="error"]').textContent, /请为这个账号添加搜索 Key/);
  ctx.close();
});

// Accounts come from a browser login or pasted keys, so there is no "create an empty
// account" control any more; renaming still sends the literal name.
test('T07 accounts: rename sends provider, account id and literal name; default has neither destructive control', async () => {
  const ctx = await setup({ keys: ['synthetic-default'], groups: [account('default', '默认账号', ['synthetic-default']), account('acc_New', '登录账号', [], { source: 'oauth' })] });
  await ctx.open();
  assert.equal(ctx.row.querySelector('[data-account-action="add"]'), null, 'no empty-account creation');
  assert.equal(groupFor(ctx, 'default').querySelector('[data-account-action="rename"]'), null);
  assert.equal(groupFor(ctx, 'default').querySelector('[data-account-action="remove"]'), null);
  let group = groupFor(ctx, 'acc_New');
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
  assert.equal(ctx.row.querySelector('.provider-counts').textContent, `1 个账号 · ${deleteKeys ? 1 : 2} 个 Key`);
  ctx.close();
});

test('T07 accounts: account-local test and remove resolve the current global index and snapshot', async () => {
  const ctx = await setup({ keys: ['synthetic-first', 'synthetic-company'], groups: [account('default', '默认账号', ['synthetic-first']), account('acc_C', '公司', ['synthetic-company'])] });
  await ctx.open();
  const group = groupFor(ctx, 'acc_C');
  assert.equal(group.querySelector('.key-fingerprint').textContent, fingerprint('synthetic-company'));
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
  assert.equal(groupFor(ctx, 'acc_C').querySelector('.key-fingerprint').textContent, fingerprint('synthetic-new'));
  assert.match(groupFor(ctx, 'acc_C').querySelector('.account-summary').textContent, /1 个 Key/);
  assert.equal(ctx.row.querySelector('.provider-counts').textContent, '2 个账号 · 2 个 Key');
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
  assert.ok(groupFor(ctx, 'acc_Login').textContent.includes('请为这个账号添加搜索 Key'));
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
  assert.equal(row.querySelector('.provider-counts').textContent, '1 个账号 · 1 个 Key');
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
  assert.ok(group.textContent.includes('Exa 管理 Key · 仅查余额'));
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

test('T07 accounts: Exa can add a management key when its empty default account starts hidden', async () => {
  const ctx = await setup({ source: 'exa', groups: [account('default', '默认账号'), account('acc_C', '公司')] });
  await ctx.open();
  assert.equal(groupFor(ctx, 'default'), null);
  const add = ctx.row.querySelector('[data-account-action="add-admin"]');
  assert.equal(add.hidden, false);
  add.click(); await flush();
  assert.ok(groupFor(ctx, 'default').querySelector('.exa-admin-key'));
  assert.equal(groupFor(ctx, 'acc_C').querySelector('.exa-admin-key'), null);
  ctx.close();
});


for (const [search, scrape, count] of [[0, 0, 0], [2, 3, 5], [undefined, 0, '未知']]) test(`T07 accounts: unsupported balance shows literal local calls (${count})`, async () => {
  const ctx = await setup({ overrides: { usageView: async () => ({ providers: [{ id: 'tavily', balance_supported: false, calls: { today: { search, scrape, failures: 9 } } }] }) } });
  assert.equal(ctx.row.querySelector('.provider-meter').textContent, `无余额接口 · 今天调用 ${count} 次`);
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
