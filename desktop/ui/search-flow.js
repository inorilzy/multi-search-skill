// Search flow diagram for the test search: query → route → searchers → fusion → scrape.
// The model is built only from `ExecutionStatus.progress` events (the CLI's `@@progress` stream),
// so the same renderer draws a live search and replays a finished one on its recorded clock.
// Every provider-supplied string is set with textContent; nothing here uses innerHTML for data.
import { canonicalSource, sourceLabel } from './catalog.js';

const SCRAPE_LABELS = {
  jina_key: 'Jina Key', jina_anon: 'Jina 匿名', jina: 'Jina', exa: 'Exa', tavily: 'Tavily',
  firecrawl_key: 'Firecrawl Key', firecrawl_anon: 'Firecrawl 匿名', firecrawl: 'Firecrawl',
  twitter: 'Twitter', 'content-store': '本地缓存',
};
const SOURCE_STATUS = {
  waiting: '等待', running: '搜索中', ok: '成功', empty: '无结果', partial: '部分失败',
  error: '失败', skipped: '未运行',
};
const ATTEMPT_STATUS = { ok: '成功', error: '失败', skipped: '跳过', blocked: '被拦截', trying: '尝试中', waiting: '未轮到' };
// Error kinds from the CLI (support/models.py ERROR_KIND_*), in the words the rest of the app uses.
const ERROR_KIND = {
  missing_key: '缺少 Key', invalid: 'Key 无效', transient_invalid: 'Key 暂时无效', quota_exhausted: '额度用尽',
  rate_limit: '被限流', timeout: '超时', network: '网络错误', target: '目标网站错误', credential_unavailable: '凭据不可读',
};
export const errorLabel = kind => ERROR_KIND[kind] || String(kind);
const OUTCOME = { success: '搜索成功', empty: '没有结果', partial: '部分来源失败', failed: '全部来源失败' };
// A replay never takes longer than this, however slow the real search was.
const REPLAY_MAX_MS = 6000;

const num = value => (Number.isFinite(value) ? value : null);
const seconds = ms => `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} 秒`;
export const scrapeLabel = name => SCRAPE_LABELS[name] || String(name);
function host(url) {
  try { return new URL(url).host || url; } catch { return String(url); }
}
function chars(n) {
  if (!Number.isFinite(n)) return '';
  return n >= 10_000 ? `${(n / 1000).toFixed(0)}k 字` : n >= 1000 ? `${(n / 1000).toFixed(1)}k 字` : `${n} 字`;
}

/**
 * Fold progress events (already in arrival order) up to `clock` ms into a view model.
 * @param {any[]} events @param {number} [clock] events with a later `t_ms` are ignored (replay)
 */
