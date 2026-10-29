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

test('a successful update re-reads the target so the new version and available actions replace the old ones', async () => {
  let updated = false;
  const updates = [];
  const api = {
    skillStatus: async () => updated
      ? { state: 'current', installed_version: '2', release_version: '2', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'ok', can_update: false }
      : { state: 'outdated', installed_version: '1', release_version: '2', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'old', can_update: true },
    skillUpdate: async (scope, project, confirm) => { updates.push(confirm); updated = true; return { status: 'updated', verified: true, reason: 'verified', backup: null }; },
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
    skillRemove: async () => ({}),
  };
  const { root, window } = setup(api);
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.match(root.querySelector('[data-info="installed"]').textContent, /已装版本：1；发布版本：2/);
  assert.equal(root.querySelector('[data-action="update"]').disabled, false);
  root.querySelector('[data-action="update"]').click(); await tick(); await tick();
  assert.deepEqual(updates, [false]);
  assert.match(root.querySelector('[data-info="installed"]').textContent, /已装版本：2；发布版本：2/);
  assert.doesNotMatch(root.querySelector('[data-info="installed"]').textContent, /已装版本：1/);
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  assert.equal(root.querySelector('[data-action="remove-plan"]').disabled, false);
  assert.match(root.querySelector('[data-info="manage-status"]').textContent, /已更新并校验/);
  window.close();
});

test('updating a modified skill does not carry the overwrite consent into the next state', async () => {
  let state = 'modified';
  const confirms = [];
  const api = {
    skillStatus: async () => state === 'modified'
      ? { state: 'modified', installed_version: '1', release_version: '1', target: 'C:\\x', modified_files: ['SKILL.md'], unknown_entries: [], reason: 'edited', can_update: true }
      : { state: 'current', installed_version: '1', release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'ok', can_update: false },
    skillUpdate: async (scope, project, confirm) => { confirms.push(confirm); state = 'current'; return { status: 'updated', verified: true, reason: 'verified', backup: 'C:/b' }; },
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  };
  const { root, window } = setup(api);
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-field="confirm-overwrite"]').click();
  root.querySelector('[data-action="update"]').click(); await tick(); await tick();
  assert.deepEqual(confirms, [true]);
  assert.equal(root.querySelector('[data-field="confirm-overwrite"]').checked, false);
  assert.equal(root.querySelector('[data-info="modified"]').textContent, '');
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  window.close();
});

test('a failed update shows the real failure and the re-read state still offers the update', async () => {
  const api = {
    skillStatus: async () => ({ state: 'outdated', installed_version: '1', release_version: '2', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'old', can_update: true }),
    skillUpdate: async () => ({ status: 'failed', reason: 'Update failed verification; the installed skill was kept.', verified: false, backup: null }),
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  };
  const { root, window } = setup(api);
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="manage-status"]').textContent, /未完成更新：Update failed verification/);
  assert.doesNotMatch(root.textContent, /已更新并校验/);
  assert.doesNotMatch(root.querySelector('[data-info="manage-error"]').textContent, /操作已完成/);
  assert.match(root.querySelector('[data-info="installed"]').textContent, /已装版本：1；发布版本：2/);
  assert.equal(root.querySelector('[data-action="update"]').disabled, false);
  window.close();
});

test('an update reported as unverified does not claim completion even if the re-read fails', async () => {
  let reads = 0;
  const api = {
    skillStatus: async () => { reads += 1; if (reads === 2) throw new Error('disk busy'); return { state: 'outdated', installed_version: '1', release_version: '2', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'old', can_update: true }; },
    skillUpdate: async () => ({ status: 'updated', verified: false, reason: 'unverified', backup: null }),
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  };
  const { root, window } = setup(api);
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick(); await tick();
  assert.doesNotMatch(root.querySelector('[data-info="manage-error"]').textContent, /操作已完成/);
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  window.close();
});

test('a read failure after a successful update disables stale update actions and does not show the old version', async () => {
  let reads = 0;
  const api = {
    skillStatus: async () => { reads += 1; if (reads === 2) throw new Error('disk busy'); return { state: 'outdated', installed_version: '1', release_version: '2', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'old', can_update: true }; },
    skillUpdate: async () => ({ status: 'updated', verified: true, reason: 'verified', backup: null }),
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  };
  const { root, window } = setup(api);
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="manage-error"]').textContent, /操作已完成，当前状态未确认/);
  assert.equal(root.querySelector('[data-info="installed"]').textContent, '');
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  assert.equal(root.querySelector('[data-action="remove-plan"]').disabled, true);
  window.close();
});

// 09: a write that succeeded followed by a failed status read. Writes are counted so retries prove they only read.
function writeThenReadFailure({ write, reads, readFails }) {
  let readCount = 0;
  const counts = { install: 0, update: 0, remove: 0, status: 0 };
  const statusFor = (state) => ({ state, installed_version: state === 'absent' ? null : '1', release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'ok', can_update: state === 'outdated' });
  const current = { state: 'outdated' };
  const api = {
    skillPlan: async () => ({ scope: 'global', target: 'C:\\x', files: ['SKILL.md'], status: 'ready', reason: 'ok', can_install: true }),
    skillInstall: async () => { counts.install += 1; current.state = 'current'; return { status: 'installed', target: 'C:\\x', reason: 'verified', verified: true }; },
    skillStatus: async () => {
      counts.status += 1; readCount += 1;
      if (readFails(readCount)) throw new Error('disk busy');
      return statusFor(current.state);
    },
    skillUpdate: async () => { counts.update += 1; current.state = 'current'; return { status: 'updated', verified: true, reason: 'verified', backup: null }; },
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
    skillRemove: async () => { counts.remove += 1; current.state = 'absent'; return { status: 'removed', deleted: ['SKILL.md'], reason: 'done' }; },
  };
  return { api, counts, current, write };
}

