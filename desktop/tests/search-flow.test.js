import test from 'node:test';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
import { buildFlow, cutReasons, describeFlow, moveSummary, mountSearchFlow } from '../ui/search-flow.js';
import { mountDiagnostics } from '../ui/diagnostics.js';

// One recorded search: two searchers (one fails), fusion, two pages on the scrape chain.
const EVENTS = [
  { event: 'query_plan', t_ms: 0, primary_query: 'rust async', executed_queries: ['rust async', 'tokio runtime'] },
  { event: 'route', t_ms: 5, resolved_route: 'default', active_sources: ['brave', 'tavily', 'exa'], disabled_sources: ['baidu'] },
  { event: 'provider_start', t_ms: 6, source: 'brave' },
  { event: 'provider_start', t_ms: 6, source: 'tavily' },
  { event: 'provider_done', t_ms: 400, source: 'tavily', status: 'error', hit_count: 0, error_count: 1, error_type: 'invalid' },
  { event: 'provider_done', t_ms: 900, source: 'brave', status: 'ok', hit_count: 8, error_count: 0 },
  { event: 'provider_result', t_ms: 900, source: 'exa', status: 'error', hit_count: 0, errors: [{ error_type: 'missing_key', error: 'skipped' }] },
  { event: 'search_stage_done', t_ms: 905, raw_row_count: 8, fused_candidate_count: 6 },
  { event: 'scrape_chain', t_ms: 910, url: 'https://a.example/post', order: ['jina_key', 'jina_anon'] },
  { event: 'scrape_attempt', t_ms: 1300, url: 'https://a.example/post', backend: 'jina_key', status: 'error', elapsed_ms: 390, error: 'http 451' },
  { event: 'scrape_attempt', t_ms: 1700, url: 'https://a.example/post', backend: 'jina_anon', status: 'ok', elapsed_ms: 400, content_length: 4200 },
  { event: 'fetch_source', t_ms: 1701, url: 'https://a.example/post', how: 'scrape', backend: 'jina', content_length: 4200 },
  { event: 'fetch_source', t_ms: 1702, url: 'https://b.example/', how: 'cache_hit', backend: 'content-store', content_length: 900 },
  { event: 'search_response', t_ms: 1800, outcome: 'partial', result_count: 6 },
];

function fakeClock() {
  const clock = { t: 0, frames: [] };
  clock.deps = {
    now: () => clock.t,
    frame: cb => { clock.frames.push(cb); return clock.frames.length; },
    cancelFrame: () => {},
    reducedMotion: () => false,
  };
  clock.tick = ms => { clock.t += ms; const run = clock.frames.splice(0); run.forEach(cb => cb()); };
  return clock;
}

test('the model folds stage events into query, route, searchers, fusion and scrape chain', () => {
  const model = buildFlow(EVENTS);
  assert.equal(model.query, 'rust async');
  assert.deepEqual(model.variants, ['tokio runtime']);
  assert.equal(model.route, 'default');
  assert.deepEqual(model.disabled, ['baidu']);
  assert.equal(model.sources.get('brave').hits, 8);
  assert.equal(model.sources.get('brave').end - model.sources.get('brave').start, 894);
  assert.equal(model.sources.get('tavily').status, 'error');
  assert.equal(model.sources.get('exa').status, 'skipped', 'a source that never started is shown as not run');
  assert.equal(model.sources.get('exa').error, '缺少 Key');
  assert.deepEqual(model.fusion, { t: 905, raw: 8, fused: 6 });
  const page = model.scrapes.get('https://a.example/post');
  assert.deepEqual(page.order, ['jina_key', 'jina_anon']);
  assert.equal(page.attempts.get('jina_key').status, 'error');
  assert.equal(page.final.length, 4200);
  assert.deepEqual(model.scrapes.get('https://b.example/').order, ['content-store']);
  assert.equal(model.outcome, 'partial');
});

test('route and searcher spellings of one source share a row', () => {
  const model = buildFlow([
    { event: 'route', t_ms: 0, resolved_route: 'dev', active_sources: ['github_repos'] },
    { event: 'provider_start', t_ms: 1, source: 'github-repos' },
    { event: 'provider_done', t_ms: 5, source: 'github-repos', status: 'ok', hit_count: 2 },
  ]);
  assert.equal(model.sources.size, 1);
  assert.equal([...model.sources.values()][0].hits, 2);
});