export function buildFlow(events, clock = Infinity) {
  const model = {
    query: '', variants: [], route: null, routeSources: [], disabled: [],
    sources: new Map(), fusion: null, rerank: null, scrapes: new Map(), finalKeys: null, perSite: null,
    outcome: null, resultCount: null, endMs: null, lastMs: 0,
  };
  // Route events use canonical names (github_repos) and searcher events the CLI spelling
  // (github-repos); one key per source keeps them on the same row.
  const source = raw => {
    const name = canonicalSource(raw) || raw;
    if (!model.sources.has(name)) model.sources.set(name, { name, status: 'waiting', start: null, end: null, hits: null, error: '' });
    return model.sources.get(name);
  };
  const scrape = url => {
    if (!model.scrapes.has(url)) model.scrapes.set(url, { url, order: [], attempts: new Map(), final: null, start: null });
    return model.scrapes.get(url);
  };
  for (const event of Array.isArray(events) ? events : []) {
    if (!event || typeof event !== 'object') continue;
    const t = num(event.t_ms) ?? model.lastMs;
    if (t > clock) break;
    model.lastMs = Math.max(model.lastMs, t);
    switch (event.event) {
      case 'query_plan': {
        model.query = String(event.primary_query ?? '');
        const all = Array.isArray(event.executed_queries) ? event.executed_queries.map(String) : [];
        model.variants = all.filter(item => item !== model.query);
        break;
      }
      case 'route':
        model.route = String(event.resolved_route ?? event.requested_route ?? '');
        model.routeSources = Array.isArray(event.active_sources) ? event.active_sources.map(String) : [];
        model.disabled = Array.isArray(event.disabled_sources) ? event.disabled_sources.map(String) : [];
        for (const name of model.routeSources) source(name);
        model.routeSources = [...new Set(model.routeSources.map(name => canonicalSource(name) || name))];
        break;
      case 'provider_start': {
        const row = source(String(event.source));
        if (row.start === null) row.start = t;
        if (row.end === null) row.status = 'running';
        break;
      }
      case 'provider_done': {
        // With query variants a source runs once per query; keep its first start and last end.
        const row = source(String(event.source));
        row.end = t;
        if (row.start === null) row.start = Math.max(0, t - (num(event.elapsed_ms) ?? 0));
        row.status = String(event.status || 'ok');
        row.hits = (row.hits ?? 0) + (num(event.hit_count) ?? 0);
        if (event.error_type) row.error = errorLabel(String(event.error_type));
        break;
      }
      case 'provider_result': {
        // Final per-source verdict. A source that never started (missing key, credential error)
        // only appears here, with no elapsed time.
        const row = source(String(event.source));
        if (row.start === null && row.end === null) {
          row.status = 'skipped';
          row.end = row.start = t;
        } else {
          row.status = String(event.status || row.status);
        }
        const first = Array.isArray(event.errors) ? event.errors[0] : null;
        if (first) row.error = first.error_type ? errorLabel(String(first.error_type)) : String(first.error || row.error);
        break;
      }
      case 'search_stage_done':
        model.fusion = { t, raw: num(event.raw_row_count), fused: num(event.fused_candidate_count) };
        break;
      case 'rerank_start':
        model.rerank = { start: t, t: null, model: String(event.model ?? ''), candidates: num(event.candidate_count),
          scored: null, used: false, fallback: '' };
        break;
      case 'rerank': {
        const prev = model.rerank || { start: null, model: '', candidates: null };
        model.rerank = {
          start: prev.start ?? Math.max(0, t - (num(event.elapsed_ms) ?? 0)), t,
          model: String(event.model ?? prev.model ?? ''),
          candidates: num(event.candidate_count) ?? prev.candidates,
          scored: num(event.scored_count),
          used: event.mode_used === 'rrf_model',
          fallback: event.fallback_reason ? String(event.fallback_reason) : '',
          moves: Array.isArray(event.moves) ? event.moves.filter(m => m && typeof m === 'object').map(m => ({
            key: m.key == null ? '' : String(m.key), before: num(m.rrf_rank), after: num(m.rank),
            score: num(m.relevance_score), title: m.title ? String(m.title) : '', url: m.url ? String(m.url) : '',
            modelNorm: num(m.model_norm), rrfNorm: num(m.rrf_norm), blended: num(m.blended),
          })) : [],
          weight: num(event.model_weight),
        };
        break;
      }
      case 'final_order':
        model.finalKeys = Array.isArray(event.keys) ? event.keys.map(String) : null;
        model.perSite = num(event.max_results_per_site);
        break;
      case 'scrape_chain': {
        const row = scrape(String(event.url));
        row.order = Array.isArray(event.order) ? event.order.map(String) : row.order;
        if (row.start === null) row.start = t;
        break;
      }
      case 'scrape_attempt': {
        const row = scrape(String(event.url));
        if (row.start === null) row.start = t;
        const backend = String(event.backend);
        if (!row.order.includes(backend)) row.order.push(backend);
        row.attempts.set(backend, {
          status: String(event.status || 'error'), ms: num(event.elapsed_ms),
          length: num(event.content_length), error: event.error ? String(event.error) : '',
        });
        break;
      }
      case 'fetch_source': {
        const url = String(event.url ?? '');
        // The chain logs the normalised URL; fall back to a new row when it differs.
        const row = model.scrapes.get(url) || scrape(url);
        if (row.start === null) row.start = t;
        row.final = {
          how: String(event.how || ''), backend: event.backend ? String(event.backend) : '',
          length: num(event.content_length), error: event.error ? String(event.error) : '',
        };
        if (row.final.how === 'cache_hit' && !row.order.length) row.order = ['content-store'];
        break;
      }
      case 'search_response':
        model.outcome = String(event.outcome || '');
        model.resultCount = num(event.result_count);
        model.endMs = t;
        break;
      default:
        break;
    }
  }
  return model;
}