test('install success with a failed read says completed but unconfirmed, and a later check recovers both panels', async () => {
  const h = writeThenReadFailure({ readFails: n => n === 1 });
  const { root, window } = setup(h.api);
  root.querySelector('[data-action="preview"]').click(); await tick();
  root.querySelector('[data-action="install"]').click(); await tick(); await tick();
  assert.equal(h.counts.install, 1);
  assert.match(root.querySelector('[data-info="status"]').textContent, /已安装并校验/);
  assert.match(root.querySelector('[data-info="manage-error"]').textContent, /操作已完成，当前状态未确认/);
  assert.equal(root.querySelector('[data-info="installed"]').textContent, '');
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  assert.equal(root.querySelector('[data-action="remove-plan"]').disabled, true);
  // Recovery: the check re-reads and only reads.
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.match(root.querySelector('[data-info="installed"]').textContent, /状态：有可用更新|状态：当前版本|已装版本/);
  assert.equal(root.querySelector('[data-info="manage-error"]').textContent, '');
  assert.equal(h.counts.install, 1, 'retry must not repeat the install');
  assert.equal(root.querySelector('[data-action="remove-plan"]').disabled, false);
  window.close();
});

test('update success with a failed read says completed but unconfirmed, and a later check recovers without repeating the update', async () => {
  const h = writeThenReadFailure({ readFails: n => n === 2 });
  const { root, window } = setup(h.api);
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick(); await tick();
  assert.equal(h.counts.update, 1);
  assert.match(root.querySelector('[data-info="manage-status"]').textContent, /已更新并校验/);
  assert.match(root.querySelector('[data-info="manage-error"]').textContent, /操作已完成，当前状态未确认/);
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  assert.equal(root.querySelector('[data-info="installed"]').textContent, '');
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.match(root.querySelector('[data-info="installed"]').textContent, /状态：当前版本/);
  assert.equal(root.querySelector('[data-info="manage-error"]').textContent, '');
  assert.equal(h.counts.update, 1, 'retry must not repeat the update');
  window.close();
});

test('removal success with a failed read says completed but unconfirmed, and a later check recovers to not-installed', async () => {
  const h = writeThenReadFailure({ readFails: n => n === 2 });
  const { root, window } = setup(h.api);
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  root.querySelector('[data-action="remove"]').click(); await tick(); await tick();
  assert.equal(h.counts.remove, 1);
  assert.match(root.querySelector('[data-info="manage-status"]').textContent, /已移除：SKILL\.md/);
  assert.match(root.querySelector('[data-info="manage-error"]').textContent, /操作已完成，当前状态未确认/);
  assert.equal(root.querySelector('[data-action="remove"]').disabled, true);
  assert.equal(root.querySelector('[data-action="remove-plan"]').disabled, true);
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.match(root.querySelector('[data-info="installed"]').textContent, /状态：未安装/);
  assert.equal(root.querySelector('[data-info="manage-error"]').textContent, '');
  assert.equal(h.counts.remove, 1, 'retry must not repeat the removal');
  window.close();
});

test('a read that keeps failing shows an understandable error and never repeats a write', async () => {
  const h = writeThenReadFailure({ readFails: n => n >= 2 });
  const { root, window } = setup(h.api);
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick(); await tick();
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.equal(h.counts.update, 1);
  assert.match(root.querySelector('[data-info="manage-error"]').textContent, /操作已完成，当前状态未确认/);
  assert.match(root.querySelector('[data-info="manage-error"]').textContent, /检查失败，请重试/);
  assert.equal(root.querySelector('[data-info="installed"]').textContent, '');
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  assert.equal(root.querySelector('[data-action="remove"]').disabled, true);
  window.close();
});

test('an operation failure is reported differently from a successful write whose read failed', async () => {
  const h = writeThenReadFailure({ readFails: n => n === 2 });
  h.api.skillUpdate = async () => ({ status: 'failed', reason: 'Update failed verification; the installed skill was kept.', verified: false, backup: null });
  const { root, window } = setup(h.api);
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="manage-status"]').textContent, /未完成更新：Update failed verification/);
  assert.doesNotMatch(root.querySelector('[data-info="manage-error"]').textContent, /操作已完成/);
  window.close();
});

// 10: races. Each test drives user actions and resolves deferred API responses in a chosen order.
function deferred() { let resolve, reject; const promise = new Promise((res, rej) => { resolve = res; reject = rej; }); return { promise, resolve, reject }; }

test('a double click on install sends exactly one install request', async () => {
  let installs = 0; const gate = deferred();
  const { root, window } = setup({
    skillPlan: async () => ({ scope: 'global', target: 'C:\\x', files: [], status: 'ready', reason: 'ok', can_install: true }),
    skillInstall: async () => { installs += 1; await gate.promise; return { status: 'installed', target: 'C:\\x', reason: 'verified', verified: true }; },
    skillStatus: async () => ({ state: 'current', installed_version: '1', release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'ok', can_update: false }),
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}), skillUpdate: async () => ({}),
  });
  root.querySelector('[data-action="preview"]').click(); await tick();
  const install = root.querySelector('[data-action="install"]');
  install.click(); install.click(); install.click(); await tick();
  assert.equal(installs, 1);
  gate.resolve(); await tick(); await tick();
  assert.equal(installs, 1);
  window.close();
});

test('a double click on update sends exactly one update request', async () => {
  let updates = 0; const gate = deferred();
  const { root, window } = setup({
    skillStatus: async () => ({ state: 'outdated', installed_version: '1', release_version: '2', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'old', can_update: true }),
    skillUpdate: async () => { updates += 1; await gate.promise; return { status: 'updated', verified: true, reason: 'verified', backup: null }; },
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  });
  root.querySelector('[data-action="check"]').click(); await tick();
  const update = root.querySelector('[data-action="update"]');
  update.click(); update.click(); update.click(); await tick();
  assert.equal(updates, 1);
  gate.resolve(); await tick(); await tick();
  assert.equal(updates, 1);
  window.close();
});