const RERANKED = [
  ...EVENTS.slice(0, 8),
  { event: 'rerank_start', t_ms: 906, model: 'typesafe/jev-1.14', candidate_count: 6 },
  { event: 'rerank', t_ms: 1600, elapsed_ms: 694, mode_requested: 'rrf_model', mode_used: 'rrf_model', model: 'typesafe/jev-1.14', candidate_count: 6, scored_count: 6 },
  { event: 'search_response', t_ms: 1700, outcome: 'success', result_count: 6 },
];

test('model rerank is its own stage between fusion and scrape', () => {
  const window = new Window();
  const host = window.document.createElement('section');
  window.document.body.append(host);
  const clock = fakeClock();
  const flow = mountSearchFlow(host, clock.deps);
  flow.update(RERANKED.slice(0, 9), true);
  const node = () => host.querySelector('.flow-node-rerank');
  assert.equal(node().dataset.lit, 'busy');
  assert.match(node().textContent, /打分中/);
  assert.match(node().textContent, /jev-1\.14/);
  const order = [...host.querySelector('.flow-stage').children].map(el => el.className.split(' ').pop());
  assert.deepEqual(order.filter(name => name.startsWith('flow-node-')), ['flow-node-query', 'flow-node-route', 'flow-node-fusion', 'flow-node-rerank', 'flow-node-scrape']);
  flow.update(RERANKED, false);
  assert.equal(node().dataset.lit, 'on');
  assert.match(node().textContent, /6 个已打分/);
  assert.match(node().textContent, /0\.7 秒/);
  assert.ok(describeFlow(buildFlow(RERANKED)).some(line => /模型重排：typesafe\/jev-1\.14 为 6 个候选打分/.test(line)));
  flow.dispose();
  window.close();
});

test('the rerank comparison lists each candidate before and after, with score and cut-off', () => {
  const moves = [
    { key: 'b', rrf_rank: 3, rank: 1, relevance_score: 0.95, title: 'Best match', url: 'https://b.example/x' },
    { key: 'a', rrf_rank: 1, rank: 2, relevance_score: 0.8, title: 'Was first', url: 'https://a.example/' },
    { key: 'c', rrf_rank: 2, rank: 3, relevance_score: 0.5, title: '<b>c</b>', url: 'https://c.example/' },
    { key: 'd', rrf_rank: 4, rank: 4, relevance_score: null, title: 'Unscored', url: 'https://d.example/' },
  ];
  const events = [...EVENTS.slice(0, 8),
    { event: 'rerank_start', t_ms: 906, model: 'typesafe/jev-1.14', candidate_count: 4 },
    { event: 'rerank', t_ms: 1600, elapsed_ms: 694, mode_used: 'rrf_model', model: 'typesafe/jev-1.14', candidate_count: 4, scored_count: 3, moves },
    { event: 'final_order', t_ms: 1601, keys: ['b', 'a', 'c'], max_results_per_site: 3 }];
  assert.equal(moveSummary(buildFlow(events).rerank.moves), '1 条上升、2 条下降、1 条不变；上升最多的是「Best match」，从第 3 名升到第 1 名。');
  const window = new Window();
  const host = window.document.createElement('section');
  window.document.body.append(host);
  const flow = mountSearchFlow(host, fakeClock().deps);
  flow.update(events, false);
  const block = host.querySelector('.flow-rerank');
  assert.equal(block.hidden, false);
  assert.equal(block.open, true);
  const rows = [...block.querySelectorAll('tbody tr')];
  assert.deepEqual(rows.map(row => row.dataset.move), ['up', 'down', 'down', 'same']);
  assert.deepEqual([...block.querySelectorAll('th')].map(th => th.textContent), ['最终', '重排后', '重排前', '变化', 'Jev 评分', '结果']);
  assert.match(rows[0].textContent, /^113↑ 20\.950Best match/);
  assert.match(rows[3].textContent, /^—4/);
  assert.match(rows[3].textContent, /未打分/);
  assert.equal(rows[3].dataset.dropped, 'true');
  assert.match(rows[3].textContent, /排名在最终 3 条之外/);
  assert.match(block.querySelector('.flow-rerank-cap').textContent, /最终返回 3 条。同一网站最多保留 3 条/);
  assert.equal(block.querySelector('tbody b'), null, 'titles are text, not markup');
  block.open = false;
  block.dispatchEvent(new window.Event('toggle'));
  flow.update(events, false);
  assert.equal(host.querySelector('.flow-rerank').open, false, 'a closed comparison stays closed across redraws');
  flow.dispose();
  window.close();
});

