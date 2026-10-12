import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountSkill } from '../ui/skill.js';

const tick = () => new Promise(resolve => setTimeout(resolve, 5));

function setup(api) {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root, page: mountSkill(root, api) };
}

test('install stays disabled until the target is previewed', async () => {
  const calls = [];
  const api = {
    skillPlan: async (scope, project) => { calls.push(['plan', scope, project]); return { scope, target: 'C:\\home\\.claude\\skills\\multi-search', files: ['SKILL.md'], status: 'ready', reason: 'ok', can_install: true }; },
    skillInstall: async (scope, project) => { calls.push(['install', scope, project]); return { status: 'installed', target: 'C:\\home\\.claude\\skills\\multi-search', reason: 'verified', verified: true }; },
  };
  const { root, window } = setup(api);
  assert.equal(root.querySelector('[data-action="install"]').disabled, true);
  root.querySelector('[data-action="preview"]').click();
  await tick();
  assert.match(root.textContent, /C:\\home\\\.claude\\skills\\multi-search/);
  assert.equal(root.querySelector('[data-action="install"]').disabled, false);
  root.querySelector('[data-action="install"]').click();
  await tick();
  assert.deepEqual(calls.map(c => c[0]), ['plan', 'install']);
  assert.match(root.textContent, /已安装并校验/);
  window.close();
});

test('project scope needs a project path and changing scope clears the preview', async () => {
  const api = { skillPlan: async () => ({ scope: 'project', target: null, files: [], status: 'invalid_scope', reason: 'Select the project directory', can_install: false }), skillInstall: async () => ({}) };
  const { root, window } = setup(api);
  const project = root.querySelector('[data-field="project"]');
  assert.equal(project.disabled, true);
  root.querySelector('input[value="project"]').click();
  await tick();
  assert.equal(project.disabled, false);
  root.querySelector('[data-action="preview"]').click();
  await tick();
  assert.match(root.textContent, /目标无效/);
  assert.equal(root.querySelector('[data-action="install"]').disabled, true);
  window.close();
});

test('an incompatible or missing CLI is shown as blocked, not configured', async () => {
  const api = { skillPlan: async () => ({ scope: 'global', target: 'C:\\x', files: [], status: 'cli_incompatible', reason: 'update the CLI', can_install: false }), skillInstall: async () => ({}) };
  const { root, window } = setup(api);
  root.querySelector('[data-action="preview"]').click();
  await tick();
  assert.match(root.textContent, /CLI 与 Skill 不兼容/);
  assert.equal(root.querySelector('[data-action="install"]').disabled, true);
  window.close();
});

test('a failed write reports the real failure reason', async () => {
  const api = {
    skillPlan: async () => ({ scope: 'global', target: 'C:\\x', files: [], status: 'ready', reason: 'ok', can_install: true }),
    skillInstall: async () => ({ status: 'failed', target: 'C:\\x', reason: 'Cannot place the skill at the target: access denied', verified: false }),
  };
  const { root, window } = setup(api);
  root.querySelector('[data-action="preview"]').click(); await tick();
  root.querySelector('[data-action="install"]').click(); await tick();
  assert.match(root.textContent, /未完成安装：Cannot place the skill/);
  // Check the install status line only; the static "已安装 Skill" heading is unrelated page text.
  assert.doesNotMatch(root.querySelector('[data-info="status"]').textContent, /已安装并校验/);
  window.close();
});

test('update is enabled only for a managed outdated or modified skill, and local edits need the overwrite checkbox', async () => {
  const calls = [];
  const api = {
    skillStatus: async () => ({ state: 'modified', installed_version: '1', release_version: '1', modified_files: ['SKILL.md'], unknown_entries: [], reason: 'edited' }),
    skillUpdate: async (scope, project, confirm) => { calls.push(['update', confirm]); return { status: 'updated', reason: 'verified', backup: 'C:\\b' }; },
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  };
  const { root, window } = setup(api);
  const update = root.querySelector('[data-action="update"]');
  assert.equal(update.disabled, true);
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.match(root.textContent, /本地修改：SKILL\.md/);
  assert.equal(update.disabled, false);
  // Without the explicit checkbox the backend is told not to overwrite.
  update.click(); await tick();
  assert.deepEqual(calls[0], ['update', false]);
  window.close();
});

test('a current skill cannot be updated, and removal requires a preview before its confirm button enables', async () => {
  const removed = [];
  const api = {
    skillStatus: async () => ({ state: 'current', installed_version: '1', release_version: '1', modified_files: [], unknown_entries: ['notes.md'], reason: 'ok' }),
    skillUpdate: async () => ({}),
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md', '.multi-search-install.json'], will_keep: ['notes.md'], reason: 'only ours' }),
    skillRemove: async (scope, project, confirmed) => { removed.push(confirmed); return { status: 'removed', deleted: ['SKILL.md'], reason: 'done' }; },
  };
  const { root, window } = setup(api);
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  const confirm = root.querySelector('[data-action="remove"]');
  assert.equal(confirm.disabled, true);
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  assert.match(root.textContent, /将删除：SKILL\.md、\.multi-search-install\.json/);
  assert.match(root.textContent, /保留：notes\.md/);
  assert.equal(confirm.disabled, false);
  confirm.click(); await tick();
  assert.deepEqual(removed, [true]);
  assert.match(root.textContent, /已移除：SKILL\.md/);
  window.close();
});

test('a failed update reports that the previous skill was kept', async () => {
  const api = {
    skillStatus: async () => ({ state: 'outdated', installed_version: '0', release_version: '1', modified_files: [], unknown_entries: [], reason: 'old' }),
    skillUpdate: async () => ({ status: 'failed', reason: 'Update failed verification; the installed skill was kept.', verified: false, backup: null }),
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  };
  const { root, window } = setup(api);
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick();
  assert.match(root.textContent, /未完成更新（原 Skill 保持可用）/);
  assert.doesNotMatch(root.textContent, /已更新/);
  window.close();
});