test('a double click on remove confirm sends exactly one removal request', async () => {
  let removals = 0; const gate = deferred();
  const { root, window } = setup({
    skillStatus: async () => ({ state: 'current', installed_version: '1', release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'ok', can_update: false }),
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
    skillRemove: async () => { removals += 1; await gate.promise; return { status: 'removed', deleted: ['SKILL.md'], reason: 'done' }; },
    skillUpdate: async () => ({}),
  });
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  const remove = root.querySelector('[data-action="remove"]');
  remove.click(); remove.click(); remove.click(); await tick();
  assert.equal(removals, 1);
  gate.resolve(); await tick(); await tick();
  assert.equal(removals, 1);
  window.close();
});

test('a slow preview for the old scope cannot enable install after the scope changed', async () => {
  const gate = deferred();
  const installs = [];
  const { root, window } = setup({
    skillPlan: async (scope) => {
      if (scope === 'global') { await gate.promise; return { scope: 'global', target: 'C:\\global', files: [], status: 'ready', reason: 'ok', can_install: true }; }
      return { scope: 'project', target: null, files: [], status: 'invalid_scope', reason: 'Select the project directory', can_install: false };
    },
    skillInstall: async (scope) => { installs.push(scope); return { status: 'installed', target: 'C:\\x', reason: 'verified', verified: true }; },
    skillStatus: async () => ({ state: 'absent', installed_version: null, release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'not installed', can_update: false }),
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}), skillUpdate: async () => ({}),
  });
  root.querySelector('[data-action="preview"]').click();
  root.querySelector('input[value="project"]').click();
  root.querySelector('input[value="project"]').click(); // scope change is the user action
  gate.resolve(); await tick(); await tick();
  assert.equal(root.querySelector('[data-action="install"]').disabled, true);
  assert.doesNotMatch(root.querySelector('[data-info="target"]').textContent, /C:\\global/);
  root.querySelector('[data-action="install"]').click(); await tick();
  assert.deepEqual(installs, []);
  window.close();
});

test('a late status response for a previous project does not overwrite the newly selected project', async () => {
  const gates = [];
  const { root, window } = setup({
    skillStatus: async (scope, project) => {
      const gate = deferred(); gates.push({ project, gate });
      await gate.promise;
      return { state: project === 'B' ? 'current' : 'outdated', installed_version: project === 'B' ? '2' : '1', release_version: '2', target: 'C:\\' + project, modified_files: [], unknown_entries: [], reason: project, can_update: project !== 'B' };
    },
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}), skillUpdate: async () => ({}),
  });
  const scopeProject = () => root.querySelector('input[value="project"]').click();
  scopeProject();
  root.querySelector('[data-field="project"]').value = 'A';
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-field="project"]').value = 'B';
  root.querySelector('[data-field="project"]').dispatchEvent(new root.ownerDocument.defaultView.Event('input'));
  root.querySelector('[data-action="check"]').click(); await tick();
  // Resolve B first, then the old A response.
  gates[1].gate.resolve(); await tick();
  gates[0].gate.resolve(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="installed"]').textContent, /状态：当前版本/);
  assert.doesNotMatch(root.querySelector('[data-info="installed"]').textContent, /有可用更新/);
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  window.close();
});

test('a late failure for a previous target does not overwrite the new target success', async () => {
  const gates = [];
  const { root, window } = setup({
    skillStatus: async (scope, project) => {
      const gate = deferred(); gates.push({ project, gate });
      await gate.promise;
      if (project === 'A') throw new Error('late failure A');
      return { state: 'current', installed_version: '2', release_version: '2', target: 'C:\\B', modified_files: [], unknown_entries: [], reason: 'B ok', can_update: false };
    },
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}), skillUpdate: async () => ({}),
  });
  root.querySelector('input[value="project"]').click();
  root.querySelector('[data-field="project"]').value = 'A';
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-field="project"]').value = 'B';
  root.querySelector('[data-field="project"]').dispatchEvent(new root.ownerDocument.defaultView.Event('input'));
  root.querySelector('[data-action="check"]').click(); await tick();
  gates[1].gate.resolve(); await tick(); await tick();
  gates[0].gate.resolve(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="installed"]').textContent, /状态：当前版本/);
  assert.equal(root.querySelector('[data-info="manage-error"]').textContent, '');
  window.close();
});

test('a write that already started is not redirected when the project changes during the request', async () => {
  const gate = deferred();
  const removed = [];
  const { root, window } = setup({
    skillStatus: async () => ({ state: 'current', installed_version: '1', release_version: '1', target: 'C:\\A', modified_files: [], unknown_entries: [], reason: 'ok', can_update: false }),
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
    skillRemove: async (scope, project) => { removed.push(project); await gate.promise; return { status: 'removed', deleted: ['SKILL.md'], reason: 'done' }; },
    skillUpdate: async () => ({}),
  });
  root.querySelector('input[value="project"]').click();
  root.querySelector('[data-field="project"]').value = 'A';
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  root.querySelector('[data-action="remove"]').click(); await tick();
  // Target changes mid-write.
  root.querySelector('[data-field="project"]').value = 'B';
  root.querySelector('[data-field="project"]').dispatchEvent(new root.ownerDocument.defaultView.Event('input'));
  gate.resolve(); await tick(); await tick();
  assert.deepEqual(removed, ['A']);
  window.close();
});

test('a late response after leaving the page does not change the page', async () => {
  let statusCalls = 0; const gate = deferred();
  const api = {
    skillStatus: async () => { statusCalls += 1; await gate.promise; return { state: 'outdated', installed_version: '1', release_version: '2', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'old', can_update: true }; },
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}), skillUpdate: async () => ({}),
  };
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  const page = await mountSkill(root, api);
  root.querySelector('[data-action="check"]').click(); await tick();
  page.dispose(); // app.js calls dispose() when the user navigates away
  gate.resolve(); await tick(); await tick();
  assert.equal(statusCalls, 1);
  assert.equal(root.querySelector('[data-info="installed"]').textContent, '');
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  window.close();
});

