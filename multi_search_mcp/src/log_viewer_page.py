"""Static page for ``logs serve``: HTML shell, stylesheet and renderer.

Log content (queries, titles, page text) is untrusted: the script builds DOM
nodes and only ever assigns it through ``textContent``; links are emitted only
for http(s) URLs. Served under a CSP without inline script or style.
"""

HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Multi-Search 搜索记录</title>
<link rel="stylesheet" href="/app.css">
<script src="/app.js" defer></script>
</head>
<body>
<aside class="sidebar">
  <div class="sidebar-head">
    <h1>搜索记录</h1>
    <button type="button" id="refresh">刷新</button>
  </div>
  <input id="filter" type="search" placeholder="按查询词或路由筛选" aria-label="筛选搜索记录">
  <p id="source" class="muted small"></p>
  <ol id="runs" class="runs"></ol>
</aside>
<main id="detail" class="detail" tabindex="-1">
  <p class="empty">从左侧选择一次搜索查看详情。</p>
</main>
</body>
</html>
"""

STYLE = r"""
:root {
  --paper: #eef1f4;
  --sheet: #fbfcfd;
  --ink: #1c2430;
  --muted: #5d6877;
  --line: #d3d9e1;
  --search: #2f6f8f;
  --fetch: #b7791f;
  --ok: #3c7a4a;
  --bad: #b23a3a;
  --warn: #9a6a00;
  font-family: "Avenir Next", "PingFang SC", "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
  font-size: 15px;
  line-height: 1.5;
  color: var(--ink);
  background: var(--paper);
}
* { box-sizing: border-box; }
body { margin: 0; display: grid; grid-template-columns: 340px minmax(0, 1fr); min-height: 100vh; }
button, input { font: inherit; }
:focus-visible { outline: 2px solid var(--search); outline-offset: 2px; }
.num, td.num { font-variant-numeric: tabular-nums; }
.muted { color: var(--muted); }
.small { font-size: 13px; }

