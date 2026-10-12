import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountMigration } from '../ui/migration.js';

// Synthetic values only. The full value must never reach the DOM; previews are masked.
const SYNTHETIC_FULL = 'synthetic-tavily-0001';
const TOKEN = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root };
}

function plan() {
  return {
    plan_token: TOKEN,
    items: [
      { provider: 'tavily', action: 'migrate', preview: 'synth…0001' },
      { provider: 'brave', action: 'conflict', preview: 'synth…0002' },
      { provider: 'jina', action: 'unsupported', reason: 'not a single-key search provider; left in the legacy file' },
    ],
    migratable: ['tavily', 'brave'],
    skipped: ['jina'],
  };
}

test('preview shows masked values, lists skips, and never renders a full key', async () => {
  const { window, root } = setup();
  const api = { migrationPlan: async () => plan() };
  const mounted = await mountMigration(root, api);
  root.querySelector('[data-action="preview"]').click();
  await flush();
  assert.ok(root.querySelector('[data-preview="tavily"]').textContent.startsWith('synth'));
  assert.ok(root.querySelector('[data-item="jina"]').textContent.includes('不支持'));
  assert.ok(!root.innerHTML.includes(SYNTHETIC_FULL), 'full key must not appear in the DOM');
  assert.match(root.querySelector('[data-info="summary"]').textContent, /可迁移 2 项；跳过 1 项/);
  mounted.dispose();
  window.close();
});

test('apply requires confirmation and an explicit conflict choice before calling the API', async () => {
  const { window, root } = setup();
  const calls = [];
  const api = {
    migrationPlan: async () => plan(),
    migrationApply: async (...args) => { calls.push(args); return { written: [], kept: [], unchanged: [], failed: [], not_done: [], complete: true }; },
  };
  const mounted = await mountMigration(root, api);
  root.querySelector('[data-action="preview"]').click();
  await flush();
  root.querySelector('[data-approve="tavily"]').checked = true;
  root.querySelector('[data-approve="brave"]').checked = true;
  root.querySelector('[data-action="apply"]').click();
  await flush();
  assert.equal(calls.length, 0, 'conflict without a choice must not reach the API');
  assert.match(root.querySelector('[data-info="result"]').textContent, /请为 brave 选择保留或替换/);
  root.querySelector('[data-choice="brave"]').value = 'keep';
  root.querySelector('[data-action="apply"]').click();
  await flush();
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], TOKEN);
  assert.deepEqual(calls[0][1], ['tavily', 'brave']);
  assert.deepEqual(calls[0][2], { brave: 'keep' });
  mounted.dispose();
  window.close();
});

test('partial failure is reported as incomplete with done and not-done parts', async () => {
  const { window, root } = setup();
  const api = {
    migrationPlan: async () => plan(),
    migrationApply: async () => ({ written: ['tavily'], kept: [], unchanged: [], failed: ['brave'], not_done: ['jina'], complete: false }),
  };
  const mounted = await mountMigration(root, api);
  root.querySelector('[data-action="preview"]').click();
  await flush();
  root.querySelector('[data-approve="tavily"]').checked = true;
  root.querySelector('[data-approve="brave"]').checked = true;
  root.querySelector('[data-choice="brave"]').value = 'replace';
  root.querySelector('[data-action="apply"]').click();
  await flush();
  const text = root.querySelector('[data-info="result"]').textContent;
  assert.match(text, /迁移未全部完成/);
  assert.match(text, /已写入：tavily/);
  assert.match(text, /失败：brave/);
  assert.match(text, /未完成：jina/);
  mounted.dispose();
  window.close();
});
