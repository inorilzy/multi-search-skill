import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { createNavigation } from '../ui/app.js';

function setup() {
  const window = new Window();
  const nav = window.document.createElement('nav');
  const root = window.document.createElement('main');
  window.document.body.append(nav, root);
  return { window, nav, root };
}

const page = (id, mount) => ({ id, label: id, number: '01', mount });
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

test('a stale navigation result cannot replace the current page and is disposed', async () => {
  const { window, nav, root } = setup();
  let release;
  let firstDisposed = false;
  const first = page('first', async view => {
    view.textContent = '最早页面';
    await new Promise(resolve => { release = resolve; });
    return { dispose() { firstDisposed = true; } };
  });
  let secondDisposed = false;
  const second = page('second', async view => {
    view.textContent = '当前页面';
    return { dispose() { secondDisposed = true; } };
  });
  const app = createNavigation(root, nav, async () => ({}), [first, second]);
  const pending = app.select(first);
  await flush();
  await app.select(second);
  release();
  await pending;
  assert.equal(firstDisposed, true, 'the late mount is disposed even though it never became current');
  assert.equal(secondDisposed, false);
  assert.equal(root.textContent, '当前页面', 'the late page cannot overwrite the visible page');
  assert.equal(nav.querySelector('[data-page="second"]').getAttribute('aria-current'), 'page');

  app.dispose();
  assert.equal(secondDisposed, true);
  window.close();
});

test('a transition cancels the previous mount before it resolves', async () => {
  const { window, nav, root } = setup();
  let seenSignal;
  let disposed = false;
  const first = page('first', async (view, api, { signal }) => {
    seenSignal = signal;
    await new Promise(resolve => setTimeout(resolve, 20));
    return { dispose() { disposed = true; } };
  });
  const second = page('second', async view => { view.textContent = 'second'; return { dispose() {} }; });
  const app = createNavigation(root, nav, async () => ({}), [first, second]);
  const pending = app.select(first);
  await app.select(second);
  assert.equal(seenSignal.aborted, true);
  await pending;
  assert.equal(disposed, true);
  assert.equal(root.textContent, 'second');
  window.close();
});

test('a failed mount shows the backend reason and retry remounts the page', async () => {
  const { window, nav, root } = setup();
  let attempts = 0;
  let signal;
  const broken = page('broken', async (view, api, options) => {
    signal = options.signal;
    attempts += 1;
    if (attempts === 1) throw '后端不可用：IPC 已断开';
    view.textContent = '恢复页面';
    return { dispose() {} };
  });
  const app = createNavigation(root, nav, async () => ({}), [broken]);
  await app.select(broken);
  assert.match(root.textContent, /页面加载失败/);
  assert.match(root.textContent, /后端不可用：IPC 已断开/);
  assert.equal(signal.aborted, true, 'partial listeners are released when mount fails');
  root.querySelector('[data-action="retry"]').click();
  await flush();
  assert.equal(attempts, 2);
  assert.equal(root.textContent, '恢复页面');
  app.dispose();
  window.close();
});

test('a missing desktop runtime explains itself without mounting pages', async () => {
  const { window, nav, root } = setup();
  let mounted = false;
  const only = page('only', async () => { mounted = true; });
  const app = createNavigation(root, nav, null, [only]);
  await app.select(only);
  assert.equal(mounted, false);
  assert.match(root.textContent, /桌面应用/);
  window.close();
});