/** Narrative of one search, as plain sentences. @param {ReturnType<typeof buildFlow>} model */
export function describeFlow(model) {
  const lines = [];
  if (model.query) {
    lines.push(model.variants.length
      ? `搜索词「${model.query}」，另外扩展了 ${model.variants.length} 个改写：${model.variants.map(v => `「${v}」`).join('、')}。`
      : `搜索词「${model.query}」。`);
  }
  if (model.route !== null) {
    const names = model.routeSources.map(sourceLabel).join('、') || '没有可用的搜索源';
    const off = model.disabled.length ? `；${model.disabled.map(sourceLabel).join('、')} 已停用` : '';
    lines.push(`使用路由 ${model.route}，同时查询 ${names}${off}。`);
  }
  const rows = [...model.sources.values()];
  const done = rows.filter(row => row.end !== null && row.status !== 'running');
  if (done.length) {
    const parts = done.map(row => {
      const label = sourceLabel(row.name);
      if (row.status === 'skipped') return `${label} 未运行${row.error ? `（${row.error}）` : ''}`;
      const time = row.start !== null ? `，${seconds(row.end - row.start)}` : '';
      if (row.status === 'error') return `${label} 失败${row.error ? `（${row.error}）` : ''}${time}`;
      return `${label} ${row.hits ?? 0} 条${time}`;
    });
    lines.push(`搜索器：${parts.join('；')}。`);
  }
  if (model.fusion) {
    const raw = model.fusion.raw ?? '?';
    const fused = model.fusion.fused ?? '?';
    lines.push(`融合排序：${raw} 条原始结果去重合并为 ${fused} 个候选。`);
  }
  if (model.rerank && model.rerank.t !== null) {
    const r = model.rerank;
    const who = r.model ? ` ${r.model}` : '';
    lines.push(r.used
      ? `模型重排：${who.trim() || '模型'} 为 ${r.scored ?? r.candidates ?? '?'} 个候选打分，${r.weight !== null && r.weight !== undefined ? `按 Jev ${Math.round(r.weight * 100)}% + RRF ${100 - Math.round(r.weight * 100)}% 综合排序` : '重新排序'}，用时 ${seconds(r.t - (r.start ?? r.t))}。${moveSummary(r.moves)}`
      : `模型重排：${who.trim() || '模型'} 未生效${r.fallback ? `（${rerankReason(r.fallback)}）` : ''}，保留融合顺序。`);
  }
  const pages = [...model.scrapes.values()];
  if (pages.length) {
    const ok = pages.filter(page => page.final && !page.final.error).length;
    const cached = pages.filter(page => page.final?.how === 'cache_hit').length;
    lines.push(`抓取正文：${pages.length} 个网页，成功 ${ok} 个${cached ? `（其中 ${cached} 个来自本地缓存）` : ''}。`);
  }
  if (model.outcome) {
    const count = model.resultCount !== null ? `，返回 ${model.resultCount} 条结果` : '';
    lines.push(`${OUTCOME[model.outcome] || model.outcome}${count}，共 ${seconds(model.endMs ?? model.lastMs)}。`);
  }
  return lines;
}

/** How many candidates moved, and the biggest jump, in one sentence. */
function siteOf(url) {
  try { return new URL(url).hostname.toLowerCase().replace(/^www\./, ''); } catch { return String(url || ''); }
}