.sidebar { border-right: 1px solid var(--line); padding: 18px 14px; height: 100vh; position: sticky; top: 0; overflow-y: auto; }
.sidebar-head { display: flex; align-items: center; justify-content: space-between; }
.sidebar h1 { font-size: 19px; margin: 0; font-weight: 600; }
.sidebar button { border: 1px solid var(--line); background: var(--sheet); border-radius: 6px; padding: 3px 10px; cursor: pointer; }
#filter { width: 100%; margin: 12px 0 4px; padding: 7px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--sheet); }
.runs { list-style: none; margin: 8px 0 0; padding: 0; }
.runs li button { display: block; width: 100%; text-align: left; border: 0; border-left: 3px solid transparent; background: none; padding: 8px 10px; cursor: pointer; border-radius: 0 6px 6px 0; }
.runs li button:hover { background: #e3e8ee; }
.runs li button[aria-current="true"] { background: var(--sheet); border-left-color: var(--search); }
.runs .q { display: block; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.runs .meta { display: flex; gap: 8px; font-size: 12.5px; color: var(--muted); }

.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; vertical-align: middle; background: var(--muted); }
.st-success, .st-ok { background: var(--ok); }
.st-partial, .st-empty { background: var(--warn); }
.st-failed, .st-error, .st-blocked, .st-timeout { background: var(--bad); }
.st-skipped, .st-untried { background: #b6bec9; }

.detail { padding: 28px 36px 80px; max-width: 1180px; }
.empty { color: var(--muted); margin-top: 30vh; text-align: center; }
.query-title { font-size: 28px; font-weight: 600; margin: 0 0 6px; overflow-wrap: anywhere; }
.facts { display: flex; flex-wrap: wrap; gap: 6px 22px; margin: 0 0 18px; color: var(--muted); }
.facts b { color: var(--ink); font-weight: 600; }

section { background: var(--sheet); border: 1px solid var(--line); border-radius: 8px; padding: 18px 20px; margin-top: 18px; }
section > h2 { font-size: 17px; margin: 0 0 12px; font-weight: 600; display: flex; gap: 10px; align-items: baseline; }
section > h2 .step { color: var(--search); font-variant-numeric: tabular-nums; }
section > h2 .aside { font-size: 13px; color: var(--muted); font-weight: 400; }

.chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 10px; }
.chip { border: 1px solid var(--line); border-radius: 999px; padding: 1px 10px; font-size: 13px; background: #fff; }
.chip.on { border-color: var(--search); color: var(--search); }
.chip.off { text-decoration: line-through; color: var(--muted); }
dl.kv { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; margin: 0; }
dl.kv dt { color: var(--muted); }
dl.kv dd { margin: 0; overflow-wrap: anywhere; }

table { width: 100%; border-collapse: collapse; font-size: 14px; }
th { text-align: left; font-weight: 500; color: var(--muted); border-bottom: 1px solid var(--line); padding: 6px 8px; }
td { border-bottom: 1px solid #e6eaef; padding: 7px 8px; vertical-align: top; overflow-wrap: anywhere; }
tr.expandable { cursor: pointer; }
tr.expandable:hover td { background: #f1f4f7; }
tr.sub td { background: #f6f8fa; }
.err { color: var(--bad); }
.up { color: var(--ok); }
.down { color: var(--bad); }
a { color: var(--search); }
pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f3f5f8; border: 1px solid #e3e8ee; border-radius: 6px; padding: 10px 12px; font-size: 12.5px; max-height: 360px; overflow: auto; }
details > summary { cursor: pointer; color: var(--muted); }

/* The one bold element: every provider call and page fetch on one time axis. */
.timeline { position: relative; margin-top: 6px; }
.tl-axis { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); margin-left: 230px; border-bottom: 1px solid var(--line); padding-bottom: 2px; }
.tl-row { display: grid; grid-template-columns: 230px 1fr; align-items: center; height: 24px; }
.tl-label { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding-right: 10px; }
.tl-track { position: relative; height: 100%; background-image: linear-gradient(to right, #e6eaef 1px, transparent 1px); background-size: 25% 100%; }
.tl-bar { position: absolute; top: 5px; height: 14px; border-radius: 3px; min-width: 2px; }
.tl-bar.search { background: var(--search); }
.tl-bar.fetch { background: var(--fetch); }
.tl-bar.failed { background: var(--bad); }
.tl-bar span { position: absolute; left: calc(100% + 6px); top: -2px; font-size: 12px; color: var(--muted); white-space: nowrap; font-variant-numeric: tabular-nums; }
.tl-bar.end span { left: auto; right: 6px; color: #fff; }
.tl-group { font-size: 12.5px; color: var(--muted); margin: 10px 0 2px; }

.page { border-top: 1px solid #e6eaef; padding: 12px 0; }
.page:first-of-type { border-top: 0; }
.page-head { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.page-head .rank { color: var(--muted); font-variant-numeric: tabular-nums; min-width: 2em; }
.steps { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; margin: 8px 0 4px; font-size: 13px; }
.step-box { border: 1px solid var(--line); border-radius: 5px; padding: 2px 8px; background: #fff; }
.step-box.ok { border-color: var(--ok); color: var(--ok); }
.step-box.error, .step-box.blocked, .step-box.timeout { border-color: var(--bad); color: var(--bad); }
.step-box.skipped, .step-box.untried { color: #8a94a1; border-style: dashed; }
.steps .sep { color: #a0a9b4; }

@media (max-width: 860px) {
  body { grid-template-columns: 1fr; }
  .sidebar { position: static; height: auto; max-height: 45vh; border-right: 0; border-bottom: 1px solid var(--line); }
  .detail { padding: 18px 14px 60px; }
  .tl-axis { margin-left: 120px; }
  .tl-row { grid-template-columns: 120px 1fr; }
}
@media (prefers-reduced-motion: no-preference) {
  .tl-bar { transition: width .25s ease-out; }
}
"""

SCRIPT = r"""
"use strict";
const $ = (id) => document.getElementById(id);
let runs = [];
let currentId = null;

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "onclick") node.addEventListener("click", value);
    else if (key === "style") node.style.cssText = value;
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function link(url, text) {
  const value = String(url || "");
  if (/^https?:\/\//i.test(value)) {
    return h("a", { href: value, target: "_blank", rel: "noopener noreferrer" }, text || value);
  }
  return h("span", {}, text || value);
}

const ms = (value) => value === null || value === undefined ? "—" :
  value >= 1000 ? (value / 1000).toFixed(value >= 10000 ? 1 : 2) + " s" : value + " ms";
const dot = (status) => h("span", { class: "dot st-" + (status || "none"), "aria-hidden": "true" });
const OUTCOME = { success: "成功", partial: "部分成功", failed: "失败", empty: "无结果" };
const STATUS = { ok: "成功", error: "失败", partial: "部分失败", empty: "无结果", skipped: "跳过", blocked: "被拦截", untried: "未尝试", timeout: "超时", running: "未结束" };
const when = (ts) => ts ? new Date(ts).toLocaleString() : "";

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(url + " 返回 " + response.status);
  return response.json();
}

async function loadRuns() {
  try {
    const data = await getJSON("/api/runs");
    runs = data.runs;
    $("source").textContent = "日志位置：" + data.sources.join("，");
  } catch (error) {
    $("source").textContent = "读取记录失败：" + error.message;
  }
  renderRuns();
}

function renderRuns() {
  const term = $("filter").value.trim().toLowerCase();
  const list = $("runs");
  list.replaceChildren();
  const shown = runs.filter((run) => !term ||
    String(run.query || "").toLowerCase().includes(term) || String(run.route || "").toLowerCase().includes(term));
  if (!shown.length) {
    list.append(h("li", { class: "muted small" }, runs.length ? "没有匹配的记录。" :
      "还没有记录。运行一次 multi-search search 后点“刷新”。"));
  }
  for (const run of shown) {
    list.append(h("li", {}, h("button", {
      type: "button", "aria-current": run.run_id === currentId ? "true" : "false",
      onclick: () => { location.hash = run.run_id; },
    },
      h("span", { class: "q" }, run.query || "(无查询词)"),
      h("span", { class: "meta" },
        h("span", {}, dot(run.outcome), OUTCOME[run.outcome] || run.outcome || (run.complete ? "完成" : "未结束")),
        run.command === "fetch" ? h("span", {}, "抓取") : h("span", {}, run.route || ""),
        h("span", { class: "num" }, ms(run.elapsed_ms)),
        h("span", {}, when(run.ts))),
    )));
  }
}

async function showRun(id) {
  currentId = id;
  renderRuns();
  const main = $("detail");
  if (!id) { main.replaceChildren(h("p", { class: "empty" }, "从左侧选择一次搜索查看详情。")); return; }
  main.replaceChildren(h("p", { class: "empty" }, "加载中…"));
  try {
    const detail = await getJSON("/api/runs/" + encodeURIComponent(id));
    main.replaceChildren(...renderDetail(detail));
    main.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  } catch (error) {
    main.replaceChildren(h("p", { class: "empty err" }, "读取这次记录失败：" + error.message));
  }
}

function section(step, title, aside, ...body) {
  return h("section", {}, h("h2", {}, step ? h("span", { class: "step" }, step) : null, title,
    aside ? h("span", { class: "aside" }, aside) : null), ...body);
}

function renderDetail(d) {
  const s = d.summary;
  const out = [
    h("h1", { class: "query-title" }, s.query || "(无查询词)"),
    h("p", { class: "facts" },
      h("span", {}, dot(s.outcome), h("b", {}, OUTCOME[s.outcome] || s.outcome || (s.complete ? "完成" : "未结束"))),
      h("span", {}, "总耗时 ", h("b", { class: "num" }, ms(d.stages.total_ms))),
      d.stages.search_ms !== undefined && d.stages.search_ms !== null ? h("span", {}, "搜索 ", h("b", { class: "num" }, ms(d.stages.search_ms))) : null,
      d.stages.rerank_ms ? h("span", {}, "重排 ", h("b", { class: "num" }, ms(d.stages.rerank_ms))) : null,
      d.stages.fetch_ms ? h("span", {}, "抓取 ", h("b", { class: "num" }, ms(d.stages.fetch_ms))) : null,
      s.result_count !== null && s.result_count !== undefined ? h("span", {}, "结果 ", h("b", {}, s.result_count), " 条") : null,
      h("span", {}, when(s.ts))),
  ];
  if (s.error) out.push(h("p", { class: "err" }, "运行失败：" + s.error));
  out.push(renderTimeline(d));
  if (d.route && d.route.event) out.push(renderRoute(d.route, d.request));
  if (d.query_plan && d.query_plan.event) out.push(renderQueries(d.query_plan, d.queries));
  if (d.providers.length) out.push(renderProviders(d.providers));
  if (d.ranking.rows.length) out.push(renderRanking(d.ranking));
  if (d.fetches.length || d.fetch_stage.start.event) out.push(renderFetches(d));
  out.push(section("", "原始记录", d.events.length + " 条事件",
    h("details", {}, h("summary", {}, "展开全部事件 JSON"),
      h("pre", {}, d.events.map((event) => JSON.stringify(event, null, 2)).join("\n")))));
  return out;
}

function renderTimeline(d) {
  const rows = [];
  for (const p of d.providers) {
    for (const a of p.attempts) {
      if (a.t_ms === undefined || a.elapsed_ms === undefined) continue;
      rows.push({ group: "搜索", label: p.source + "  " + p.query, start: a.t_ms - a.elapsed_ms,
        dur: a.elapsed_ms, kind: "search", failed: (a.errors && a.errors.length) || a.error });
    }
  }
  for (const f of d.fetches) {
    const r = f.result;
    if (!r || r.t_ms === undefined) continue;
    let host = f.url;
    try { host = new URL(f.url).host + new URL(f.url).pathname; } catch (_) { /* keep raw */ }
    rows.push({ group: "抓取", label: host, start: r.t_ms - (r.elapsed_ms || 0), dur: r.elapsed_ms || 0,
      kind: "fetch", failed: !!r.error, note: r.backend || (r.event === "fetch_timeout" ? "超时" : "") });
  }
  if (!rows.length) return section("", "时间线", "没有可画的调用");
  const total = Math.max(d.stages.total_ms || 0, ...rows.map((r) => r.start + r.dur), 1);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => h("span", { class: "num" }, ms(Math.round(total * f))));
  const body = [h("div", { class: "tl-axis" }, ticks)];
  let group = null;
  for (const r of rows) {
    if (r.group !== group) { group = r.group; body.push(h("div", { class: "tl-group" }, group)); }
    const left = Math.max(0, r.start) / total * 100;
    const width = Math.max(0.3, r.dur / total * 100);
    body.push(h("div", { class: "tl-row" },
      h("div", { class: "tl-label", title: r.label }, r.label),
      h("div", { class: "tl-track" }, h("div", {
        class: "tl-bar " + r.kind + (r.failed ? " failed" : "") + (left + width > 78 ? " end" : ""),
        style: "left:" + left.toFixed(2) + "%;width:" + Math.min(width, 100 - left).toFixed(2) + "%",
        title: r.label + "：" + ms(r.dur),
      }, h("span", {}, ms(r.dur) + (r.note ? "  " + r.note : "") + (r.failed && r.note !== "超时" ? "  失败" : ""))))));
  }
  return section("", "时间线", "每次搜索器调用和页面抓取，按开始时间排在同一时间轴上", h("div", { class: "timeline" }, body));
}

function renderRoute(route, request) {
  const active = new Set(route.active_sources || []);
  const disabled = new Set(route.disabled_sources || []);
  const chips = (route.route_sources || []).map((name) => h("span", {
    class: "chip " + (active.has(name) ? "on" : "off"),
    title: active.has(name) ? "参与本次搜索" : disabled.has(name) ? "已全局禁用" : "未参与",
  }, name));
  const counts = route.per_provider_counts || {};
  const params = (request && request.parameters) || {};
  const explicit = (route.requested_sources || []).length > 0;
  const aside = explicit ? "用 --source 指定了搜索源，路由的源列表不起作用，只提供超时和默认条数"
    : route.requested_route ? "" : "未指定 --route，使用默认路由";
  return section("1", "路由", aside,
    h("dl", { class: "kv" },
      h("dt", {}, "请求的路由"), h("dd", {}, route.requested_route || "（未指定）"),
      h("dt", {}, explicit ? "参数来自路由" : "实际使用"), h("dd", {}, h("b", {}, route.resolved_route || "—")),
      (route.requested_sources || []).length ? [h("dt", {}, "指定的源"), h("dd", {}, route.requested_sources.join("、"))] : null,
      h("dt", {}, explicit ? "参与的源" : "路由内的源"), h("dd", {}, h("div", { class: "chips" }, chips)),
      disabled.size ? [h("dt", {}, "已禁用"), h("dd", {}, [...disabled].join("、"))] : null,
      h("dt", {}, "每个源取"), h("dd", {}, [...active].map((n) => n + " " + (counts[n] ?? "?") + " 条").join("，")),
      h("dt", {}, "搜索超时"), h("dd", { class: "num" }, (route.search_timeout_s ?? "—") + " 秒"),
      h("dt", {}, "状态库"), h("dd", {}, route.use_state === false ? "关闭（--no-state）" : "开启"),
      params.no_fetch ? [h("dt", {}, "抓取"), h("dd", {}, "关闭（--no-fetch，只要候选）")] : null));
}

function renderQueries(plan, done) {
  const weights = plan.weights || {};
  const timing = Object.fromEntries((done || []).map((q) => [q.query, q]));
  const notes = [];
  if (plan.duplicate_count) notes.push("去掉了 " + plan.duplicate_count + " 个重复的改写");
  if (plan.discarded_blank_count) notes.push("去掉了 " + plan.discarded_blank_count + " 个空白改写");
  return section("2", "搜索词",
    plan.expand_from === "config" ? "改写来自配置文件的 expand" : (plan.expand_input || []).length ? "改写来自本次请求的 --expand" : "没有改写，只搜原始查询",
    h("dl", { class: "kv" },
      h("dt", {}, "传入的查询"), h("dd", {}, h("b", {}, plan.query)),
      h("dt", {}, "传入的改写"), h("dd", {}, (plan.expand_input || []).length ?
        h("div", { class: "chips" }, plan.expand_input.map((q) => h("span", { class: "chip" }, JSON.stringify(q)))) : "无"),
      h("dt", {}, "融合方式"), h("dd", {}, (plan.fusion && plan.fusion.mode) === "weighted" ? "加权" : "等权")),
    h("p", { class: "muted small" }, "这里记录的是调用方（通常是 Agent）交给 CLI 的查询和改写。用户最初的提问不会传给 CLI，所以记录不到。"),
    notes.length ? h("p", { class: "muted small" }, notes.join("；")) : null,
    h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "实际执行的查询"), h("th", {}, "类型"), h("th", {}, "权重"),
        h("th", {}, "耗时"), h("th", {}, "命中"), h("th", {}, "错误"))),
      h("tbody", {}, (plan.executed_queries || []).map((q) => {
        const t = timing[q] || {};
        return h("tr", {}, h("td", {}, q), h("td", {}, q === plan.primary_query ? "主查询" : "改写"),
          h("td", { class: "num" }, weights[q] ?? "—"), h("td", { class: "num" }, ms(t.elapsed_ms)),
          h("td", { class: "num" }, t.hit_count ?? "—"), h("td", { class: "num" }, t.error_count ?? "—"));
      }))));
}

function renderProviders(providers) {
  const tbody = h("tbody");
  for (const p of providers) {
    const errors = (p.errors || []).map((e) => e.error).filter(Boolean);
    const sub = h("tr", { class: "sub", hidden: true }, h("td", { colspan: 6 },
      (p.rows || []).length ? h("ol", {}, p.rows.map((row) => h("li", {},
        link(row.url, row.title || row.url), row.snippet ? h("div", { class: "muted small" }, row.snippet) : null)))
        : h("span", { class: "muted" }, "没有返回结果。"),
      p.attempts.length > 1 ? h("p", { class: "small muted" }, "共尝试 " + p.attempts.length + " 次（换 key 重试）：" +
        p.attempts.map((a) => ms(a.elapsed_ms) + ((a.errors || []).length || a.error ? " 失败" : " 成功")).join("，")) : null));
    const row = h("tr", { class: "expandable", tabindex: 0, "aria-expanded": "false" },
      h("td", {}, dot(p.status), p.source), h("td", {}, p.query),
      h("td", {}, STATUS[p.status] || p.status), h("td", { class: "num" }, ms(p.elapsed_ms)),
      h("td", { class: "num" }, p.hit_count),
      h("td", { class: errors.length ? "err" : "" }, errors.join("；") || (p.elapsed_ms === null ? "未调用" : "")));
    const toggle = () => { sub.hidden = !sub.hidden; row.setAttribute("aria-expanded", String(!sub.hidden)); };
    row.addEventListener("click", toggle);
    row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
    tbody.append(row, sub);
  }
  return section("3", "搜索器", "点一行查看这个源返回的结果",
    h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "搜索源"), h("th", {}, "查询"), h("th", {}, "状态"),
      h("th", {}, "耗时"), h("th", {}, "命中"), h("th", {}, "错误"))), tbody));
}

function renderRanking(r) {
  const reranked = r.mode_used === "rrf_model";
  let note = "先按各源的排名做 RRF 融合（同一网址在多个源、多个查询里排得越靠前，分越高）";
  note += reranked ? "，再用模型打相关性分重排" : r.mode_requested === "rrf_model" ?
    "；模型重排失败，保留 RRF 顺序：" + (r.fallback_reason || "原因未知") : "；没有开启模型重排";
  return section("4", "排序", "融合候选 " + r.fused_count + " 条，最终保留 " + r.rows.length + " 条",
    h("p", { class: "muted small" }, note),
    h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "最终"), h("th", {}, "RRF"), h("th", {}, "结果"),
        h("th", {}, "各源排名"), h("th", {}, "RRF 分"), h("th", {}, "相关性"))),
      h("tbody", {}, r.rows.map((row) => {
        const moved = row.rrf_rank ? row.rrf_rank - row.final_rank : 0;
        return h("tr", {},
          h("td", { class: "num" }, "#" + row.final_rank),
          h("td", { class: "num" }, row.rrf_rank ? "#" + row.rrf_rank : "—",
            moved ? h("span", { class: moved > 0 ? "up" : "down" }, moved > 0 ? " ↑" + moved : " ↓" + (-moved)) : null),
          h("td", {}, link(row.url, row.title || row.url), h("div", { class: "muted small" }, row.url)),
          h("td", { class: "small" }, (row.provider_ranks || []).map((p) =>
            h("div", {}, p.provider + " 第 " + p.rank + " 名", h("span", { class: "muted" }, "（" + p.query + "）")))),
          h("td", { class: "num" }, row.rrf_score !== null && row.rrf_score !== undefined ? Number(row.rrf_score).toFixed(4) : "—"),
          h("td", { class: "num" }, row.relevance_score !== null && row.relevance_score !== undefined ? Number(row.relevance_score).toFixed(3) : "—"));
      }))));
}

