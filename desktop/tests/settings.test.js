import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountSettings, SETTINGS_SOURCES } from '../ui/settings.js';

const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const BUILTINS = {
  default: { label: '默认（网页综合）', sources: ['brave', 'parallel', 'tavily', 'exa', 'serpapi', 'firecrawl', 'baidu'], timeout: null },
  fast: { label: '快速', sources: ['baidu', 'tavily', 'firecrawl', 'exa'], timeout: null },
  all: { label: '全部', sources: ['brave', 'parallel', 'tavily', 'exa', 'serpapi', 'baidu', 'firecrawl', 'twitter', 'stackoverflow', 'github_repos', 'hackernews', 'sov2ex'], timeout: null },
  social: { label: '社交（Twitter）', sources: ['twitter'], timeout: null },
  dev: { label: '开发者（Stack Overflow / GitHub / Hacker News）', sources: ['stackoverflow', 'github_repos', 'hackernews'], timeout: null },
};
const clone = value => JSON.parse(JSON.stringify(value));
const coded = (code, message = '') => JSON.stringify({ code, message });

let current = null;
function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  current = window;
  return { window, root };
}
test.afterEach(() => { try { current?.close(); } catch { /* already closed */ } current = null; });

function view(overrides = {}) {
  const routes = clone(overrides.routes || BUILTINS);
  const route = overrides.route || 'default';
  const timeout = overrides.timeout ?? 60;
  const selected = routes[route];
  const disabled = overrides.disabled_sources || [];
  return {
    config_path: 'C:/Users/test/.multi-search/config.sqlite',
    path_source: 'user',
    file_present: true,
    read_source: 'sqlite',
    route,
    timeout,
    timeout_configured: true,
    timeout_min: 1,
    timeout_max: 90,
    timeout_out_of_range: false,
    unknown_disabled_sources: [],
    effective_timeout: selected?.timeout ?? timeout,
    effective_timeouts: Object.fromEntries(Object.entries(routes).map(([id, item]) => [id, item.timeout ?? timeout])),
    routes,
    builtin_routes: clone(BUILTINS),
    disabled_sources: disabled,
    twitter_cookies_path: null,
    active_sources: selected?.sources.filter(source => !disabled.includes(source)) || [],
    status: 'ok',
    message: '',
    ...overrides,
  };
}

function savedView(input, overrides = {}) {
  const selected = input.routes[input.route];
  const timeout = input.timeout ?? 60;
  return view({
    ...input,
    timeout,
    routes: input.routes,
    effective_timeout: selected.timeout ?? timeout,
    active_sources: selected.sources.filter(source => !input.disabled_sources.includes(source)),
    ...overrides,
  });
}

const row = (root, id) => [...root.querySelectorAll('[data-route-row]')].find(node => node.getAttribute('data-route-row') === id);
const rowButton = (root, id, label) => [...row(root, id).querySelectorAll('button')].find(button => button.textContent === label);

async function openNew(root) {
  root.querySelector('[data-action="new-route"]').click();
  await flush();
  return root.querySelector('.route-editor');
}

function chooseSource(editor, source, checked = true) {
  const box = [...editor.querySelectorAll('[data-route-source]')].find(input => input.value === source);
  box.checked = checked;
  return box;
}

test('the CLI source list uses canonical underscore names', async () => {
  const { window, root } = setup();
  await mountSettings(root, ({ settingsView: async () => view() }));
  const names = SETTINGS_SOURCES.map(source => source.source);
  assert.equal(names.length, 12);
  assert.ok(names.every(name => !name.includes('-')));
  assert.ok(names.includes('github_repos'));
  assert.equal(root.querySelectorAll('[data-route-row]').length, 5);
  window.close();
});