// 09: switching the target clears every result shown for the previous target, in both directions.
test('switching global to project and back clears install and manage results from the old target', async () => {
  const { root, window } = setup({
    skillPlan: async () => ({ scope: 'global', target: 'C:\\global', files: ['SKILL.md'], status: 'ready', reason: 'ok', can_install: true }),
    skillInstall: async () => ({ status: 'installed', target: 'C:\\global', reason: 'verified', verified: true }),
    skillStatus: async () => ({ state: 'outdated', installed_version: '1', release_version: '2', target: 'C:\\global', modified_files: [], unknown_entries: [], reason: 'old', can_update: true }),
    skillUpdate: async () => ({ status: 'updated', verified: true, reason: 'verified', backup: 'C:\\backup-global' }),
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  });
  root.querySelector('[data-action="preview"]').click(); await tick();
  root.querySelector('[data-action="install"]').click(); await tick(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="status"]').textContent, /已安装并校验/);
  assert.match(root.querySelector('[data-info="manage-status"]').textContent, /已更新并校验.*C:\\backup-global/);
  root.querySelector('input[value="project"]').click(); await tick();
  assert.equal(root.querySelector('[data-info="status"]').textContent, '');
  assert.equal(root.querySelector('[data-info="target"]').textContent, '');
  assert.equal(root.querySelector('[data-info="manage-status"]').textContent, '');
  assert.equal(root.querySelector('[data-info="manage-error"]').textContent, '');
  assert.equal(root.querySelector('[data-info="installed"]').textContent, '');
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  assert.equal(root.querySelector('[data-action="install"]').disabled, true);
  root.querySelector('input[value="global"]').click(); await tick();
  assert.equal(root.querySelector('[data-info="manage-status"]').textContent, '');
  window.close();
});

test('switching project to global clears the old project failure and backup line', async () => {
  const { root, window } = setup({
    skillStatus: async () => ({ state: 'modified', installed_version: '1', release_version: '2', target: 'C:\\A', modified_files: ['SKILL.md'], unknown_entries: [], reason: 'edited', can_update: true }),
    skillUpdate: async () => ({ status: 'failed', reason: 'Cannot write', verified: false, backup: 'C:\\A-backup' }),
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  });
  root.querySelector('input[value="project"]').click();
  root.querySelector('[data-field="project"]').value = 'A';
  root.querySelector('[data-field="project"]').dispatchEvent(new root.ownerDocument.defaultView.Event('input'));
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="manage-status"]').textContent, /未完成更新：Cannot write.*C:\\A-backup/);
  root.querySelector('input[value="global"]').click(); await tick();
  assert.equal(root.querySelector('[data-info="manage-status"]').textContent, '');
  assert.equal(root.querySelector('[data-info="manage-error"]').textContent, '');
  assert.equal(root.querySelector('[data-info="installed"]').textContent, '');
  window.close();
});

test('a same-target manage refresh keeps the successful update line', async () => {
  let reads = 0;
  const { root, window } = setup({
    skillStatus: async () => { reads += 1; return { state: reads === 1 ? 'outdated' : 'current', installed_version: reads === 1 ? '1' : '2', release_version: '2', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'ok', can_update: reads === 1 }; },
    skillUpdate: async () => ({ status: 'updated', verified: true, reason: 'verified', backup: null }),
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  });
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="manage-status"]').textContent, /已更新并校验/);
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.match(root.querySelector('[data-info="manage-status"]').textContent, /已更新并校验/);
  window.close();
});

test('a slow update that finishes after the project changed does not write its result onto the new project', async () => {
  const gate = deferred();
  const { root, window } = setup({
    skillStatus: async () => ({ state: 'outdated', installed_version: '1', release_version: '2', target: 'C:\\A', modified_files: [], unknown_entries: [], reason: 'old', can_update: true }),
    skillUpdate: async () => { await gate.promise; return { status: 'updated', verified: true, reason: 'verified', backup: 'C:\\A-backup' }; },
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  });
  root.querySelector('input[value="project"]').click();
  root.querySelector('[data-field="project"]').value = 'A';
  root.querySelector('[data-field="project"]').dispatchEvent(new root.ownerDocument.defaultView.Event('input'));
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick();
  root.querySelector('[data-field="project"]').value = 'B';
  root.querySelector('[data-field="project"]').dispatchEvent(new root.ownerDocument.defaultView.Event('input'));
  gate.resolve(); await tick(); await tick();
  assert.equal(root.querySelector('[data-info="manage-status"]').textContent, '');
  assert.equal(root.querySelector('[data-info="installed"]').textContent, '');
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  window.close();
});

// 11: a write that succeeded but whose read-back failed keeps the unconfirmed note only for its own target.
// The follow-up reads on the new target fail on purpose, so a leaked note would show up in the error line.
test('an unconfirmed install note does not carry to a new scope, even when the new target read also fails', async () => {
  const h = writeThenReadFailure({ readFails: n => n <= 2 });
  const { root, window } = setup(h.api);
  root.querySelector('[data-action="preview"]').click(); await tick();
  root.querySelector('[data-action="install"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="manage-error"]').textContent, /操作已完成，当前状态未确认/);
  root.querySelector('input[value="project"]').click(); await tick();
  root.querySelector('[data-action="check"]').click(); await tick();
  const text = root.querySelector('[data-info="manage-error"]').textContent;
  assert.match(text, /检查失败，请重试/);
  assert.doesNotMatch(text, /操作已完成/);
  assert.equal(h.counts.install, 1);
  window.close();
});

