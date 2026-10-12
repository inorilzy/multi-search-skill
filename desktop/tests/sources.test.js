import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { mountSources } from '../ui/sources.js';

test('sources page mounts one scoped credential panel per allowlisted source', async () => {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  const seen = [];
  const api = {
    credentialStatus: async source => {
      seen.push(source);
      return { store: { state: 'absent', saved_at: null, error: null }, effective_source: 'none', env_overrides_store: false, env_var: '', file_key_count: 0 };
    },
  };
  const mounted = await mountSources(root, api);
  const panels = [...root.querySelectorAll('[data-source-panel]')].map(node => node.getAttribute('data-source-panel'));
  assert.deepEqual(panels, ['baidu', 'brave', 'parallel', 'tavily', 'exa', 'firecrawl', 'serpapi', 'github-repos']);
  assert.deepEqual(seen, panels);
  assert.equal(root.querySelectorAll('[data-status="store"]').length, 8);
  assert.ok(!root.textContent.includes('Jina'), 'Jina is out of scope for 05');
  mounted.dispose();
  window.close();
});