const HOW = { scrape: "现场抓取", cache_hit: "缓存命中", search_provider_body: "搜索源自带正文" };

function renderFetches(d) {
  const start = d.fetch_stage.start;
  const rankOf = Object.fromEntries(d.ranking.rows.map((row) => [row.url, row.final_rank]));
  const pages = d.fetches.map((f) => {
    const result = f.result || {};
    const tried = Object.fromEntries(f.attempts.map((a) => [a.backend, a]));
    const order = (f.chain && f.chain.order) || f.attempts.map((a) => a.backend);
    const steps = [];
    order.forEach((backend, index) => {
      const a = tried[backend];
      const status = a ? a.status : "untried";
      if (index) steps.push(h("span", { class: "sep", "aria-hidden": "true" }, "›"));
      steps.push(h("span", { class: "step-box " + status, title: a && a.error ? a.error : (a && a.reason) || STATUS[status] },
        backend + "  " + (STATUS[status] || status) + (a && a.elapsed_ms !== undefined && status !== "skipped" ? "  " + ms(a.elapsed_ms) : "")));
    });
    const reordered = f.chain && JSON.stringify(f.chain.order) !== JSON.stringify(f.chain.order_before_site_memory);
    const keys = f.key_attempts.map((k) => k.backend + " " + (k.key_id === "anonymous" ? "匿名" : k.key_id) +
      " " + ms(k.elapsed_ms) + (k.error ? " 失败：" + k.error : " 成功"));
    return h("div", { class: "page" },
      h("div", { class: "page-head" },
        h("span", { class: "rank" }, rankOf[f.url] ? "#" + rankOf[f.url] : ""),
        dot(result.event === "fetch_timeout" ? "timeout" : result.error ? "error" : result.event ? "ok" : "untried"),
        link(f.url),
        h("span", { class: "muted small" }, [HOW[result.how] || ({ fetch_failed: "抓取失败", fetch_timeout: "抓取超时，没有拿到正文" }[result.event]) || result.how || "",
          result.backend ? "用 " + result.backend : "", result.elapsed_ms !== undefined ? ms(result.elapsed_ms) : "",
          result.content_length ? result.content_length + " 字符" : ""].filter(Boolean).join("，"))),
      result.error ? h("p", { class: "err small" }, result.error) : null,
      steps.length ? h("div", { class: "steps" }, steps) : null,
      reordered ? h("p", { class: "muted small" }, "站点抓取记忆调整了顺序，原顺序：" + f.chain.order_before_site_memory.join(" › ")) : null,
      keys.length ? h("p", { class: "muted small" }, "Key 尝试：" + keys.join("；")) : null,
      result.body_preview ? h("details", {}, h("summary", {}, "正文预览"), h("pre", {}, result.body_preview)) : null);
  });
  return section("5", "抓取的页面",
    start.event ? "并发 " + start.concurrency + "，时限 " + start.timeout_s + " 秒，" + d.fetches.length + " 个页面" : "",
    pages.length ? pages : h("p", { class: "muted" }, "没有抓取页面。"));
}

window.addEventListener("hashchange", () => showRun(location.hash.slice(1)));
document.addEventListener("DOMContentLoaded", async () => {
  $("filter").addEventListener("input", renderRuns);
  $("refresh").addEventListener("click", loadRuns);
  await loadRuns();
  const initial = location.hash.slice(1) || (runs[0] && runs[0].run_id);
  if (initial) { if (location.hash.slice(1) === initial) showRun(initial); else location.hash = initial; }
});
"""
