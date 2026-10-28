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
    skillStatus: async () => ({ state: 'modified', can_update: true, installed_version: '1', release_version: '1', modified_files: ['SKILL.md'], unknown_entries: [], reason: 'edited' }),
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

test('installed target and CLI requirements are visible and incompatible updates stay disabled', async () => {
  const { root, window } = setup({ skillStatus: async () => ({
    state: 'outdated', can_update: true, installed_version: '0', release_version: '1', target: 'C:\\isolated\\.claude\\skills\\multi-search',
    modified_files: [], unknown_entries: [], reason: 'old', can_update: false, cli_compatible: false,
    cli_requirements: 'search: --expand; fetch: --full-content', compatibility_reason: 'Missing --expand',
  }) });
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.match(root.textContent, /目标目录：C:/);
  assert.match(root.textContent, /CLI 要求：search: --expand/);
  assert.match(root.textContent, /Missing --expand/);
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  window.close();
});

test('changing scope invalidates a removal confirmation even after switching back', async () => {
  const removed = [];
  const { root, window } = setup({
    skillStatus: async () => ({ state: 'current', installed_version: '1', release_version: '1', modified_files: [], unknown_entries: [], reason: 'ok' }),
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
    skillRemove: async () => { removed.push(true); return {status: 'removed', deleted: []}; },
  });
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  root.querySelector('input[value="project"]').click();
  root.querySelector('input[value="global"]').click();
  root.querySelector('[data-action="remove"]').click(); await tick();
  assert.deepEqual(removed, []);
  assert.equal(root.querySelector('[data-action="remove"]').disabled, true);
  window.close();
});

test('stale removal preview cannot re-enable confirmation after target changes', async () => {
  let resolvePlan;
  const { root, window } = setup({
    skillStatus: async () => ({ state: 'current', installed_version: '1', release_version: '1', modified_files: [], unknown_entries: [], reason: 'ok' }),
    skillRemovePlan: () => new Promise(resolve => { resolvePlan = resolve; }),
  });
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="remove-plan"]').click();
  root.querySelector('input[value="project"]').click();
  resolvePlan({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'old target' }); await tick();
  assert.equal(root.querySelector('[data-action="remove"]').disabled, true);
  assert.doesNotMatch(root.querySelector('[data-info="manage-plan"]').textContent, /old target/);
  window.close();
});

test('confirmed overwrite displays the actual backup and verified outcome', async () => {
  const calls = [];
  const { root, window } = setup({
    skillStatus: async () => ({ state: 'modified', can_update: true, installed_version: '1', release_version: '1', modified_files: ['SKILL.md'], unknown_entries: [], reason: 'edited' }),
    skillUpdate: async (scope, project, confirm) => { calls.push(confirm); return { status: 'updated', verified: true, backup: 'C:/backup', reason: 'verified' }; },
  });
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-field="confirm-overwrite"]').click();
  root.querySelector('[data-action="update"]').click(); await tick();
  assert.deepEqual(calls, [true]);
  assert.match(root.querySelector('[data-info="manage-status"]').textContent, /已更新并校验.*C:\/backup/);
  window.close();
});

test('a pending update prevents a concurrent removal or refreshed confirmation', async () => {
  let finishUpdate;
  const removals = [];
  const { root, window } = setup({
    skillStatus: async () => ({ state: 'modified', can_update: true, installed_version: '1', release_version: '1', modified_files: ['SKILL.md'], unknown_entries: [], reason: 'edited' }),
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
    skillUpdate: () => new Promise(resolve => { finishUpdate = resolve; }),
    skillRemove: async () => { removals.push(true); return { status: 'removed', deleted: [] }; },
  });
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  root.querySelector('[data-action="update"]').click();
  root.querySelector('[data-action="remove"]').click(); await tick();
  assert.deepEqual(removals, []);
  assert.equal(root.querySelector('[data-action="check"]').disabled, true);
  finishUpdate({ status: 'updated', verified: true, reason: 'done' }); await tick();
  window.close();
});

test('a failed update reports that the previous skill was kept', async () => {
  const api = {
    skillStatus: async () => ({ state: 'outdated', can_update: true, installed_version: '0', release_version: '1', modified_files: [], unknown_entries: [], reason: 'old' }),
    skillUpdate: async () => ({ status: 'failed', reason: 'Update failed verification; the installed skill was kept.', verified: false, backup: null }),
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  };
  const { root, window } = setup(api);
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick();
  assert.match(root.textContent, /未完成更新：Update failed verification; the installed skill was kept/);
  assert.doesNotMatch(root.textContent, /已更新/);
  window.close();
});