test('a blended rerank shows both normalized parts, the blend and the weight', () => {
  const moves = [
    { key: 'b', rrf_rank: 2, rank: 1, relevance_score: 0.97, model_norm: 1, rrf_norm: 0.6, blended: 0.8, title: 'B', url: 'https://b.example/' },
    { key: 'a', rrf_rank: 1, rank: 2, relevance_score: 0.80, model_norm: 0.2, rrf_norm: 1, blended: 0.6, title: 'A', url: 'https://a.example/' },
  ];
  const events = [...EVENTS.slice(0, 8),
    { event: 'rerank', t_ms: 1000, elapsed_ms: 90, mode_used: 'rrf_model', model: 'typesafe/jev-1.14', candidate_count: 2, scored_count: 2, model_weight: 0.5, moves }];
  const window = new Window();
  const host = window.document.createElement('section');
  window.document.body.append(host);
  const flow = mountSearchFlow(host, fakeClock().deps);
  flow.update(events, false);
  const headers = [...host.querySelectorAll('.flow-rerank th')].map(th => th.textContent);
  assert.deepEqual(headers, ['重排后', '重排前', '变化', 'Jev 评分', 'Jev 归一', 'RRF 归一', '综合分', '结果']);
  assert.match(host.querySelector('tbody tr').textContent, /0\.9701\.000\.600\.800B/);
  assert.match(host.querySelector('.flow-rerank-note').textContent, /综合分 = 0\.50 × Jev 归一 \+ 0\.50 × RRF 归一/);
  assert.match(host.querySelector('.flow-node-rerank').textContent, /Jev 50%/);
  assert.ok(describeFlow(buildFlow(events)).some(line => /按 Jev 50% \+ RRF 50% 综合排序/.test(line)));
  flow.dispose();
  window.close();
});

test('a page pushed out by the per-site cap says which site was full', () => {
  const docs = n => ({ key: `d${n}`, rrf_rank: n, rank: n, relevance_score: 0.9, title: `Doc ${n}`, url: `https://docs.python.org/3.${n}/` });
  const other = n => ({ key: `o${n}`, rrf_rank: n, rank: n, relevance_score: 0.8, title: `Other ${n}`, url: `https://site${n}.example/` });
  const moves = [docs(1), docs(2), docs(3), docs(4), other(5), other(6)];
  const events = [...EVENTS.slice(0, 8),
    { event: 'rerank', t_ms: 1000, elapsed_ms: 90, mode_used: 'rrf_model', model: 'jev', candidate_count: 6, scored_count: 6, model_weight: 0.5, moves: moves.map(m => ({ ...m, model_norm: 1, rrf_norm: 1, blended: 1 })) },
    { event: 'final_order', t_ms: 1001, keys: ['d1', 'd2', 'd3', 'o5', 'o6'], max_results_per_site: 3 }];
  const finalRank = new Map([['d1', 1], ['d2', 2], ['d3', 3], ['o5', 4], ['o6', 5]]);
  const reasons = cutReasons(buildFlow(events).rerank.moves, finalRank, 3);
  assert.equal(reasons.get('d4'), '同站已满：docs.python.org 已有 3 条');
  const window = new Window();
  const host = window.document.createElement('section');
  window.document.body.append(host);
  const flow = mountSearchFlow(host, fakeClock().deps);
  flow.update(events, false);
  const rows = [...host.querySelectorAll('.flow-rerank tbody tr')];
  assert.equal(rows[3].querySelector('.flow-rerank-final').textContent, '—');
  assert.match(rows[3].textContent, /同站已满：docs\.python\.org 已有 3 条/);
  assert.equal(rows[4].querySelector('.flow-rerank-final').textContent, '4', 'the next site moves up into the freed slot');
  assert.match(host.querySelector('.flow-rerank-cap').textContent, /本次有 1 条因为所在网站已满被挤出前 5/);
  flow.dispose();
  window.close();
});

