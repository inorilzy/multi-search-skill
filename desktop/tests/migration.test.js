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
      { provider: 'tavily', action: 'migrate', preview: 'sha256:1a2b3c4d' },
      { provider: 'brave', action: 'conflict', preview: 'sha256:5e6f7a8b' },
      { provider: 'jina', action: 'unsupported', reason: 'not a single-key search provider; left in the legacy file' },
    ],
    migratable: ['tavily', 'brave'],
    skipped: ['jina'],
    // The desktop backend attaches its platform fact after the CLI reports the
    // plan: format compatibility is not executability.
    store_supported: true,
  };
}

test('preview shows masked values, lists skips, and never renders a full key', async () => {
  const { window, root } = setup();
  const api = { migrationPlan: async () => plan() };
  const mounted = await mountMigration(root, api);
  root.querySelector('[data-action="preview"]').click();
  await flush();
  assert.equal(root.querySelector('[data-preview="tavily"]').textContent, 'sha256:1a2b3c4d');
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

test('old CLI missing migrate-legacy reports failure, never migration success', async () => {
  for (const phase of ['preview', 'apply']) {
    const { window, root } = setup();
    const unsupported = async () => { throw new Error("invalid choice: 'migrate-legacy'"); };
    const api = {
      migrationPlan: phase === 'preview' ? unsupported : async () => plan(),
      migrationApply: unsupported,
    };
    const mounted = await mountMigration(root, api);
    try {
      root.querySelector('[data-action="preview"]').click();
      await flush();
      if (phase === 'preview') {
        assert.match(root.querySelector('[data-info="error"]').textContent, /无法预览.*CLI/);
        assert.equal(root.querySelector('[data-action="apply"]'), null);
      } else {
        // A previously obtained preview does not make a rejected apply successful.
        root.querySelector('[data-approve="tavily"]').checked = true;
        root.querySelector('[data-action="apply"]').click();
        await flush();
        assert.match(root.querySelector('[data-info="result"]').textContent, /迁移未完成/);
      }
      assert.doesNotMatch(root.textContent, /迁移完成。|已写入：/);
    } finally {
      mounted.dispose();
      window.close();
    }
  }
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

test('apply shows a loading state and a double click sends exactly one migration', async () => {
  const { window, root } = setup();
  let release;
  const calls = [];
  const api = {
    migrationPlan: async () => plan(),
    migrationApply: (...args) => { calls.push(args); return new Promise(resolve => { release = resolve; }); },
  };
  const mounted = await mountMigration(root, api);
  root.querySelector('[data-action="preview"]').click();
  await flush();
  root.querySelector('[data-approve="tavily"]').checked = true;
  const applyButton = root.querySelector('[data-action="apply"]');
  applyButton.click();
  applyButton.click();
  await flush();
  assert.equal(calls.length, 1, 'a second click while applying must not reach the API');
  assert.equal(applyButton.disabled, true);
  assert.equal(applyButton.getAttribute('aria-busy'), 'true');
  assert.match(applyButton.textContent, /迁移中/);
  assert.equal(root.querySelector('[data-action="preview"]').disabled, true, 'preview cannot replace the plan mid-apply');
  release({ written: ['tavily'], kept: [], unchanged: [], failed: [], not_done: [], complete: true });
  await flush();
  assert.match(root.querySelector('[data-info="result"]').textContent, /迁移完成/);
  assert.equal(applyButton.disabled, true, 'a used plan token needs a fresh preview');
  assert.equal(root.querySelector('[data-action="preview"]').disabled, false);
  applyButton.click();
  await flush();
  assert.equal(calls.length, 1);
  mounted.dispose();
  window.close();
});

test('preview shows a loading state and ignores repeated clicks', async () => {
  const { window, root } = setup();
  let release;
  let previews = 0;
  const api = { migrationPlan: () => { previews += 1; return new Promise(resolve => { release = resolve; }); } };
  const mounted = await mountMigration(root, api);
  const button = root.querySelector('[data-action="preview"]');
  button.click();
  button.click();
  await flush();
  assert.equal(previews, 1);
  assert.equal(button.disabled, true);
  assert.match(button.textContent, /预览中/);
  release(plan());
  await flush();
  assert.equal(button.disabled, false);
  assert.equal(root.querySelector('[data-action="apply"]').disabled, false);
  mounted.dispose();
  window.close();
});

test('apply result warns about plaintext legacy file and wide permissions', async () => {
  const { window, root } = setup();
  const api = {
    migrationPlan: async () => plan(),
    migrationApply: async () => ({
      written: ['tavily'], kept: [], unchanged: [], failed: [], not_done: [], complete: true,
      legacy_file: '/home/synthetic/.search-keys.json',
      legacy_file_has_plaintext: true,
      warnings: ['/home/synthetic/.search-keys.json is readable by other users (mode 0644)'],
    }),
  };
  const mounted = await mountMigration(root, api);
  root.querySelector('[data-action="preview"]').click();
  await flush();
  root.querySelector('[data-approve="tavily"]').checked = true;
  root.querySelector('[data-action="apply"]').click();
  await flush();
  const result = root.querySelector('[data-info="result"]').textContent;
  assert.match(result, /迁移完成/);
  assert.match(result, /旧文件仍含明文 Key：\/home\/synthetic\/\.search-keys\.json/);
  assert.match(result, /readable by other users/);
  mounted.dispose();
  window.close();
});

test('unsupported platform keeps masked previews read-only and issues no write path', async () => {
  const { window, root } = setup();
  const calls = [];
  const api = {
    migrationPlan: async () => ({ ...plan(), store_supported: false, store_unsupported_reason: 'platform_unsupported' }),
    migrationApply: async (...args) => { calls.push(args); return { written: [], kept: [], unchanged: [], failed: [], not_done: [], complete: true }; },
  };
  const mounted = await mountMigration(root, api);
  root.querySelector('[data-action="preview"]').click();
  await flush();
  // 格式分类与掩码预览照常展示，但没有任何批准/应用路径。
  assert.equal(root.querySelector('[data-preview="tavily"]').textContent, 'sha256:1a2b3c4d');
  assert.match(root.querySelector('[data-item="tavily"]').textContent, /可迁移/);
  assert.equal(root.querySelector('[data-approve]'), null, 'no approval checkboxes without write support');
  assert.equal(root.querySelector('[data-choice]'), null, 'no conflict choices without write support');
  assert.match(root.querySelector('[data-info="capability"]').textContent, /Windows 当前用户 DPAPI/);
  assert.match(root.querySelector('[data-info="capability"]').textContent, /当前平台无法执行迁移/);
  const applyButton = root.querySelector('[data-action="apply"]');
  assert.equal(applyButton.disabled, true);
  applyButton.click();
  await flush();
  assert.equal(calls.length, 0, 'no apply request reaches the backend');
  mounted.dispose();
  window.close();
});

test('supported platform keeps the explicit approve-and-apply flow', async () => {
  const { window, root } = setup();
  const calls = [];
  const api = {
    migrationPlan: async () => plan(),
    migrationApply: async (...args) => { calls.push(args); return { written: ['tavily'], kept: [], unchanged: [], failed: [], not_done: [], complete: true }; },
  };
  const mounted = await mountMigration(root, api);
  root.querySelector('[data-action="preview"]').click();
  await flush();
  assert.equal(root.querySelector('[data-info="capability"]'), null);
  assert.notEqual(root.querySelector('[data-approve="tavily"]'), null);
  root.querySelector('[data-approve="tavily"]').checked = true;
  root.querySelector('[data-action="apply"]').click();
  await flush();
  assert.equal(calls.length, 1);
  mounted.dispose();
  window.close();
});