test('an unconfirmed update note does not carry to a new project, even when the new target read also fails', async () => {
  const h = writeThenReadFailure({ readFails: n => n === 2 || n === 3 });
  const { root, window } = setup(h.api);
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="manage-error"]').textContent, /操作已完成，当前状态未确认/);
  root.querySelector('input[value="project"]').click(); await tick();
  root.querySelector('[data-field="project"]').value = 'B';
  root.querySelector('[data-field="project"]').dispatchEvent(new root.ownerDocument.defaultView.Event('input'));
  root.querySelector('[data-action="check"]').click(); await tick();
  const text = root.querySelector('[data-info="manage-error"]').textContent;
  assert.match(text, /检查失败，请重试/);
  assert.doesNotMatch(text, /操作已完成/);
  assert.equal(h.counts.update, 1, 'the new target must not trigger another update');
  window.close();
});

test('an unconfirmed removal note does not carry back to global, even when the read there also fails', async () => {
  const h = writeThenReadFailure({ readFails: n => n === 2 || n === 3 });
  const { root, window } = setup(h.api);
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  root.querySelector('[data-action="remove"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="manage-error"]').textContent, /操作已完成，当前状态未确认/);
  root.querySelector('input[value="project"]').click(); await tick();
  root.querySelector('input[value="global"]').click(); await tick();
  root.querySelector('[data-action="check"]').click(); await tick();
  const text = root.querySelector('[data-info="manage-error"]').textContent;
  assert.match(text, /检查失败，请重试/);
  assert.doesNotMatch(text, /操作已完成/);
  assert.equal(h.counts.remove, 1, 'retry must not repeat the removal');
  window.close();
});

// 10: editing the project directory invalidates the previous project's shown state at once, before any check or submit.
function typeProject(root, value) {
  const field = root.querySelector('[data-field="project"]');
  field.value = value;
  field.dispatchEvent(new root.ownerDocument.defaultView.Event('input'));
}

test('editing project A to B clears A results immediately, and a re-check shows only B', async () => {
  const seen = [];
  const { root, window } = setup({
    skillPlan: async (scope, project) => { seen.push(['plan', project]); return { scope, target: `C:\\${project}`, files: ['SKILL.md'], status: 'ready', reason: 'ok', can_install: true }; },
    skillInstall: async (scope, project) => { seen.push(['install', project]); return { status: 'installed', target: `C:\\${project}`, reason: 'verified', verified: true }; },
    skillStatus: async (scope, project) => { seen.push(['status', project]); return { state: project === 'B' ? 'current' : 'outdated', installed_version: '1', release_version: '2', target: `C:\\${project}`, modified_files: [], unknown_entries: [], reason: `at ${project}`, can_update: project !== 'B' }; },
    skillUpdate: async () => ({ status: 'updated', verified: true, reason: 'verified', backup: 'C:\\A-backup' }),
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
    skillRemove: async () => ({ status: 'removed', deleted: ['SKILL.md'], reason: 'done' }),
  });
  root.querySelector('input[value="project"]').click();
  typeProject(root, 'A');
  root.querySelector('[data-action="preview"]').click(); await tick();
  root.querySelector('[data-action="install"]').click(); await tick(); await tick();
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="status"]').textContent, /已安装并校验/);
  assert.match(root.querySelector('[data-info="manage-status"]').textContent, /已更新并校验.*C:\\A-backup/);
  assert.match(root.querySelector('[data-info="installed"]').textContent, /状态：当前版本|有可用更新/);

  typeProject(root, 'B');
  assert.equal(root.querySelector('[data-info="status"]').textContent, '');
  assert.equal(root.querySelector('[data-info="target"]').textContent, '');
  assert.equal(root.querySelector('[data-info="manage-status"]').textContent, '');
  assert.equal(root.querySelector('[data-info="installed"]').textContent, '');
  assert.equal(root.querySelector('[data-info="managed-target"]').textContent, '');
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  assert.equal(root.querySelector('[data-action="remove-plan"]').disabled, true);
  assert.equal(root.querySelector('[data-action="install"]').disabled, true);

  root.querySelector('[data-action="check"]').click(); await tick();
  assert.match(root.querySelector('[data-info="installed"]').textContent, /at B/);
  assert.doesNotMatch(root.textContent, /at A|已更新并校验|C:\\A-backup/);
  assert.equal(seen.filter(c => c[0] === 'status').at(-1)[1], 'B');
  window.close();
});

test('clearing the directory or leaving it incomplete never reuses A state or allows acting on A', async () => {
  const writes = [];
  const { root, window } = setup({
    skillPlan: async (scope, project) => ({ scope, target: project ? `C:\\${project}` : null, files: [], status: project ? 'ready' : 'invalid_scope', reason: project ? 'ok' : 'Select the project directory', can_install: !!project }),
    skillInstall: async (scope, project) => { writes.push(['install', project]); return { status: 'installed', target: 'C:\\A', reason: 'verified', verified: true }; },
    skillStatus: async (scope, project) => ({ state: 'outdated', installed_version: '1', release_version: '2', target: `C:\\${project}`, modified_files: [], unknown_entries: [], reason: 'old', can_update: true }),
    skillUpdate: async (scope, project) => { writes.push(['update', project]); return { status: 'updated', verified: true, reason: 'verified', backup: null }; },
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
    skillRemove: async (scope, project) => { writes.push(['remove', project]); return { status: 'removed', deleted: ['SKILL.md'], reason: 'done' }; },
  });
  root.querySelector('input[value="project"]').click();
  typeProject(root, 'A');
  root.querySelector('[data-action="preview"]').click(); await tick();
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.equal(root.querySelector('[data-action="install"]').disabled, false);
  assert.equal(root.querySelector('[data-action="update"]').disabled, false);

  for (const value of ['', '   ', 'C:\\bad\\\\']) {
    typeProject(root, value);
    assert.equal(root.querySelector('[data-info="status"]').textContent, '', `status kept for "${value}"`);
    assert.equal(root.querySelector('[data-info="target"]').textContent, '', `target kept for "${value}"`);
    assert.equal(root.querySelector('[data-info="installed"]').textContent, '', `installed kept for "${value}"`);
    assert.equal(root.querySelector('[data-info="manage-status"]').textContent, '');
    assert.equal(root.querySelector('[data-action="install"]').disabled, true);
    assert.equal(root.querySelector('[data-action="update"]').disabled, true);
    assert.equal(root.querySelector('[data-action="remove-plan"]').disabled, true);
    // Acting without a fresh preview or check is refused and never reaches the backend with A.
    root.querySelector('[data-action="install"]').click(); await tick();
    root.querySelector('[data-action="remove"]').click(); await tick();
    root.querySelector('[data-action="update"]').click(); await tick();
  }
  assert.deepEqual(writes, []);
  window.close();
});