test('saving submits the complete route draft and preserves global disabled sources', async () => {
  const { window, root } = setup();
  let sent = null;
  await mountSettings(root, ({
    settingsView: async () => view({ disabled_sources: ['exa'] }),
    settingsSave: async input => { sent = input; return savedView(input); },
  }));
  root.querySelector('[data-field="route"]').value = 'fast';
  root.querySelector('[data-field="route"]').dispatchEvent(new window.Event('change'));
  root.querySelector('[data-field="timeout"]').value = '30';
  root.querySelector('[data-field="timeout"]').dispatchEvent(new window.Event('input'));
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(sent.route, 'fast');
  assert.equal(sent.timeout, 30);
  assert.deepEqual(sent.disabled_sources, ['exa']);
  assert.deepEqual(sent.routes.fast, BUILTINS.fast);
  assert.equal(sent.twitter_cookies_path, '');
  assert.equal(root.querySelector('[data-status="save"]').textContent, '已保存。');
  window.close();
});

test('normal search-settings save leaves the custom scrape chain untouched', async () => {
  const { window, root } = setup();
  let sent = null;
  await mountSettings(root, ({
    settingsView: async () => view({ scrape_backends: ['firecrawl', 'jina'] }),
    settingsSave: async input => { sent = input; return savedView(input); },
  }));
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.ok(sent);
  assert.equal(Object.hasOwn(sent, 'scrape_backends'), false);
  window.close();
});

test('dynamic list supports create edit copy and delete after switching current route', async () => {
  const { window, root } = setup();
  await mountSettings(root, ({ settingsView: async () => view() }));
  let editor = await openNew(root);
  editor.querySelector('[data-edit="id"]').value = 'research';
  editor.querySelector('[data-edit="label"]').value = '研究组';
  editor.querySelector('[data-edit="timeout"]').value = '12';
  chooseSource(editor, 'github_repos');
  chooseSource(editor, 'hackernews');
  editor.querySelector('[data-action="apply-route"]').click();
  assert.ok(row(root, 'research'));
  assert.match(row(root, 'research').textContent, /独立超时 · 12 秒/);

  rowButton(root, 'research', '编辑').click();
  editor = root.querySelector('.route-editor');
  assert.equal(editor.querySelector('[data-edit="id"]').readOnly, true);
  editor.querySelector('[data-edit="label"]').value = '研究与社区';
  editor.querySelector('[data-edit="timeout"]').value = '';
  editor.querySelector('[data-action="apply-route"]').click();
  assert.match(row(root, 'research').textContent, /研究与社区/);
  assert.match(row(root, 'research').textContent, /继承全局/);

  rowButton(root, 'research', '复制').click();
  editor = root.querySelector('.route-editor');
  editor.querySelector('[data-edit="id"]').value = 'research_copy';
  editor.querySelector('[data-action="apply-route"]').click();
  assert.ok(row(root, 'research_copy'));

  const select = root.querySelector('[data-field="route"]');
  select.value = 'research';
  select.dispatchEvent(new window.Event('change'));
  assert.equal(rowButton(root, 'research', '删除').disabled, true);
  select.value = 'default';
  select.dispatchEvent(new window.Event('change'));
  rowButton(root, 'research', '删除').click();
  row(root, 'research').querySelector('[data-action="confirm-delete"]')?.click();
  assert.equal(row(root, 'research'), undefined);
  assert.ok(row(root, 'research_copy'));
  window.close();
});

test('route validation covers id label source timeout and duplicate ids', async () => {
  const { window, root } = setup();
  await mountSettings(root, ({ settingsView: async () => view() }));
  const editor = await openNew(root);
  const apply = editor.querySelector('[data-action="apply-route"]');
  editor.querySelector('[data-edit="id"]').value = 'web';
  editor.querySelector('[data-edit="label"]').value = 'Name';
  chooseSource(editor, 'tavily');
  apply.click();
  assert.match(editor.querySelector('[data-edit-error]').textContent, /不能使用 web/);
  editor.querySelector('[data-edit="id"]').value = 'UPPER'; apply.click();
  assert.match(editor.querySelector('[data-edit-error]').textContent, /ASCII/);
  editor.querySelector('[data-edit="id"]').value = 'fast'; apply.click();
  assert.match(editor.querySelector('[data-edit-error]').textContent, /已存在/);
  editor.querySelector('[data-edit="id"]').value = 'valid';
  editor.querySelector('[data-edit="label"]').value = ' '.repeat(4); apply.click();
  assert.match(editor.querySelector('[data-edit-error]').textContent, /名称/);
  editor.querySelector('[data-edit="label"]').value = 'Valid';
  chooseSource(editor, 'tavily', false); apply.click();
  assert.match(editor.querySelector('[data-edit-error]').textContent, /至少选择/);
  chooseSource(editor, 'tavily');
  editor.querySelector('[data-edit="timeout"]').value = '61'; apply.click();
  assert.match(editor.querySelector('[data-edit-error]').textContent, /1–60/);
  window.close();
});