test('a successful install automatically refreshes the manage panel to the installed state', async () => {
  let installed = false;
  const statusCalls = [];
  const api = {
    skillPlan: async () => ({ scope: 'global', target: 'C:\\isolated\\skills\\multi-search', files: ['SKILL.md'], status: 'ready', reason: 'ok', can_install: true }),
    skillInstall: async () => { installed = true; return { status: 'installed', target: 'C:\\isolated\\skills\\multi-search', reason: 'verified', verified: true }; },
    skillStatus: async (scope) => {
      statusCalls.push(scope);
      return installed
        ? { state: 'current', installed_version: '1', release_version: '1', target: 'C:\\isolated\\skills\\multi-search', modified_files: [], unknown_entries: [], reason: 'ok', can_update: false, cli_requirements: 'search', compatibility_reason: '' }
        : { state: 'absent', installed_version: null, release_version: '1', target: 'C:\\isolated\\skills\\multi-search', modified_files: [], unknown_entries: [], reason: 'not installed', can_update: false, cli_requirements: 'search', compatibility_reason: '' };
    },
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}), skillUpdate: async () => ({}),
  };
  const { root, window } = setup(api);
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.match(root.querySelector('[data-info="installed"]').textContent, /状态：未安装/);
  root.querySelector('[data-action="preview"]').click(); await tick();
  root.querySelector('[data-action="install"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="status"]').textContent, /已安装并校验/);
  assert.match(root.querySelector('[data-info="installed"]').textContent, /状态：当前版本/);
  assert.match(root.querySelector('[data-info="managed-target"]').textContent, /C:\\isolated\\skills\\multi-search/);
  assert.equal(root.querySelector('[data-action="remove-plan"]').disabled, false);
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  assert.equal(statusCalls.length, 2);
  window.close();
});

test('a failed install re-reads the real state and never reports installed', async () => {
  const api = {
    skillPlan: async () => ({ scope: 'global', target: 'C:\\x', files: [], status: 'ready', reason: 'ok', can_install: true }),
    skillInstall: async () => ({ status: 'failed', target: 'C:\\x', reason: 'access denied', verified: false }),
    skillStatus: async () => ({ state: 'absent', installed_version: null, release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'not installed', can_update: false }),
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}), skillUpdate: async () => ({}),
  };
  const { root, window } = setup(api);
  root.querySelector('[data-action="preview"]').click(); await tick();
  root.querySelector('[data-action="install"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="status"]').textContent, /未完成安装：access denied/);
  assert.match(root.querySelector('[data-info="installed"]').textContent, /状态：未安装/);
  assert.doesNotMatch(root.textContent, /已安装并校验/);
  window.close();
});

test('a read failure after a successful install reports completion with unconfirmed state, and a later check recovers', async () => {
  let reads = 0;
  const api = {
    skillPlan: async () => ({ scope: 'global', target: 'C:\\x', files: [], status: 'ready', reason: 'ok', can_install: true }),
    skillInstall: async () => ({ status: 'installed', target: 'C:\\x', reason: 'verified', verified: true }),
    skillStatus: async () => {
      reads += 1;
      if (reads === 1) throw new Error('disk busy');
      return { state: 'current', installed_version: '1', release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'ok', can_update: false };
    },
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}), skillUpdate: async () => ({}),
  };
  const { root, window } = setup(api);
  root.querySelector('[data-action="preview"]').click(); await tick();
  root.querySelector('[data-action="install"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="status"]').textContent, /已安装并校验/);
  assert.match(root.querySelector('[data-info="manage-error"]').textContent, /操作已完成，当前状态未确认/);
  assert.equal(root.querySelector('[data-action="remove-plan"]').disabled, true);
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.match(root.querySelector('[data-info="installed"]').textContent, /状态：当前版本/);
  assert.equal(root.querySelector('[data-info="manage-error"]').textContent, '');
  window.close();
});