test('a valid empty-to-new directory is re-checked and shows the real result for that directory only', async () => {
  const { root, window } = setup({
    skillPlan: async (scope, project) => ({ scope, target: `C:\\${project}`, files: ['SKILL.md'], status: 'ready', reason: 'ok', can_install: true }),
    skillInstall: async () => ({ status: 'installed', target: 'C:\\C', reason: 'verified', verified: true }),
    skillStatus: async (scope, project) => ({ state: 'current', installed_version: '1', release_version: '1', target: `C:\\${project}`, modified_files: [], unknown_entries: [], reason: `dir ${project}`, can_update: false }),
    skillUpdate: async () => ({}), skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  });
  root.querySelector('input[value="project"]').click();
  typeProject(root, 'A');
  root.querySelector('[data-action="check"]').click(); await tick();
  typeProject(root, '');
  typeProject(root, 'C');
  assert.equal(root.querySelector('[data-info="installed"]').textContent, '');
  root.querySelector('[data-action="preview"]').click(); await tick();
  assert.match(root.querySelector('[data-info="target"]').textContent, /C:\\C/);
  assert.doesNotMatch(root.textContent, /dir A/);
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.match(root.querySelector('[data-info="installed"]').textContent, /dir C/);
  assert.match(root.querySelector('[data-info="managed-target"]').textContent, /C:\\C/);
  window.close();
});

// 12: a removal preview or overwrite approval given for one target never authorizes a return to it.
function typeProjectValue(root, value) {
  const field = root.querySelector('[data-field="project"]');
  field.value = value;
  field.dispatchEvent(new root.ownerDocument.defaultView.Event('input'));
}

test('A to B and back to A does not revive a removal preview or its confirm button, and a bypassed confirm writes nothing', async () => {
  const removed = [];
  const { root, window } = setup({
    skillStatus: async (scope, project) => ({ state: 'current', installed_version: '1', release_version: '1', target: `C:\\${project}`, modified_files: [], unknown_entries: [], reason: 'ok', can_update: false }),
    skillRemovePlan: async (scope, project) => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: `plan ${project}` }),
    skillRemove: async (scope, project) => { removed.push(project); return { status: 'removed', deleted: ['SKILL.md'], reason: 'done' }; },
    skillUpdate: async () => ({}),
  });
  root.querySelector('input[value="project"]').click();
  typeProjectValue(root, 'A');
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  assert.equal(root.querySelector('[data-action="remove"]').disabled, false);

  typeProjectValue(root, 'B');
  typeProjectValue(root, 'A');
  assert.equal(root.querySelector('[data-action="remove"]').disabled, true);
  assert.doesNotMatch(root.textContent, /plan A/);
  // Bypass the disabled button and fire the old confirm handler directly.
  root.querySelector('[data-action="remove"]').click(); await tick(); await tick();
  assert.deepEqual(removed, []);

  // Fresh check and preview, then the explicit confirm, writes for A only.
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.equal(root.querySelector('[data-action="remove"]').disabled, true);
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  root.querySelector('[data-action="remove"]').click(); await tick(); await tick();
  assert.deepEqual(removed, ['A']);
  window.close();
});

test('switching scope global to project and back drops a removal approval and its preview', async () => {
  const removed = [];
  const { root, window } = setup({
    skillStatus: async () => ({ state: 'current', installed_version: '1', release_version: '1', target: 'C:\\g', modified_files: [], unknown_entries: [], reason: 'ok', can_update: false }),
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'global plan' }),
    skillRemove: async (scope) => { removed.push(scope); return { status: 'removed', deleted: ['SKILL.md'], reason: 'done' }; },
    skillUpdate: async () => ({}),
  });
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  root.querySelector('input[value="project"]').click(); await tick();
  root.querySelector('input[value="global"]').click(); await tick();
  assert.equal(root.querySelector('[data-action="remove"]').disabled, true);
  assert.doesNotMatch(root.querySelector('[data-info="manage-plan"]').textContent, /global plan/);
  root.querySelector('[data-action="remove"]').click(); await tick();
  assert.deepEqual(removed, []);
  window.close();
});

test('overwrite consent given for A is cleared on A to B to A, and an update then needs a fresh consent', async () => {
  const confirms = [];
  const { root, window } = setup({
    skillStatus: async (scope, project) => ({ state: 'modified', installed_version: '1', release_version: '2', target: `C:\\${project}`, modified_files: ['SKILL.md'], unknown_entries: [], reason: 'edited', can_update: true }),
    skillUpdate: async (scope, project, confirm) => { confirms.push([project, confirm]); return { status: 'updated', verified: true, reason: 'verified', backup: 'C:\\bk' }; },
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  });
  root.querySelector('input[value="project"]').click();
  typeProjectValue(root, 'A');
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-field="confirm-overwrite"]').click();
  assert.equal(root.querySelector('[data-field="confirm-overwrite"]').checked, true);

  typeProjectValue(root, 'B');
  typeProjectValue(root, 'A');
  assert.equal(root.querySelector('[data-field="confirm-overwrite"]').checked, false);
  assert.equal(root.querySelector('[data-action="update"]').disabled, true);
  root.querySelector('[data-action="update"]').click(); await tick();
  assert.deepEqual(confirms, []);

  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick(); await tick();
  assert.deepEqual(confirms, [['A', false]], 'without fresh consent the backend is told not to overwrite');
  window.close();
});

