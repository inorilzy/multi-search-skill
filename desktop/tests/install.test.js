import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountInstall } from '../ui/install.js';

function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root };
}

const plan = (status, extra = {}) => ({ status, root: 'C:\\fixture\\cli', bin: 'C:\\fixture\\cli\\bin\\multi-search.exe', version: null, reason: '', path_hint: 'PATH 提示', ...extra });

test('missing bundled CLI resource shows the prerequisite and keeps install disabled', async () => {
  const { window, root } = setup();
  await mountInstall(root, { installPlan: async () => plan('prerequisite_missing', { reason: '安装包缺少内置 CLI 资源，无法安装' }), install: async () => { throw new Error('must not run'); } });
  assert.equal(root.querySelector('[data-status="plan"]').textContent, '缺少安装前提');
  assert.match(root.querySelector('[data-info="reason"]').textContent, /内置 CLI 资源/);
  assert.equal(root.querySelector('[data-action="install"]').disabled, true);
  window.close();
});

test('unknown existing installation is reported as untouched and not installable', async () => {
  const { window, root } = setup();
  await mountInstall(root, { installPlan: async () => plan('unknown_existing', { reason: '安装目录已有非本工具内容，未做任何修改' }), install: async () => { throw new Error('must not run'); } });
  assert.equal(root.querySelector('[data-status="plan"]').textContent, '已有未知安装，未修改');
  assert.equal(root.querySelector('[data-action="install"]').disabled, true);
  window.close();
});

test('ready plan shows target and PATH hint; success shows steps and version', async () => {
  const { window, root } = setup();
  const api = {
    installPlan: async () => plan('ready', { version: '0.4.0' }),
    install: async () => ({ status: 'installed', version: '0.4.0', path_hint: '安装后请将 PATH 加入用户环境', reason: '', steps: [{ name: '验证可执行性', ok: true, detail: 'multi-search 0.4.0' }] }),
  };
  await mountInstall(root, api);
  assert.equal(root.querySelector('[data-action="install"]').disabled, false);
  assert.match(root.querySelector('[data-info="bin"]').textContent, /multi-search\.exe/);
  root.querySelector('[data-action="install"]').click();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(root.querySelector('[data-status="result"]').textContent, '安装成功 v0.4.0');
  assert.match(root.querySelector('[data-steps]').textContent, /验证可执行性/);
  assert.match(root.querySelector('[data-info="path-hint"]').textContent, /PATH/);
  window.close();
});

test('failed install never reports success and shows the actionable reason', async () => {
  const { window, root } = setup();
  const api = {
    installPlan: async () => plan('ready', { version: '0.4.0' }),
    install: async () => ({ status: 'integrity_failed', reason: '产物 SHA-256 校验失败，已拒绝安装', steps: [{ name: '检查安装来源与完整性', ok: false, detail: '产物 SHA-256 校验失败' }] }),
  };
  await mountInstall(root, api);
  root.querySelector('[data-action="install"]').click();
  await new Promise(resolve => setTimeout(resolve, 10));
  const result = root.querySelector('[data-status="result"]').textContent;
  assert.doesNotMatch(result, /成功/);
  assert.equal(result, '完整性校验失败');
  assert.match(root.querySelector('[data-info="reason"]').textContent, /SHA-256/);
  window.close();
});

test('a thrown install request is reported as unconfirmed, not as success', async () => {
  const { window, root } = setup();
  const api = { installPlan: async () => plan('ready'), install: async () => { throw new Error('ipc'); } };
  await mountInstall(root, api);
  root.querySelector('[data-action="install"]').click();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(root.querySelector('[data-status="result"]').textContent, '安装失败');
  assert.match(root.querySelector('[data-info="reason"]').textContent, /未确认安装结果/);
  window.close();
});

test('update is offered only for a newer verified bundle and reports the new version', async () => {
  const { window, root } = setup();
  let updated = 0;
  const api = {
    installPlan: async () => plan('update_available', { version: '0.5.0' }),
    install: async () => { throw new Error('must not run'); },
    update: async () => { updated += 1; return { status: 'installed', version: '0.5.0', path_hint: 'PATH', reason: '', steps: [] }; },
  };
  await mountInstall(root, api);
  assert.equal(root.querySelector('[data-action="install"]').disabled, true);
  assert.equal(root.querySelector('[data-action="update"]').disabled, false);
  root.querySelector('[data-action="update"]').click();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(updated, 1);
  assert.equal(root.querySelector('[data-status="result"]').textContent, '更新成功 v0.5.0');
  window.close();
});