/** Why a candidate is missing from the final list: its site was full, or it simply ranked too low. */
export function cutReasons(moves, finalRank, perSite) {
  const reasons = new Map();
  const counts = new Map();
  const lastFinal = Math.max(0, ...finalRank.values());
  const bySlot = [...moves].sort((a, b) => a.after - b.after);
  for (const move of bySlot) {
    const site = siteOf(move.url);
    if (finalRank.has(move.key)) { counts.set(site, (counts.get(site) || 0) + 1); continue; }
    const used = counts.get(site) || 0;
    if (perSite !== null && used >= perSite && move.after <= lastFinal) {
      reasons.set(move.key, `同站已满：${site} 已有 ${used} 条`);
    } else if (perSite !== null && used >= perSite) {
      reasons.set(move.key, `同站已满且排名靠后：${site} 已有 ${used} 条`);
    } else {
      reasons.set(move.key, `排名在最终 ${finalRank.size} 条之外`);
    }
  }
  return reasons;
}

export function moveSummary(moves) {
  const known = (moves || []).filter(m => m.before !== null && m.after !== null);
  if (!known.length) return '';
  const up = known.filter(m => m.after < m.before);
  const down = known.filter(m => m.after > m.before);
  if (!up.length && !down.length) return '顺序没有变化。';
  const top = [...up].sort((a, b) => (b.before - b.after) - (a.before - a.after))[0];
  const best = top ? `；上升最多的是「${top.title || top.url}」，从第 ${top.before} 名升到第 ${top.after} 名` : '';
  return `${up.length} 条上升、${down.length} 条下降、${known.length - up.length - down.length} 条不变${best}。`;
}

const RERANK_REASON = {
  missing_key: '缺少 System One Key', timeout: '超时', rate_limit: '被限流', auth: 'Key 无效',
  invalid_response: '响应无法解析', unavailable: '服务不可用',
};
export const rerankReason = reason => RERANK_REASON[reason] || String(reason);

function attemptState(page, backend, index) {
  const attempt = page.attempts.get(backend);
  if (attempt) return attempt.status;
  if (page.final) return page.final.how === 'cache_hit' && backend === 'content-store' ? 'ok' : 'waiting';
  // The first backend in the chain without a result yet is the one being tried right now.
  const firstOpen = page.order.findIndex(name => !page.attempts.has(name));
  return index === firstOpen ? 'trying' : 'waiting';
}

/**
 * Mount the diagram inside `container`.
 * @param {any} container @param {{ now?: () => number, frame?: (cb: () => void) => any, cancelFrame?: (id: any) => void, reducedMotion?: () => boolean }} [deps]
 */