test('global to project and back also drops overwrite consent', async () => {
  const confirms = [];
  const { root, window } = setup({
    skillStatus: async () => ({ state: 'modified', installed_version: '1', release_version: '2', target: 'C:\\g', modified_files: ['SKILL.md'], unknown_entries: [], reason: 'edited', can_update: true }),
    skillUpdate: async (scope, project, confirm) => { confirms.push(confirm); return { status: 'updated', verified: true, reason: 'verified', backup: null }; },
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  });
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-field="confirm-overwrite"]').click();
  root.querySelector('input[value="project"]').click(); await tick();
  root.querySelector('input[value="global"]').click(); await tick();
  assert.equal(root.querySelector('[data-field="confirm-overwrite"]').checked, false);
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="update"]').click(); await tick(); await tick();
  assert.deepEqual(confirms, [false]);
  window.close();
});

// 13: a response that arrives after the user left the page or moved to another target must not touch
// the old page. Each test gates one request, disposes the page, then releases the response.
test('a late install response after leaving the page does not paint the old page or start a re-read', async () => {
  const gate = deferred();
  let statusCalls = 0;
  const api = {
    skillPlan: async () => ({ scope: 'global', target: 'C:\\x', files: ['SKILL.md'], status: 'ready', reason: 'ok', can_install: true }),
    skillInstall: async () => { await gate.promise; return { status: 'installed', target: 'C:\\x', reason: 'verified', verified: true }; },
    skillStatus: async () => { statusCalls += 1; return { state: 'current', installed_version: '1', release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'ok', can_update: false }; },
    skillUpdate: async () => ({}), skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  };
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  const page = await mountSkill(root, api);
  root.querySelector('[data-action="preview"]').click(); await tick();
  root.querySelector('[data-action="install"]').click(); await tick();
  page.dispose();
  // What the page showed when it was left is the last word: a late response must not rewrite it.
  const statusBefore = root.querySelector('[data-info="status"]').textContent;
  const targetBefore = root.querySelector('[data-info="target"]').textContent;
  gate.resolve(); await tick(); await tick();
  assert.equal(root.querySelector('[data-info="status"]').textContent, statusBefore);
  assert.doesNotMatch(statusBefore, /已安装/);
  assert.equal(root.querySelector('[data-info="target"]').textContent, targetBefore);
  assert.equal(statusCalls, 0, 'a disposed page must not re-read the target');
  window.close();
});

test('a late update response after leaving the page does not paint the backup line or re-read', async () => {
  const gate = deferred();
  let statusCalls = 0;
  const api = {
    skillStatus: async () => { statusCalls += 1; return { state: 'outdated', installed_version: '1', release_version: '2', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'old', can_update: true }; },
    skillUpdate: async () => { await gate.promise; return { status: 'updated', verified: true, reason: 'verified', backup: 'C:\\x-backup' }; },
    skillPlan: async () => ({}), skillInstall: async () => ({}), skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  };
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  const page = await mountSkill(root, api);
  root.querySelector('[data-action="check"]').click(); await tick();
  const before = statusCalls;
  root.querySelector('[data-action="update"]').click(); await tick();
  page.dispose();
  const statusBefore = root.querySelector('[data-info="manage-status"]').textContent;
  gate.resolve(); await tick(); await tick();
  assert.equal(root.querySelector('[data-info="manage-status"]').textContent, statusBefore);
  assert.doesNotMatch(statusBefore, /已更新并校验|备份/);
  assert.equal(statusCalls, before, 'a disposed page must not re-read the target after the write');
  window.close();
});

test('a late removal response after leaving the page does not paint the old page or re-read', async () => {
  const gate = deferred();
  let statusCalls = 0;
  const api = {
    skillStatus: async () => { statusCalls += 1; return { state: 'current', installed_version: '1', release_version: '1', target: 'C:\\x', modified_files: [], unknown_entries: [], reason: 'ok', can_update: false }; },
    skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
    skillRemove: async () => { await gate.promise; return { status: 'removed', deleted: ['SKILL.md'], reason: 'done' }; },
    skillPlan: async () => ({}), skillInstall: async () => ({}), skillUpdate: async () => ({}),
  };
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  const page = await mountSkill(root, api);
  root.querySelector('[data-action="check"]').click(); await tick();
  const before = statusCalls;
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  root.querySelector('[data-action="remove"]').click(); await tick();
  page.dispose();
  const statusBefore = root.querySelector('[data-info="manage-status"]').textContent;
  gate.resolve(); await tick(); await tick();
  assert.equal(root.querySelector('[data-info="manage-status"]').textContent, statusBefore);
  assert.doesNotMatch(statusBefore, /已移除/);
  assert.equal(statusCalls, before, 'a disposed page must not re-read the target after the removal');
  window.close();
});