test('an install clears a previously previewed removal so its confirm button cannot fire', async () => {
  const removed = [];
  const api = {
    skillPlan: async () => ({ scope: 'global', target: 'C:\\x', files: [], status: 'ready', reason: 'ok', can_install: true }),
    skillInstall: async () => ({ status: 'installed', target: 'C:\\x', reason: 'verified', verified: true }),
    skillStatus: async () => ({ state: 'current', installed_version: '1', release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'ok', can_update: false }),
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
    skillRemove: async () => { removed.push(true); return { status: 'removed', deleted: [] }; },
    skillUpdate: async () => ({}),
  };
  const { root, window } = setup(api);
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  assert.equal(root.querySelector('[data-action="remove"]').disabled, false);
  root.querySelector('[data-action="preview"]').click(); await tick();
  root.querySelector('[data-action="install"]').click(); await tick(); await tick();
  assert.equal(root.querySelector('[data-action="remove"]').disabled, true);
  root.querySelector('[data-action="remove"]').click(); await tick();
  assert.deepEqual(removed, []);
  window.close();
});

test('cancelling a removal preview issues no removal request and leaves the state untouched', async () => {
  const removed = [];
  const { root, window } = setup({
    skillStatus: async () => ({ state: 'current', installed_version: '1', release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'ok', can_update: false }),
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
    skillRemove: async () => { removed.push(true); return { status: 'removed', deleted: [] }; },
  });
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  // Cancel = user never presses the confirm button; navigating the scope back to the same target is not a removal.
  assert.equal(root.querySelector('[data-action="remove"]').disabled, false);
  assert.deepEqual(removed, []);
  assert.match(root.querySelector('[data-info="installed"]').textContent, /状态：当前版本/);
  window.close();
});

test('a successful removal clears the stale install success line and refreshes both panels to not-installed', async () => {
  let removedNow = false;
  const removed = [];
  const api = {
    skillPlan: async () => ({ scope: 'global', target: 'C:\\x', files: [], status: 'ready', reason: 'ok', can_install: true }),
    skillInstall: async () => ({ status: 'installed', target: 'C:\\x', reason: 'verified', verified: true }),
    skillStatus: async () => removedNow
      ? { state: 'absent', installed_version: null, release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'not installed', can_update: false }
      : { state: 'current', installed_version: '1', release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'ok', can_update: false },
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
    skillRemove: async () => { removed.push(true); removedNow = true; return { status: 'removed', deleted: ['SKILL.md'], reason: 'done' }; },
    skillUpdate: async () => ({}),
  };
  const { root, window } = setup(api);
  root.querySelector('[data-action="preview"]').click(); await tick();
  root.querySelector('[data-action="install"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="status"]').textContent, /已安装并校验/);
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  root.querySelector('[data-action="remove"]').click(); await tick(); await tick();
  assert.deepEqual(removed, [true]);
  assert.equal(root.querySelector('[data-info="status"]').textContent, '');
  assert.doesNotMatch(root.textContent, /已安装并校验/);
  assert.match(root.querySelector('[data-info="installed"]').textContent, /状态：未安装/);
  assert.equal(root.querySelector('[data-action="remove-plan"]').disabled, true);
  assert.equal(root.querySelector('[data-action="remove"]').disabled, true);
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  assert.match(root.querySelector('[data-info="manage-status"]').textContent, /已移除：SKILL\.md/);
  window.close();
});

test('a failed removal reports the real reason and does not claim the skill was removed', async () => {
  const { root, window } = setup({
    skillStatus: async () => ({ state: 'current', installed_version: '1', release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'ok', can_update: false }),
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
    skillRemove: async () => ({ status: 'failed', deleted: [], reason: 'Cannot delete SKILL.md: access denied' }),
  });
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  root.querySelector('[data-action="remove"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="manage-status"]').textContent, /未移除：Cannot delete SKILL\.md/);
  assert.doesNotMatch(root.querySelector('[data-info="manage-status"]').textContent, /已移除/);
  window.close();
});

test('a removal whose refresh read fails reports completion with unconfirmed state, and a later check recovers', async () => {
  let reads = 0;
  const api = {
    skillStatus: async () => {
      reads += 1;
      if (reads === 2) throw new Error('disk busy');
      return reads === 1
        ? { state: 'current', installed_version: '1', release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'ok', can_update: false }
        : { state: 'absent', installed_version: null, release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'not installed', can_update: false };
    },
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
    skillRemove: async () => ({ status: 'removed', deleted: ['SKILL.md'], reason: 'done' }),
    skillUpdate: async () => ({}),
  };
  const { root, window } = setup(api);
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  root.querySelector('[data-action="remove"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="manage-error"]').textContent, /操作已完成，当前状态未确认/);
  assert.equal(root.querySelector('[data-action="remove"]').disabled, true);
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.match(root.querySelector('[data-info="installed"]').textContent, /状态：未安装/);
  assert.equal(root.querySelector('[data-info="manage-error"]').textContent, '');
  window.close();
});