test('uninstall needs an explicit confirmation and states that config and Skills are kept', async () => {
  const { window, root } = setup();
  let uninstalled = 0;
  const api = {
    installPlan: async () => plan('installed', { version: '0.4.0' }),
    install: async () => { throw new Error('must not run'); },
    uninstall: async () => { uninstalled += 1; return { status: 'uninstalled', steps: [], reason: '' }; },
  };
  await mountInstall(root, api);
  assert.equal(root.querySelector('[data-action="uninstall"]').disabled, false);
  const confirm = root.querySelector('[data-confirm]');
  assert.equal(confirm.hidden, true);
  root.querySelector('[data-action="uninstall"]').click();
  assert.equal(confirm.hidden, false);
  assert.match(confirm.textContent, /配置、凭据和 Skill 会保留/);
  root.querySelector('[data-action="uninstall-cancel"]').click();
  assert.equal(confirm.hidden, true);
  assert.equal(uninstalled, 0);
  root.querySelector('[data-action="uninstall"]').click();
  root.querySelector('[data-action="uninstall-confirm"]').click();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(uninstalled, 1);
  assert.match(root.querySelector('[data-status="result"]').textContent, /已卸载 CLI/);
  window.close();
});

test('unverified managed record disables every mutating action and shows the reason', async () => {
  const { window, root } = setup();
  const api = {
    installPlan: async () => plan('unverified', { reason: '已有安装记录无法验证，已阻止覆盖或更新，请先修复或卸载' }),
    install: async () => { throw new Error('must not run'); },
    update: async () => { throw new Error('must not run'); },
    uninstall: async () => { throw new Error('must not run'); },
  };
  await mountInstall(root, api);
  assert.equal(root.querySelector('[data-status="plan"]').textContent, '安装记录无法验证，已阻止修改');
  for (const action of ['install', 'update', 'uninstall']) {
    assert.equal(root.querySelector(`[data-action="${action}"]`).disabled, true, action);
  }
  assert.match(root.querySelector('[data-info="reason"]').textContent, /无法验证/);
  window.close();
});

test('update plan shows current version, target version and the install source', async () => {
  const { window, root } = setup();
  const api = {
    installPlan: async () => plan('update_available', { version: '0.5.0', current_version: '0.4.0', source: 'C:\bundle\src-v2' }),
    install: async () => { throw new Error('must not run'); },
    update: async () => { throw new Error('must not run'); },
    uninstall: async () => { throw new Error('must not run'); },
  };
  await mountInstall(root, api);
  assert.equal(root.querySelector('[data-info="current-version"]').textContent, 'v0.4.0');
  assert.equal(root.querySelector('[data-info="version"]').textContent, 'v0.5.0');
  assert.equal(root.querySelector('[data-info="source"]').textContent, 'C:\bundle\src-v2');
  window.close();
});

test('uninstall with a kept Skill shows the missing CLI dependency and refreshes status to not installed', async () => {
  const { window, root } = setup();
  let plans = 0;
  const api = {
    installPlan: async () => { plans += 1; return plans === 1 ? plan('installed', { version: '0.4.0' }) : plan('not_installed'); },
    install: async () => { throw new Error('must not run'); },
    uninstall: async () => ({
      status: 'uninstalled',
      reason: '',
      steps: [
        { name: '卸载 CLI', ok: true, detail: '0.4.0' },
        { name: '保留的 Skill', ok: false, detail: 'Skill 已保留，但其 CLI 依赖已缺失，请重新安装 CLI 或移除该 Skill' },
      ],
    }),
  };
  await mountInstall(root, api);
  root.querySelector('[data-action="uninstall"]').click();
  root.querySelector('[data-action="uninstall-confirm"]').click();
  await new Promise(resolve => setTimeout(resolve, 10));
  const steps = [...root.querySelectorAll('[data-steps] li')].map(li => li.textContent);
  assert.ok(steps.some(text => text.startsWith('✗ 保留的 Skill') && text.includes('CLI 依赖已缺失')), steps.join('\n'));
  assert.equal(root.querySelector('[data-status="plan"]').textContent, '未安装');
  assert.equal(plans, 2, 'plan must be re-read after uninstall');
  assert.equal(root.querySelector('[data-action="uninstall"]').disabled, true);
  window.close();
});