test('a rerank fallback is shown as not applied, with the reason', () => {
  const events = [...EVENTS.slice(0, 8),
    { event: 'rerank', t_ms: 950, elapsed_ms: 40, mode_requested: 'rrf_model', mode_used: 'rrf', fallback_reason: 'missing_key', model: 'typesafe/jev-1.14', candidate_count: 6, scored_count: 0 }];
  const window = new Window();
  const host = window.document.createElement('section');
  window.document.body.append(host);
  const flow = mountSearchFlow(host, fakeClock().deps);
  flow.update(events, false);
  const node = host.querySelector('.flow-node-rerank');
  assert.equal(node.dataset.lit, 'warn');
  assert.match(node.textContent, /未生效/);
  assert.match(node.textContent, /缺少 System One Key/);
  assert.equal(host.querySelector('.flow-rerank').hidden, true, 'no comparison when the model did not reorder');
  flow.dispose();
  window.close();
});

test('a plain RRF run has no rerank stage', () => {
  const window = new Window();
  const host = window.document.createElement('section');
  window.document.body.append(host);
  const flow = mountSearchFlow(host, fakeClock().deps);
  flow.update(EVENTS, false);
  assert.equal(host.querySelector('.flow-node-rerank'), null);
  flow.dispose();
  window.close();
});

test('a clock limit shows the search as it was at that moment', () => {
  const early = buildFlow(EVENTS, 500);
  assert.equal(early.sources.get('brave').status, 'running');
  assert.equal(early.sources.get('tavily').status, 'error');
  assert.equal(early.fusion, null);
  assert.equal(early.scrapes.size, 0);
  assert.equal(early.outcome, null);
});

test('the story names each stage in plain sentences', () => {
  const lines = describeFlow(buildFlow(EVENTS));
  assert.match(lines[0], /搜索词「rust async」.*1 个改写/);
  assert.match(lines[1], /路由 default/);
  assert.match(lines[1], /已停用/);
  assert.match(lines[2], /8 条/);
  assert.match(lines[2], /失败（Key 无效）/);
  assert.match(lines[2], /未运行（缺少 Key）/);
  assert.match(lines[3], /8 条原始结果.*6 个候选/);
  assert.match(lines[4], /2 个网页，成功 2 个（其中 1 个来自本地缓存）/);
  assert.match(lines[5], /部分来源失败，返回 6 条结果，共 1\.8 秒/);
});

test('live mode lights stages, grows running bars between polls and pulses the active wire', () => {
  const window = new Window();
  const host = window.document.createElement('section');
  window.document.body.append(host);
  const clock = fakeClock();
  const flow = mountSearchFlow(host, clock.deps);
  assert.equal(host.hidden, true, 'nothing to show before the first event');

  flow.update(EVENTS.slice(0, 4), true);
  assert.equal(host.hidden, false);
  assert.equal(host.dataset.mode, 'live');
  const brave = () => [...host.querySelectorAll('.flow-source')].find(row => row.textContent.includes('Brave'));
  assert.equal(brave().dataset.state, 'running');
  const before = parseFloat(brave().querySelector('.flow-bar').style.width);
  clock.tick(300);
  const after = parseFloat(brave().querySelector('.flow-bar').style.width);
  assert.ok(after >= before, 'the running bar keeps up with wall time between polls');
  assert.equal(host.querySelector('.flow-wire[data-after="route"]').dataset.flow, 'on');
  assert.equal(host.querySelector('.flow-replay').hidden, true, 'no replay while running');

  flow.update(EVENTS, false);
  assert.equal(host.dataset.mode, 'done');
  assert.equal(brave().dataset.state, 'ok');
  assert.match(brave().textContent, /8 条/);
  assert.equal(host.querySelectorAll('.flow-wire[data-flow="on"]').length, 0);
  assert.match(host.querySelector('.flow-state').textContent, /部分来源失败/);
  const chips = [...host.querySelectorAll('.flow-chip')].map(chip => chip.dataset.state);
  assert.deepEqual(chips, ['error', 'ok', 'ok']);
  assert.equal(host.querySelector('.flow-replay').hidden, false);
  flow.dispose();
  window.close();
});

