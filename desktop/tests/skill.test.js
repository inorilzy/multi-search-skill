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
  assert.doesNotMatch(root.textContent, /已安装/);
  window.close();
});
