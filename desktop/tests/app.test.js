import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
const window = new Window();
globalThis.document = window.document;
globalThis.HTMLElement = window.HTMLElement;
globalThis.MutationObserver = window.MutationObserver;
const { createNavigation } = await import('../ui/app.js');

test('late mount is disposed and cannot overwrite or dispose the current page', async () => {
  const root = document.createElement('main'), nav = document.createElement('nav'); document.body.append(nav, root);
  let finish, staleDisposed = 0, currentDisposed = 0;
  const first = { id: 'slow', number: '01', label: 'slow', mount: async holder => {
    await new Promise(resolve => { finish = resolve; }); holder.textContent = 'stale'; return { dispose() { staleDisposed++; } };
  } };
  const second = { id: 'fast', number: '02', label: 'fast', mount: async holder => {
    holder.innerHTML = '<h1>Current page</h1>'; return { dispose() { currentDisposed++; } };
  } };
  const navigation = createNavigation(root, nav, {}, [first, second]);
  const pending = navigation.select(first); await navigation.select(second); finish(); await pending;
  assert.equal(root.textContent, 'Current page'); assert.equal(staleDisposed, 1); assert.equal(currentDisposed, 0);
  assert.equal(document.activeElement, root.querySelector('h1'));
  navigation.dispose(); assert.equal(currentDisposed, 1); root.remove(); nav.remove();
});

test('mount errors are text-only and retry restores the selected page', async () => {
  const root = document.createElement('main'), nav = document.createElement('nav'); document.body.append(nav, root);
  let attempts = 0;
  const page = { id: 'retry', number: '01', label: 'retry', mount: async holder => {
    if (!attempts++) throw new Error('<img src=x onerror=alert(1)>');
    holder.innerHTML = '<h1>Recovered</h1>'; return { dispose() {} };
  } };
  const navigation = createNavigation(root, nav, {}, [page]); await navigation.select(page);
  assert.equal(root.querySelector('img'), null); assert.match(root.textContent, /onerror/);
  root.querySelector('button').click(); await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(root.textContent, 'Recovered'); navigation.dispose(); root.remove(); nav.remove();
});


test('a rejected stale mount is consumed after navigation disposal', async () => {
  const root = document.createElement('main'), nav = document.createElement('nav'); document.body.append(nav, root);
  let reject;
  const page = { id: 'late-error', number: '01', label: 'late-error', mount: () => new Promise((_, fail) => { reject = fail; }) };
  const navigation = createNavigation(root, nav, {}, [page]); const pending = navigation.select(page);
  navigation.dispose(); root.textContent = 'replacement'; reject(new Error('late failure')); await pending;
  assert.equal(root.textContent, 'replacement'); root.remove(); nav.remove();
});