test('globally disabled route members are gray but remain selectable and are not removed', async () => {
  const { window, root } = setup();
  let sent;
  await mountSettings(root, ({
    settingsView: async () => view({ route: 'fast', disabled_sources: ['exa'] }),
    settingsSave: async input => { sent = input; return savedView(input); },
  }));
  assert.match(row(root, 'fast').textContent, /Exa全局停用/);
  rowButton(root, 'fast', '编辑').click();
  const exa = chooseSource(root.querySelector('.route-editor'), 'exa');
  assert.equal(exa.disabled, false, 'global off is execution state, not membership editing permission');
  assert.equal(exa.checked, true);
  root.querySelector('.route-editor [data-action="apply-route"]').click();
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.ok(sent.routes.fast.sources.includes('exa'));
  assert.ok(sent.disabled_sources.includes('exa'));
  window.close();
});

test('restore confirmation resets only five factory ids and keeps custom groups', async () => {
  const { window, root } = setup();
  const routes = clone(BUILTINS);
  routes.fast = { label: '改过的快速', sources: ['twitter'], timeout: 9 };
  delete routes.social;
  routes.custom = { label: '自定义', sources: ['sov2ex'], timeout: null };
  await mountSettings(root, ({ settingsView: async () => view({ routes }) }));
  root.querySelector('[data-action="restore"]').click();
  assert.match(root.querySelector('[data-restore-confirm]').textContent, /自定义分组不会改变/);
  root.querySelector('[data-action="confirm-restore"]').click();
  assert.match(row(root, 'fast').textContent, /快速/);
  assert.match(row(root, 'fast').textContent, /Baidu AI 搜索/);
  assert.ok(row(root, 'social'));
  assert.ok(row(root, 'custom'));
  assert.match(row(root, 'custom').textContent, /自定义/);
  window.close();
});

test('save failure keeps draft and repeated submit is ignored while saving', async () => {
  const { window, root } = setup();
  let calls = 0;
  let rejectSave;
  await mountSettings(root, ({
    settingsView: async () => view(),
    settingsSave: () => { calls += 1; return new Promise((_, reject) => { rejectSave = reject; }); },
  }));
  root.querySelector('[data-field="timeout"]').value = '29';
  root.querySelector('[data-field="timeout"]').dispatchEvent(new window.Event('input'));
  const form = root.querySelector('[data-settings-form]');
  form.dispatchEvent(new window.Event('submit', { cancelable: true }));
  form.dispatchEvent(new window.Event('submit', { cancelable: true }));
  assert.equal(calls, 1);
  rejectSave('synthetic failure');
  await flush();
  assert.equal(root.querySelector('[data-field="timeout"]').value, '29');
  assert.equal(root.querySelector('[data-info="error"]').textContent, '保存失败，原配置未改变。');
  assert.equal(root.querySelector('[data-info="error"]').title, 'synthetic failure', 'the raw reason stays available for support');
  assert.notEqual(root.querySelector('[data-status="save"]').textContent, '已保存。');
  window.close();
});

test('late save response never overwrites edits made while the request is in flight', async () => {
  const { window, root } = setup();
  let resolveSave;
  await mountSettings(root, ({
    settingsView: async () => view(),
    settingsSave: input => new Promise(resolve => { resolveSave = () => resolve(savedView(input)); }),
  }));
  const timeout = root.querySelector('[data-field="timeout"]');
  timeout.value = '20'; timeout.dispatchEvent(new window.Event('input'));
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  timeout.value = '21'; timeout.dispatchEvent(new window.Event('input'));
  resolveSave(); await flush();
  assert.equal(timeout.value, '21');
  assert.match(root.querySelector('[data-status="draft"]').textContent, /仍未保存/);
  window.close();
});

