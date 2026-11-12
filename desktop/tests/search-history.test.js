import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { createHistory, HISTORY_LIMIT } from '../ui/search-history.js';
import { mountDiagnostics } from '../ui/diagnostics.js';

function memoryStorage(initial = {}) {
  const data = { ...initial };
  return {
    data,
    getItem: key => (key in data ? data[key] : null),
    setItem: (key, value) => { data[key] = String(value); },
    removeItem: key => { delete data[key]; },
  };
}

test('history keeps newest first, moves repeats to the front and stays bounded', () => {
  const history = createHistory(memoryStorage());
  history.add({ query: 'a', route: 'default', sources: [], timeout: 15 });
  history.add({ query: 'b', route: 'dev', sources: [], timeout: 15 });
  const list = history.add({ query: 'a', route: 'default', sources: [], timeout: 30 });
  assert.deepEqual(list.map(item => item.query), ['a', 'b']);
  assert.equal(list[0].timeout, 30, 'the repeat keeps its newest options');
  for (let i = 0; i < HISTORY_LIMIT + 3; i += 1) history.add({ query: `q${i}`, route: 'default', sources: [] });
  assert.equal(history.list().length, HISTORY_LIMIT);
  assert.equal(history.list()[0].query, `q${HISTORY_LIMIT + 2}`);
});

test('a broken or missing storage never throws', () => {
  const broken = { getItem: () => '{not json', setItem: () => { throw new Error('full'); }, removeItem: () => { throw new Error('x'); } };
  const history = createHistory(broken);
  assert.deepEqual(history.list(), []);
  assert.doesNotThrow(() => history.add({ query: 'x', route: 'default', sources: [] }));
  assert.deepEqual(createHistory(null).list(), []);
  assert.deepEqual(createHistory(null).clear(), []);
});

const ready = { status: 'ready', path: '/x/multi-search', version: '0.4.1', reason: '' };

async function mountPage(storage, starts) {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  const api = {
    detect: async () => ({ app: ready, user: ready, restart_required: false, execution: ready, managed: false }),
    start: async options => { starts.push(options); return starts.length; },
    poll: async id => ({ id, status: 'success', exit_code: 0, payload: { outcome: 'success', results: [], errors: [] }, error: '', progress: [] }),
    cancel: async () => ({ status: 'cancelled' }),
  };
  const page = await mountDiagnostics(root, api, { pollInterval: 1, storage });
  return { window, root, page };
}

test('a started search is remembered and one tap runs it again with the same options', async () => {
  const storage = memoryStorage();
  const starts = [];
  const { window, root, page } = await mountPage(storage, starts);
  assert.equal(root.querySelector('[data-history]').hidden, true, 'no history yet');

  root.querySelector('[data-field="query"]').value = 'PLC 报警代码';
  root.querySelector('[data-field="route"]').value = 'dev';
  root.querySelector('[data-search-form]').requestSubmit();
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(root.querySelector('[data-history]').hidden, false);
  const chip = root.querySelector('.search-history-run');
  assert.match(chip.textContent, /PLC 报警代码/);
  assert.match(chip.textContent, /dev/);

  root.querySelector('[data-field="query"]').value = '';
  root.querySelector('[data-field="route"]').value = 'default';
  chip.click();
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(starts.length, 2);
  assert.deepEqual(starts[1], starts[0], 'the tap repeats the same query, route, sources and timeout');
  assert.equal(root.querySelectorAll('.search-history-run').length, 1, 'a repeat does not add a second chip');
  page.dispose();

  // History survives a new page (same storage), can be removed one by one, and cleared.
  const again = await mountPage(storage, []);
  assert.equal(again.root.querySelectorAll('.search-history-run').length, 1);
  again.root.querySelector('[data-history-remove="0"]').click();
  assert.equal(again.root.querySelector('[data-history]').hidden, true);
  again.page.dispose();
  window.close();
  again.window.close();
});

test('history text is rendered as text and clear removes everything', async () => {
  const storage = memoryStorage({
    'multi-search.test-search-history': JSON.stringify([{ query: '<img src=x onerror=alert(1)>', route: 'default', sources: [] }, { query: 'b', route: 'default', sources: [] }]),
  });
  const { window, root, page } = await mountPage(storage, []);
  assert.equal(root.querySelector('[data-history] img'), null);
  assert.match(root.querySelector('.search-history-run').textContent, /<img/);
  root.querySelector('[data-action="history-clear"]').click();
  assert.equal(root.querySelector('[data-history]').hidden, true);
  assert.equal(storage.data['multi-search.test-search-history'], undefined);
  page.dispose();
  window.close();
});