test('replay walks the recorded clock and ends on the finished diagram', () => {
  const window = new Window();
  const host = window.document.createElement('section');
  window.document.body.append(host);
  const clock = fakeClock();
  const flow = mountSearchFlow(host, clock.deps);
  flow.update(EVENTS, false);
  host.querySelector('.flow-replay').click();
  assert.equal(host.dataset.mode, 'replay');
  assert.equal(host.querySelector('.flow-replay').textContent, '停止回放');
  assert.equal(host.querySelector('.flow-node-fusion').dataset.lit, 'off', 'replay starts from the beginning');
  clock.tick(907);
  assert.equal(host.querySelector('.flow-node-fusion').dataset.lit, 'on');
  assert.equal(host.querySelectorAll('.flow-scrape').length, 0);
  clock.tick(2000);
  assert.equal(host.dataset.mode, 'done');
  assert.equal(host.querySelectorAll('.flow-scrape').length, 2);
  flow.dispose();
  window.close();
});

test('reduced motion never starts a frame loop or a replay animation', () => {
  const window = new Window();
  const host = window.document.createElement('section');
  window.document.body.append(host);
  const clock = fakeClock();
  clock.deps.reducedMotion = () => true;
  const flow = mountSearchFlow(host, clock.deps);
  flow.update(EVENTS.slice(0, 4), true);
  assert.equal(clock.frames.length, 0);
  flow.update(EVENTS, false);
  host.querySelector('.flow-replay').click();
  assert.equal(clock.frames.length, 0);
  assert.equal(host.dataset.mode, 'done');
  flow.dispose();
  window.close();
});

test('provider text is rendered as text, never as markup', () => {
  const window = new Window();
  const host = window.document.createElement('section');
  window.document.body.append(host);
  const flow = mountSearchFlow(host, fakeClock().deps);
  flow.update([
    { event: 'query_plan', t_ms: 0, primary_query: '<img src=x onerror=alert(1)>', executed_queries: [] },
    { event: 'route', t_ms: 1, resolved_route: '<b>r</b>', active_sources: ['<i>s</i>'] },
  ], false);
  assert.equal(host.querySelector('img'), null);
  assert.equal(host.querySelector('b'), null);
  assert.match(host.textContent, /<img src=x/);
  flow.dispose();
  window.close();
});

test('the test search shows the diagram from polled progress and hides it for an old CLI', async () => {
  const window = new Window();
  const root = window.document.createElement('main');
  window.document.body.append(root);
  let polls = 0;
  const api = {
    detect: async () => ({ app: { status: 'ready' }, user: { status: 'ready' }, restart_required: false, execution: { status: 'ready' }, managed: true }),
    start: async () => 7,
    poll: async () => {
      polls += 1;
      return polls === 1
        ? { id: 7, status: 'running', exit_code: null, payload: null, error: '', progress: EVENTS.slice(0, 3) }
        : { id: 7, status: 'partial', exit_code: 0, payload: { outcome: 'partial', results: [], errors: [] }, error: '', progress: EVENTS };
    },
    cancel: async () => ({ status: 'cancelled' }),
  };
  const page = await mountDiagnostics(root, api, { pollInterval: 1 });
  root.querySelector('[data-field="query"]').value = 'rust async';
  root.querySelector('[data-search-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await new Promise(resolve => setTimeout(resolve, 30));
  const flow = root.querySelector('[data-flow]');
  assert.equal(flow.hidden, false);
  assert.equal(flow.dataset.mode, 'done');
  assert.match(flow.textContent, /路由 default/);
  page.dispose();

  const oldRoot = window.document.createElement('main');
  window.document.body.append(oldRoot);
  const old = await mountDiagnostics(oldRoot, { ...api, poll: async () => ({ id: 7, status: 'success', exit_code: 0, payload: { outcome: 'success', results: [], errors: [] }, error: '' }) }, { pollInterval: 1 });
  oldRoot.querySelector('[data-field="query"]').value = 'x';
  oldRoot.querySelector('[data-search-form]').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(oldRoot.querySelector('[data-flow]').hidden, true);
  old.dispose();
  window.close();
});
