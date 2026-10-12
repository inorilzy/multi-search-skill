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

test('unconfigured production source shows the prerequisite and keeps install disabled', async () => {
  const { window, root } = setup();
  await mountInstall(root, { installPlan: async () => plan('unconfigured', { reason: '未配置受控发布来源，无法安装' }), install: async () => { throw new Error('must not run'); } });
  assert.equal(root.querySelector('[data-status="plan"]').textContent, '未配置受控发布来源');
  assert.match(root.querySelector('[data-info="reason"]').textContent, /未配置受控发布来源/);
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
