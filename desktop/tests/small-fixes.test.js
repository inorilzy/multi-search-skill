import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountInstall } from '../ui/install.js';
import { mountScrape } from '../ui/scrape.js';

const plan = (status, extra = {}) => ({
  status, root: 'C:\\fixture\\cli', bin: 'C:\\fixture\\cli\\bin\\multi-search.exe',
  version: null, reason: '', path_hint: 'PATH 提示', ...extra,
});

const BUILTIN = ['jina', 'exa', 'tavily', 'firecrawl'];
const OPTIONS = BUILTIN.map(name => ({ name, label: name }));

function setup() {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  return { window, root };
}

function settingsView() {
  return {
    config_path: 'C:/test/config.sqlite', path_source: 'user', file_present: true, read_source: 'sqlite',
    route: 'default', timeout: 60, timeout_configured: true, effective_timeout: 60,
    timeout_min: 1, timeout_max: 90, timeout_out_of_range: false, effective_timeouts: {},
    routes: {}, builtin_routes: {}, disabled_sources: [], unknown_disabled_sources: [],
    twitter_cookies_path: null,
    scrape_backends: [...BUILTIN], scrape_backends_invalid: false,
    builtin_scrape_backends: [...BUILTIN],
    scrape_backend_options: OPTIONS.map(option => ({ ...option })),
    active_sources: ['brave'], status: 'ok', message: '',
  };
}

function scrapeApi() {
  return {
    credentialStatus: async source => ({ source, store: { state: 'present', saved_at: null, error: '' } }),
    settingsView: async () => settingsView(),
    scrapeSettingsSave: async input => settingsView({ scrape_backends: input }),
    scrapeMemoryView: async () => ({ available: false, path: null, reason: '', rows: [] }),
  };
}

const chainNames = root => [...root.querySelectorAll('[data-chain-row]')].map(row => row.getAttribute('data-chain-row'));
const handle = (root, name) => root.querySelector(`[data-chain-row="${name}"] .scrape-drag-handle`);
const statusNode = root => root.querySelector('[data-sort-status]');
const press = (window, node, key) => node.dispatchEvent(new window.KeyboardEvent('keydown', { bubbles: true, key }));

test('uninstall stays enabled while the managed CLI has an update available', async () => {
  const { window, root } = setup();
  let plans = 0;
  let uninstalled = 0;
  await mountInstall(root, {
    installPlan: async () => {
      plans += 1;
      return plans === 1
        ? plan('update_available', { version: '0.5.0', current_version: '0.4.0' })
        : plan('installed', { version: '0.4.0' });
    },
    update: async () => { throw new Error('must not run'); },
    uninstall: async () => { uninstalled += 1; return { status: 'uninstalled', steps: [], reason: '' }; },
  });

  const button = root.querySelector('[data-action="uninstall"]');
  assert.equal(button.disabled, false);
  button.click();
  assert.equal(root.querySelector('[data-confirm]').hidden, false);
  root.querySelector('[data-action="uninstall-confirm"]').click();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(uninstalled, 1);
  assert.match(root.querySelector('[data-status="result"]').textContent, /已卸载 CLI/);
  window.close();
});

test('a drag commit still announces when focus does not take effect', async () => {
  const { window, root } = setup();
  await mountScrape(root, scrapeApi());
  // Simulate an environment where focus is refused: activeElement never moves
  // to the re-rendered handle. Committing the sort must not throw on that.
  Object.defineProperty(root.ownerDocument, 'activeElement', { get: () => null, configurable: true });

  press(window, handle(root, 'jina'), 'Enter');
  press(window, handle(root, 'jina'), 'ArrowDown');
  press(window, handle(root, 'jina'), 'Enter');

  assert.deepEqual(chainNames(root), ['exa', 'jina', 'tavily', 'firecrawl']);
  assert.match(statusNode(root).textContent, /jina 已移到第 2 位，尚未保存/);
  window.close();
});