test('refresh requires inline confirmation when a draft would be lost', async () => {
  const { window, root } = setup();
  let reads = 0;
  await mountSettings(root, ({ settingsView: async () => { reads += 1; return view({ timeout: reads === 1 ? 60 : 18 }); } }));
  const timeout = root.querySelector('[data-field="timeout"]');
  timeout.value = '25'; timeout.dispatchEvent(new window.Event('input'));
  root.querySelector('[data-action="refresh"]').click();
  await flush();
  assert.equal(reads, 1);
  assert.match(root.querySelector('[data-refresh-confirm]').textContent, /丢弃未保存草稿/);
  root.querySelector('[data-action="confirm-refresh"]').click();
  await flush();
  assert.equal(reads, 2);
  assert.equal(timeout.value, '18');
  window.close();
});

test('late refresh response cannot overwrite edits or race a save', async () => {
  const { window, root } = setup();
  let reads = 0;
  let resolveRefresh;
  let saves = 0;
  await mountSettings(root, ({
    settingsView: async () => {
      reads += 1;
      if (reads === 1) return view();
      return new Promise(resolve => { resolveRefresh = resolve; });
    },
    settingsSave: async input => { saves += 1; return savedView(input); },
  }));
  root.querySelector('[data-action="refresh"]').click();
  await flush();
  const timeout = root.querySelector('[data-field="timeout"]');
  timeout.value = '25'; timeout.dispatchEvent(new window.Event('input'));
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  assert.equal(saves, 0, 'save is blocked while refresh is unresolved');
  resolveRefresh(view({ timeout: 18 }));
  await flush();
  assert.equal(timeout.value, '25', 'late refresh does not replace a newer draft');
  assert.match(root.querySelector('[data-info="error"]').textContent, /刷新结果未应用/);
  window.close();
});

test('rejected refresh preserves edits made while it was pending', async () => {
  const { window, root } = setup();
  let reads = 0;
  let rejectRefresh;
  await mountSettings(root, ({
    settingsView: async () => {
      reads += 1;
      if (reads === 1) return view();
      return new Promise((_, reject) => { rejectRefresh = reject; });
    },
  }));
  root.querySelector('[data-action="refresh"]').click();
  await flush();
  const timeout = root.querySelector('[data-field="timeout"]');
  timeout.value = '27'; timeout.dispatchEvent(new window.Event('input'));
  rejectRefresh(new Error('offline'));
  await flush();
  assert.equal(timeout.value, '27');
  assert.equal(root.querySelectorAll('[data-route-row]').length, 5);
  assert.equal(root.querySelector('[data-action="save"]').disabled, false);
  assert.match(root.querySelector('[data-info="error"]').textContent, /草稿和已加载设置保持不变/);
  window.close();
});

test('first settings load failure leaves an empty disabled view', async () => {
  const { window, root } = setup();
  await mountSettings(root, ({ settingsView: async () => { throw new Error('offline'); } }));
  assert.equal(root.querySelectorAll('[data-route-row]').length, 0);
  assert.equal(root.querySelector('[data-action="save"]').disabled, true);
  assert.equal(root.querySelector('[data-field="route"]').disabled, true);
  assert.match(root.querySelector('[data-info="error"]').textContent, /无法读取搜索设置/);
  window.close();
});

test('unapplied editor input blocks save and requires confirmation before discard', async () => {
  const { window, root } = setup();
  let saves = 0;
  const mounted = await mountSettings(root, ({ settingsView: async () => view(), settingsSave: async input => { saves += 1; return savedView(input); } }));
  const editor = await openNew(root);
  const id = editor.querySelector('[data-edit="id"]');
  id.value = 'draft_only'; id.dispatchEvent(new window.Event('input'));
  assert.equal(mounted.dirty, false, 'editor input is distinct from the applied route draft');
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  assert.equal(saves, 0);
  assert.match(root.querySelector('[data-info="error"]').textContent, /未应用输入/);

  root.querySelector('[data-action="refresh"]').click();
  assert.match(root.querySelector('[data-refresh-confirm]').textContent, /丢弃未保存草稿/);
  root.querySelector('[data-action="cancel-refresh"]').click();
  editor.querySelector('[data-action="close-editor"]').click();
  assert.ok(root.querySelector('[data-editor-discard]'));
  assert.ok(root.querySelector('.route-editor'), 'the editor remains until discard is confirmed');
  root.querySelector('[data-action="keep-editor"]').click();
  assert.ok(root.querySelector('.route-editor'));
  editor.querySelector('[data-action="close-editor"]').click();
  root.querySelector('[data-action="discard-editor"]').click();
  assert.equal(root.querySelector('.route-editor'), null);
  window.close();
});