export function mountSearchFlow(container, deps = {}) {
  const doc = container.ownerDocument;
  const view = doc.defaultView;
  const now = deps.now || (() => (view?.performance?.now?.() ?? Date.now()));
  const frame = deps.frame || (cb => (view?.requestAnimationFrame ? view.requestAnimationFrame(cb) : setTimeout(cb, 16)));
  const cancelFrame = deps.cancelFrame || (id => (view?.cancelAnimationFrame ? view.cancelAnimationFrame(id) : clearTimeout(id)));
  const reducedMotion = deps.reducedMotion
    || (() => Boolean(view?.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches));
  const el = (tag, className, text) => {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  container.replaceChildren();
  container.hidden = true;
  const head = el('div', 'flow-head');
  const title = el('h3', '', '这次搜索是怎么走的');
  const state = el('span', 'flow-state');
  state.setAttribute('aria-live', 'polite');
  const replayButton = el('button', 'flow-replay', '回放');
  replayButton.type = 'button';
  replayButton.hidden = true;
  head.append(title, state, replayButton);
  const stage = el('div', 'flow-stage');
  const rerankBlock = el('details', 'flow-rerank');
  const scrapeBlock = el('div', 'flow-scrapes');
  const story = el('ol', 'flow-story');
  container.append(head, stage, rerankBlock, scrapeBlock, story);
  // The comparison stays open once the user opens it, across redraws of the same search.
  let rerankOpen = true;
  rerankBlock.addEventListener('toggle', () => { rerankOpen = rerankBlock.open; });

  let events = [];
  let running = false;
  // Live clock: the newest event time plus the wall time since it arrived, so bars keep growing
  // between polls instead of jumping once per poll.
  let liveBase = 0, liveAt = 0;
  let replay = null; // { startedAt, speed }
  let raf = null;
  let disposed = false;

  function clock() {
    if (replay) return (now() - replay.startedAt) * replay.speed;
    if (running) return liveBase + (now() - liveAt);
    return Infinity;
  }

  function node(kind, label, value, extra = '') {
    const box = el('div', `flow-node flow-node-${kind}`);
    box.append(el('span', 'flow-node-label', label), el('strong', 'flow-node-value', value));
    if (extra) box.append(el('span', 'flow-node-extra', extra));
    return box;
  }

  function renderStage(model, t) {
    stage.replaceChildren();
    const queryNode = node('query', '搜索词', model.query || '…', model.variants.length ? `另有 ${model.variants.length} 个改写` : '');
    queryNode.dataset.lit = model.query ? 'on' : 'off';
    const routeNode = node('route', '路由', model.route ?? '…', model.route !== null ? `${model.routeSources.length} 个搜索源` : '');
    routeNode.dataset.lit = model.route !== null ? 'on' : 'off';

    const list = el('ol', 'flow-sources');
    list.setAttribute('aria-label', '搜索器');
    const rows = [...model.sources.values()];
    const searchEnd = model.fusion?.t ?? null;
    // Shared time axis for the waterfall: the search stage so far, or the whole stage once fused.
    const span = Math.max(1, searchEnd ?? Math.max(...rows.map(row => row.end ?? (Number.isFinite(t) ? t : model.lastMs)), model.lastMs));
    for (const row of rows) {
      const item = el('li', 'flow-source');
      const live = row.status === 'running' && row.end === null;
      item.dataset.state = live ? 'running' : row.status;
      const dot = el('span', 'flow-dot');
      dot.setAttribute('aria-hidden', 'true');
      const name = el('span', 'flow-source-name', sourceLabel(row.name));
      const track = el('span', 'flow-track');
      track.setAttribute('aria-hidden', 'true');
      const bar = el('span', 'flow-bar');
      if (row.start !== null) {
        const end = row.end ?? (Number.isFinite(t) ? t : model.lastMs);
        const left = Math.min(100, (row.start / span) * 100);
        const width = Math.max(row.status === 'skipped' ? 0 : 1.5, Math.min(100 - left, ((end - row.start) / span) * 100));
        bar.style.left = `${left.toFixed(2)}%`;
        bar.style.width = `${width.toFixed(2)}%`;
      } else {
        bar.style.width = '0%';
      }
      track.append(bar);
      let detail;
      if (live) detail = row.start !== null && Number.isFinite(t) ? `${SOURCE_STATUS.running} ${seconds(Math.max(0, t - row.start))}` : SOURCE_STATUS.running;
      else if (row.status === 'waiting') detail = SOURCE_STATUS.waiting;
      else if (row.status === 'skipped' || row.status === 'error') detail = `${SOURCE_STATUS[row.status]}${row.error ? ` · ${row.error}` : ''}`;
      else detail = `${row.hits ?? 0} 条 · ${seconds((row.end ?? 0) - (row.start ?? 0))}`;
      item.append(dot, name, track, el('span', 'flow-source-detail', detail));
      list.append(item);
    }
    if (!rows.length) list.append(el('li', 'flow-source flow-source-empty', model.route === null ? '等待路由' : '没有可用的搜索源'));

    const sourcesBox = el('div', 'flow-column flow-column-sources');
    sourcesBox.append(el('span', 'flow-node-label', '搜索器'), list);
    sourcesBox.dataset.lit = rows.some(row => row.status !== 'waiting') ? 'on' : 'off';

    const fusionNode = node('fusion', '融合排序',
      model.fusion ? `${model.fusion.fused ?? '?'} 个候选` : '…',
      model.fusion ? `来自 ${model.fusion.raw ?? '?'} 条结果` : '');
    fusionNode.dataset.lit = model.fusion ? 'on' : 'off';

    // Model rerank is its own stage only when the run asked for it; a plain RRF run skips it.
    let rerankNode = null;
    if (model.rerank) {
      const r = model.rerank;
      const done = r.t !== null;
      const value = !done ? '打分中…' : r.used ? `${r.scored ?? r.candidates ?? '?'} 个已打分` : '未生效';
      const extra = !done
        ? (r.model || '')
        : r.used ? `${r.model ? `${r.model} · ` : ''}${r.weight !== null && r.weight !== undefined ? `Jev ${Math.round(r.weight * 100)}% · ` : ''}${seconds(r.t - (r.start ?? r.t))}` : (r.fallback ? rerankReason(r.fallback) : '保留融合顺序');
      rerankNode = node('rerank', '模型重排', value, extra);
      rerankNode.dataset.lit = done ? (r.used ? 'on' : 'warn') : 'busy';
      if (r.model) rerankNode.title = r.model;
    }

    const pages = [...model.scrapes.values()];
    const fetched = pages.filter(page => page.final && !page.final.error).length;
    const scrapeNode = node('scrape', '抓取正文', pages.length ? `${fetched} / ${pages.length}` : '…', pages.length ? '个网页成功' : '');
    scrapeNode.dataset.lit = pages.length ? 'on' : 'off';

    const wireNames = rerankNode ? ['query', 'route', 'sources', 'fusion', 'rerank'] : ['query', 'route', 'sources', 'fusion'];
    const wires = wireNames.map(name => {
      const wire = el('span', 'flow-wire');
      wire.setAttribute('aria-hidden', 'true');
      wire.dataset.after = name;
      return wire;
    });
    // A wire carries the travelling pulse while the stage after it is still working.
    const active = !model.outcome && running;
    wires[0].dataset.flow = active && model.route === null ? 'on' : 'off';
    wires[1].dataset.flow = active && model.route !== null && !model.fusion ? 'on' : 'off';
    wires[2].dataset.flow = active && rows.length && !model.fusion && rows.some(row => row.end === null) ? 'on' : 'off';
    const reranking = Boolean(model.rerank && model.rerank.t === null);
    wires[3].dataset.flow = active && model.fusion !== null && (rerankNode ? !model.rerank || reranking : true) ? 'on' : 'off';
    if (rerankNode) {
      wires[4].dataset.flow = active && model.rerank?.t != null ? 'on' : 'off';
      stage.dataset.steps = '6';
      stage.append(queryNode, wires[0], routeNode, wires[1], sourcesBox, wires[2], fusionNode, wires[3], rerankNode, wires[4], scrapeNode);
    } else {
      stage.dataset.steps = '5';
      stage.append(queryNode, wires[0], routeNode, wires[1], sourcesBox, wires[2], fusionNode, wires[3], scrapeNode);
    }
  }

  function renderRerank(model) {
    const r = model.rerank;
    const moves = r && r.t !== null && r.used ? r.moves.filter(m => m.after !== null) : [];
    rerankBlock.hidden = moves.length === 0;
    if (!moves.length) { rerankBlock.replaceChildren(); return; }
    const summary = el('summary', '', `重排前后对比：${moveSummary(moves).replace(/。$/, '') || '顺序没有变化'}`);
    const table = el('table', 'flow-rerank-table');
    const head = el('tr');
    const blended = moves.some(move => move.blended !== null);
    const finalRank = model.finalKeys ? new Map(model.finalKeys.map((key, index) => [key, index + 1])) : null;
    const labels = [...(finalRank ? ['最终'] : []), '重排后', '重排前', '变化', 'Jev 评分',
      ...(blended ? ['Jev 归一', 'RRF 归一', '综合分'] : []), '结果'];
    for (const label of labels) head.append(el('th', '', label));
    const thead = el('thead'); thead.append(head);
    const body = el('tbody');
    const kept = finalRank;
    const cut = finalRank ? cutReasons(moves, finalRank, model.perSite) : new Map();
    for (const move of moves) {
      const row = el('tr');
      const delta = move.before === null ? null : move.before - move.after;
      row.dataset.move = delta === null ? 'new' : delta > 0 ? 'up' : delta < 0 ? 'down' : 'same';
      if (kept && !kept.has(move.key)) row.dataset.dropped = 'true';
      const change = delta === null ? '—' : delta > 0 ? `↑ ${delta}` : delta < 0 ? `↓ ${-delta}` : '不变';
      const changeCell = el('td', 'flow-rerank-change', change);
      changeCell.setAttribute('aria-label', delta === null ? '无重排前名次' : delta > 0 ? `上升 ${delta} 名` : delta < 0 ? `下降 ${-delta} 名` : '名次不变');
      const titleCell = el('td', 'flow-rerank-title');
      const name = el('span', '', move.title || host(move.url));
      name.title = move.url;
      titleCell.append(name, el('small', '', host(move.url)));
      if (kept && !kept.has(move.key)) titleCell.append(el('small', 'flow-rerank-cut', cut.get(move.key) || '未进入最终 15 条'));
      if (finalRank) {
        const place = finalRank.get(move.key);
        const cell = el('td', 'flow-rerank-rank flow-rerank-final', place === undefined ? '—' : String(place));
        if (place !== undefined && place !== move.after) cell.title = `重排后第 ${move.after}，因同站上限调整为最终第 ${place}`;
        row.append(cell);
      }
      row.append(
        el('td', 'flow-rerank-rank flow-rerank-after', String(move.after)),
        el('td', 'flow-rerank-rank flow-rerank-before', move.before === null ? '—' : String(move.before)),
        changeCell,
        el('td', 'flow-rerank-score', move.score === null ? '未打分' : move.score.toFixed(3)),
      );
      if (blended) {
        const cell = value => el('td', 'flow-rerank-score', value === null ? '—' : value.toFixed(2));
        row.append(cell(move.modelNorm), cell(move.rrfNorm), el('td', 'flow-rerank-score flow-rerank-blend', move.blended === null ? '—' : move.blended.toFixed(3)));
      }
      row.append(titleCell);
      body.append(row);
    }
    table.append(thead, body);
    const w = r.weight;
    const note = el('p', 'flow-rerank-note', blended && w !== null
      ? `综合分 = ${w.toFixed(2)} × Jev 归一 + ${(1 - w).toFixed(2)} × RRF 归一。两边的分数先各自按本次候选的最高、最低分缩放到 0–1，再加权，所以数值大的一方不会天然占优。「重排前」是多源融合（RRF）的名次，「现在」按综合分排序。最终返回前还会限制同一网站的条数。`
      : '「重排前」是多源融合（RRF）的名次，「现在」是 Jev 按相关性评分重新排序后的名次。最终返回前还会限制同一网站的条数。');
    const children = [summary, note];
    if (finalRank) {
      const dropped = moves.filter(move => !finalRank.has(move.key));
      const capped = dropped.filter(move => cut.get(move.key)?.startsWith('同站'));
      const limit = model.perSite;
      const parts = [`最终返回 ${finalRank.size} 条。`];
      if (limit !== null) parts.push(limit >= 15 ? '本次没有限制同一网站的条数。' : `同一网站最多保留 ${limit} 条，超出的页面排到其他网站之后，其他网站候选不够时才补回。`);
      if (capped.length) parts.push(`本次有 ${capped.length} 条因为所在网站已满被挤出前 ${finalRank.size}。`);
      if (dropped.length > capped.length) parts.push(`另有 ${dropped.length - capped.length} 条综合排名在前 ${finalRank.size} 之外。`);
      parts.push('上限可在「05 搜索设置」里调整。');
      children.push(el('p', 'flow-rerank-note flow-rerank-cap', parts.join('')));
    }
    rerankBlock.replaceChildren(...children, table);
    rerankBlock.open = rerankOpen;
  }

  function renderScrapes(model) {
    scrapeBlock.replaceChildren();
    const pages = [...model.scrapes.values()];
    scrapeBlock.hidden = pages.length === 0;
    if (!pages.length) return;
    scrapeBlock.append(el('h4', '', '抓取链'));
    const list = el('ol', 'flow-scrape-list');
    for (const page of pages) {
      const item = el('li', 'flow-scrape');
      const done = page.final !== null;
      item.dataset.state = done ? (page.final.error ? 'error' : 'ok') : 'running';
      const name = el('span', 'flow-scrape-host', host(page.url));
      name.title = page.url;
      const chain = el('span', 'flow-chain');
      page.order.forEach((backend, index) => {
        const status = attemptState(page, backend, index);
        const chip = el('span', 'flow-chip', scrapeLabel(backend));
        chip.dataset.state = status;
        const attempt = page.attempts.get(backend);
        chip.title = [ATTEMPT_STATUS[status] || status, attempt?.ms != null ? seconds(attempt.ms) : '', attempt?.error || ''].filter(Boolean).join(' · ');
        chain.append(chip);
      });
      let result;
      if (!done) result = '抓取中';
      else if (page.final.error) result = '未取得正文';
      else if (page.final.how === 'cache_hit') result = `缓存 · ${chars(page.final.length)}`;
      else if (page.final.how === 'search_provider_body') result = `搜索结果自带 · ${chars(page.final.length)}`;
      else result = chars(page.final.length) || '已取得';
      item.append(name, chain, el('span', 'flow-scrape-result', result));
      list.append(item);
    }
    scrapeBlock.append(list);
  }

  function renderStory(model) {
    story.replaceChildren();
    for (const line of describeFlow(model)) story.append(el('li', '', line));
  }

  function draw() {
    raf = null;
    if (disposed) return;
    const total = buildFlow(events).endMs;
    // A replay that reached the end becomes the finished diagram in this same frame.
    if (replay && (total === null || clock() >= total)) replay = null;
    const t = clock();
    const model = buildFlow(events, t);
    if (replay) state.textContent = `回放中 · ${seconds(Math.min(t, total ?? t))}`;
    else if (running) state.textContent = `进行中 · ${seconds(Math.max(0, t))}`;
    else state.textContent = model.outcome ? `${OUTCOME[model.outcome] || model.outcome} · ${seconds(model.endMs ?? model.lastMs)}` : '已结束';
    container.dataset.mode = replay ? 'replay' : running ? 'live' : 'done';
    renderStage(model, t);
    renderRerank(model);
    renderScrapes(model);
    renderStory(model);
    replayButton.hidden = running || !events.length;
    replayButton.textContent = replay ? '停止回放' : '回放';
    // Reduced motion: no frame loop; a live search still redraws on every poll.
    if ((replay || running) && !reducedMotion()) raf = frame(draw);
  }

  function schedule() {
    if (raf !== null) cancelFrame(raf);
    raf = null;
    draw();
  }

  replayButton.addEventListener('click', () => {
    if (replay) { replay = null; schedule(); return; }
    const total = buildFlow(events).endMs ?? buildFlow(events).lastMs;
    // Reduced motion: no replay animation; the finished diagram stays as it is.
    if (reducedMotion() || !total) { schedule(); return; }
    replay = { startedAt: now(), speed: Math.max(1, total / REPLAY_MAX_MS) };
    schedule();
  });

  return {
    /** @param {any[]} next all events so far @param {boolean} isRunning */
    update(next, isRunning) {
      if (disposed) return;
      const list = Array.isArray(next) ? next : [];
      if (list.length > events.length || isRunning !== running) {
        const latest = list.length ? num(list[list.length - 1]?.t_ms) ?? 0 : 0;
        if (list.length > events.length) { liveBase = latest; liveAt = now(); }
      }
      events = list;
      running = Boolean(isRunning);
      if (running) replay = null;
      container.hidden = events.length === 0;
      if (container.hidden) { if (raf !== null) cancelFrame(raf); raf = null; return; }
      schedule();
    },
    reset() {
      events = []; running = false; replay = null; rerankOpen = true;
      if (raf !== null) cancelFrame(raf);
      raf = null;
      container.hidden = true;
    },
    dispose() {
      disposed = true;
      if (raf !== null) cancelFrame(raf);
      raf = null;
    },
  };
}