test('a late failure after leaving the page writes no error onto the old page, for install, update and removal', async () => {
  const okStatus = { state: 'modified', installed_version: '1', release_version: '2', target: 'C:\\x', modified_files: ['SKILL.md'], unknown_entries: [], reason: 'edited', can_update: true };
  const run = async (action, infoName, write) => {
    const gate = deferred();
    const window = new Window();
    const root = window.document.createElement('main');
    window.document.body.append(root);
    const page = await mountSkill(root, {
      skillPlan: async () => ({ scope: 'global', target: 'C:\\x', files: ['SKILL.md'], status: 'ready', reason: 'ok', can_install: true }),
      skillStatus: async () => okStatus,
      skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
      skillInstall: async () => { await gate.promise; return { status: 'failed', reason: 'nope' }; },
      skillUpdate: async () => { await gate.promise; return { status: 'updated', verified: true, reason: 'ok', backup: null }; },
      skillRemove: async () => { await gate.promise; return { status: 'removed', deleted: ['SKILL.md'], reason: 'done' }; },
      [write]: async () => { await gate.promise; throw new Error('late backend failure'); },
    });
    root.querySelector('[data-action="preview"]').click(); await tick();
    root.querySelector('[data-action="check"]').click(); await tick();
    root.querySelector('[data-action="remove-plan"]').click(); await tick();
    root.querySelector(`[data-action="${action}"]`).click(); await tick();
    page.dispose();
    const node = root.querySelector(`[data-info="${infoName}"]`);
    const before = node.textContent;
    gate.reject(new Error('late backend failure')); await tick(); await tick();
    assert.equal(node.textContent, before, `${action} kept its error line`);
    assert.doesNotMatch(node.textContent, /late backend failure/);
    window.close();
  };
  await run('install', 'error', 'skillInstall');
  await run('update', 'manage-error', 'skillUpdate');
  await run('remove', 'manage-error', 'skillRemove');
});

test('a superseded check that fails late leaves the newer same-target result and buttons untouched', async () => {
  const gates = [];
  const api = {
    skillStatus: async () => {
      const gate = deferred(); gates.push(gate); await gate.promise;
      if (gates.length === 1) throw new Error('superseded read failure');
      return { state: 'outdated', installed_version: '1', release_version: '2', target: 'C:\\x', modified_files: ['SKILL.md'], unknown_entries: [], reason: 'second read', can_update: true };
    },
    skillPlan: async () => ({}), skillInstall: async () => ({}), skillUpdate: async () => ({}),
    skillRemovePlan: async () => ({}), skillRemove: async () => ({}),
  };
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  await mountSkill(root, api);
  root.querySelector('[data-action="check"]').click();
  root.querySelector('[data-action="check"]').click(); await tick();
  gates[1].resolve(); await tick(); await tick();
  assert.match(root.querySelector('[data-info="installed"]').textContent, /second read/);
  assert.equal(root.querySelector('[data-action="update"]').disabled, false);
  gates[0].reject(new Error('superseded read failure')); await tick(); await tick();
  assert.equal(root.querySelector('[data-info="manage-error"]').textContent, '', 'a superseded read adds no failure note');
  assert.match(root.querySelector('[data-info="installed"]').textContent, /second read/);
  assert.equal(root.querySelector('[data-action="update"]').disabled, false, 'the newer result keeps its actions');
  window.close();
});

test('a late removal preview for the previous target cannot re-enable removal on the new target', async () => {
  const gates = [];
  const typeProject = value => {
    const field = root.querySelector('[data-field="project"]');
    field.value = value;
    field.dispatchEvent(new root.ownerDocument.defaultView.Event('input'));
  };
  const api = {
    skillStatus: async (scope, project) => ({ state: 'current', installed_version: '1', release_version: '1', target: `C:\\${project}`, modified_files: [], unknown_entries: [], reason: `at ${project}`, can_update: false }),
    skillRemovePlan: async (scope, project) => {
      const gate = deferred(); gates.push({ project, gate }); await gate.promise;
      return { can_remove: true, will_delete: [`C:\\${project}\\SKILL.md`], will_keep: [], reason: `plan ${project}` };
    },
    skillPlan: async () => ({}), skillInstall: async () => ({}), skillUpdate: async () => ({}), skillRemove: async () => ({}),
  };
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  await mountSkill(root, api);
  root.querySelector('input[value="project"]').click();
  typeProject('A');
  root.querySelector('[data-action="check"]').click(); await tick();
  root.querySelector('[data-action="remove-plan"]').click(); await tick();
  typeProject('B');
  root.querySelector('[data-action="check"]').click(); await tick();
  assert.match(root.querySelector('[data-info="installed"]').textContent, /at B/);
  gates[0].gate.resolve(); await tick(); await tick();
  assert.equal(root.querySelector('[data-action="remove"]').disabled, true, 'the old plan must not arm removal for the new target');
  assert.doesNotMatch(root.querySelector('[data-info="manage-plan"]').textContent, /plan A/);
  assert.match(root.querySelector('[data-info="installed"]').textContent, /at B/);
  window.close();
});

test('a late write response after leaving the page keeps the old page locked instead of re-enabling its controls', async () => {
  const run = async write => {
    const gate = deferred();
    const api = {
      skillStatus: async () => ({ state: 'modified', installed_version: '1', release_version: '2', target: 'C:\\x', modified_files: ['SKILL.md'], unknown_entries: [], reason: 'edited', can_update: true }),
      skillRemovePlan: async () => ({ can_remove: true, will_delete: ['SKILL.md'], will_keep: [], reason: 'ours' }),
      skillPlan: async () => ({}), skillInstall: async () => ({}), skillUpdate: async () => ({}), skillRemove: async () => ({}),
      [write]: async () => { await gate.promise; return { status: 'updated', verified: true, reason: 'ok', backup: null, deleted: ['SKILL.md'], status2: 'removed' }; },
    };
    const window = new Window();
    const root = window.document.createElement('main');
    window.document.body.append(root);
    const page = await mountSkill(root, api);
    root.querySelector('[data-action="check"]').click(); await tick();
    if (write === 'skillRemove') root.querySelector('[data-action="remove-plan"]').click();
    await tick();
    root.querySelector(`[data-action="${write === 'skillRemove' ? 'remove' : 'update'}"]`).click(); await tick();
    page.dispose();
    gate.resolve(); await tick(); await tick();
    assert.equal(root.querySelector('[data-action="check"]').disabled, true, `${write} left the check control locked`);
    assert.equal(root.querySelector('input[value="global"]').disabled, true, `${write} left the scope radios locked`);
    window.close();
  };
  await run('skillUpdate');
  await run('skillRemove');
});