test('unreadable settings do not fake defaults and disable editing', async () => {
  const { window, root } = setup();
  await mountSettings(root, ({ settingsView: async () => view({ route: '', routes: {}, status: 'config_unreadable', message: '坏 routes' }) }));
  assert.equal(root.querySelectorAll('[data-route-row]').length, 0);
  assert.equal(root.querySelector('[data-action="save"]').disabled, true);
  assert.match(root.querySelector('[data-info="error"]').textContent, /坏 routes/);
  window.close();
});

test('route names are rendered as text and __proto__ remains an own JSON route id', async () => {
  const { window, root } = setup();
  let sent;
  await mountSettings(root, ({ settingsView: async () => view(), settingsSave: async input => { sent = input; return savedView(input); } }));
  const editor = await openNew(root);
  editor.querySelector('[data-edit="id"]').value = '__proto__';
  editor.querySelector('[data-edit="label"]').value = '<img src=x onerror=attack()>';
  chooseSource(editor, 'tavily');
  editor.querySelector('[data-action="apply-route"]').click();
  assert.equal(row(root, '__proto__').querySelector('img'), null);
  assert.match(row(root, '__proto__').textContent, /<img src=x/);
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(Object.hasOwn(sent.routes, '__proto__'), true);
  assert.equal(sent.routes.__proto__.label, '<img src=x onerror=attack()>');
  window.close();
});

test('summary shows backend effective timeout when no global timeout exists yet', async () => {
  const { window, root } = setup();
  await mountSettings(root, ({ settingsView: async () => view({ route: 'fast', timeout: 60, timeout_configured: false, effective_timeout: 45, effective_timeouts: { default: 60, fast: 45, all: 90, social: 60, dev: 60 } }) }));
  assert.equal(root.querySelector('[data-summary="effective-timeout"]').textContent, '45');
  assert.match(root.querySelector('[data-summary="timeout-kind"]').textContent, /CLI 内置值/);
  assert.match(row(root, 'fast').textContent, /当前配置 · 45 秒/);
  window.close();
});

test('SQLite is the only displayed configuration source and old sources are not promised an import path', async () => {
  const { window, root } = setup();
  await mountSettings(root, ({ settingsView: async () => view({ config_path: 'D:/env/config.sqlite', path_source: 'env', read_source: 'sqlite', twitter_cookies_path: 'C:/cookies.json' }) }));
  const info = root.querySelector('[data-info="env"]').textContent;
  assert.match(root.querySelector('[data-status="path-source"]').textContent, /MULTI_SEARCH_CONFIG_DB/);
  assert.match(info, /SQLite 是唯一生效配置来源/);
  assert.match(info, /不会自动生效/);
  assert.doesNotMatch(info, /导入|迁移/);
  assert.equal(root.querySelector('[data-field="twitter"]').value, 'C:/cookies.json');
  window.close();
});

test('page uses its navigation number, a focusable heading, and no cookie panel', async () => {
  const { window, root } = setup();
  let cookieReads = 0;
  await mountSettings(root, { settingsView: async () => view(), cookieStatus: async () => { cookieReads += 1; return { present: false, mode: 'file', supported: true }; } }, { number: '05' });
  assert.match(root.querySelector('.eyebrow').textContent, /^05 \/ /);
  assert.equal(root.querySelector('h1').getAttribute('tabindex'), '-1');
  assert.equal(root.querySelector('[data-cookie-path]'), null, 'Cookie hosting lives on its own page');
  assert.equal(cookieReads, 0);
  window.close();
});

test('an untouched timeout is sent as null so the stored value is never rewritten', async () => {
  const { window, root } = setup();
  let sent = null;
  await mountSettings(root, {
    settingsView: async () => view({ timeout: 25, timeout_configured: false }),
    settingsSave: async input => { sent = input; return savedView(input); },
  });
  assert.match(root.querySelector('[data-info="env"]').textContent, /没有显式的全局超时/);
  root.querySelector('[data-field="route"]').value = 'dev';
  root.querySelector('[data-field="route"]').dispatchEvent(new window.Event('change'));
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(sent.timeout, null);
  assert.equal(sent.route, 'dev');
  window.close();
});

test('timeout bounds come from the backend and an out-of-range stored value is kept until edited', async () => {
  const { window, root } = setup();
  const sent = [];
  await mountSettings(root, {
    settingsView: async () => view({ timeout: 120, timeout_out_of_range: true, timeout_min: 1, timeout_max: 90 }),
    settingsSave: async input => { sent.push(input); return savedView({ ...input, timeout: input.timeout ?? 120 }, { timeout_out_of_range: input.timeout == null }); },
  });
  const field = root.querySelector('[data-field="timeout"]');
  assert.equal(field.max, '90');
  assert.match(root.querySelector('[data-info="env"]').textContent, /已保存的超时 120 秒超出 1 到 90 秒；不修改则原样保留/);
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(sent[0].timeout, null, 'an untouched out-of-range value is not rewritten');
  field.value = '95';
  field.dispatchEvent(new window.Event('input'));
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(sent.length, 1, 'an edited out-of-range value is refused locally');
  assert.match(root.querySelector('[data-info="error"]').textContent, /1 到 90 秒/);
  field.value = '80';
  field.dispatchEvent(new window.Event('input'));
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.equal(sent[1].timeout, 80);
  window.close();
});

test('unknown disabled entries are explained and survive a save', async () => {
  const { window, root } = setup();
  let sent = null;
  await mountSettings(root, {
    settingsView: async () => view({ disabled_sources: ['exa'], unknown_disabled_sources: ['retired_engine'] }),
    settingsSave: async input => { sent = input; return savedView(input); },
  });
  assert.match(root.querySelector('[data-info="env"]').textContent, /无法识别的禁用项（retired_engine）/);
  root.querySelector('[data-settings-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush();
  assert.deepEqual(sent.disabled_sources, ['exa'], 'only known names are sent; the backend keeps the rest');
  window.close();
});

test('a coded read failure shows the mapped Chinese reason and refresh recovers', async () => {
  const { window, root } = setup();
  let fail = true;
  await mountSettings(root, { settingsView: async () => { if (fail) throw coded('settings_view_failed', 'Settings view worker failed'); return view(); } });
  assert.equal(root.querySelector('[data-info="error"]').textContent, '设置读取失败，请重新读取。');
  assert.equal(root.querySelector('[data-action="save"]').disabled, true);
  fail = false;
  root.querySelector('[data-action="refresh"]').click();
  await flush(); await flush();
  assert.equal(root.querySelector('[data-action="save"]').disabled, false);
  assert.equal(root.querySelector('[data-info="error"]').textContent, '');
  window.close();
});

test('the refresh-discard confirmation focuses the safe choice and Escape keeps the draft', async () => {
  const { window, root } = setup();
  let reads = 0;
  await mountSettings(root, { settingsView: async () => { reads += 1; return view(); } });
  const timeout = root.querySelector('[data-field="timeout"]');
  timeout.value = '33'; timeout.dispatchEvent(new window.Event('input'));
  const trigger = root.querySelector('[data-action="refresh"]');
  trigger.focus();
  trigger.click();
  const panel = root.querySelector('.refresh-confirm');
  assert.equal(panel.getAttribute('role'), 'group');
  assert.equal(window.document.activeElement, panel.querySelector('[data-action="cancel-refresh"]'));
  panel.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(root.querySelector('.refresh-confirm'), null);
  assert.equal(window.document.activeElement, trigger);
  assert.equal(timeout.value, '33');
  assert.equal(reads, 1);
  window.close();
});
