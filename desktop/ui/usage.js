import { el, pageRoot, disposePage } from './dom.js';
import { showError } from './api.js';
import { formatTimestamp } from './balance.js';

const UNITS = { credits: 'credits', tokens: 'tokens', searches: '次搜索', usd: '美元', requests: '次请求' };
const SCOPES = { key: 'Key', team: '团队', account: '账户' };
const STATUSES = { ok: '正常', needs_credential: '需要凭据', unsupported: '不支持余额查询', error: '查询失败' };
const amount = value => typeof value === 'number' && Number.isFinite(value)
  ? value.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '未知';
const timestamp = value => value ? formatTimestamp(value) : '未知';
const unitLabel = unit => UNITS[unit] || unit || '未知';
const scopeLabel = scope => SCOPES[scope] || scope || '未知';

/** @param {import('./types.js').UsagePace} pace */
function paceText(pace) {
  if (pace.reason === 'insufficient_data') return '数据不足';
  if (pace.rate_per_day == null) return '配速未知';
  const rate = `每天消耗 ${amount(pace.rate_per_day)} ${unitLabel(pace.unit)}`;
  if (pace.lasts_until_reset === true) return `${rate}，能撑到重置`;
  if (pace.projected_empty_at) return `${rate}，预计 ${timestamp(pace.projected_empty_at)} 用完`;
  return `${rate}，预计用完时间未知`;
}

function quota(doc, row) {
  const section = el(doc, 'div', { class: 'usage-quota' });
  section.append(el(doc, 'p', { class: 'usage-scope' }, `${scopeLabel(row.scope)}额度`));
  section.append(el(doc, 'p', { class: 'usage-amount' },
    `剩余 ${amount(row.remaining)} / 上限 ${amount(row.limit)} ${unitLabel(row.unit)}`));
  if (typeof row.remaining === 'number' && typeof row.limit === 'number' && row.limit > 0) {
    const progress = el(doc, 'progress', { max: String(row.limit),
      value: String(Math.max(0, Math.min(row.limit, row.remaining))),
      'aria-label': `${scopeLabel(row.scope)}剩余额度（${unitLabel(row.unit)}）` });
    section.append(progress);
  }
  if (row.message) section.append(el(doc, 'p', { class: 'usage-note' }, row.message));
  return section;
}

/** Draw each fingerprint separately: different units and account scopes must never be added. */
function chart(doc, history, scope, unit) {
  const figure = el(doc, 'figure', { class: 'usage-chart' });
  const label = `近 30 天剩余走势 · ${scopeLabel(scope)} · ${unitLabel(unit)}`;
  figure.append(el(doc, 'figcaption', {}, label));
  const points = history.filter(row => row.scope === scope && row.unit === unit
    && Number.isFinite(Date.parse(row.fetched_at))).sort((a, b) => Date.parse(a.fetched_at) - Date.parse(b.fetched_at));
  const series = new Map();
  for (const point of points) {
    const key = point.key_fingerprint;
    if (!series.has(key)) series.set(key, []);
    series.get(key).push(point);
  }
  const known = points.filter(point => typeof point.remaining === 'number' && Number.isFinite(point.remaining));
  if (![...series.values()].some(rows => new Set(rows.filter(row => row.remaining != null)
    .map(row => row.fetched_at)).size >= 2)) {
    figure.append(el(doc, 'p', { class: 'usage-note' }, '数据不足'));
    return figure;
  }
  const start = Date.parse(points[0].fetched_at);
  const end = Date.parse(points.at(-1).fetched_at);
  const max = Math.max(1, ...known.map(point => point.remaining));
  const min = Math.min(0, ...known.map(point => point.remaining));
  const svg = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 320 110');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', label);
  const title = doc.createElementNS(svg.namespaceURI, 'title');
  title.textContent = label;
  svg.append(title);
  const legend = el(doc, 'ul', { class: 'usage-legend' });
  let index = 0;
  for (const [fingerprint, rows] of series) {
    const dash = ['none', '6 3', '2 3'][index++ % 3];
    let run = [];
    const line = () => {
      if (!run.length) return;
      const polyline = doc.createElementNS(svg.namespaceURI, 'polyline');
      polyline.setAttribute('points', run.join(' '));
      polyline.setAttribute('stroke-dasharray', dash);
      svg.append(polyline);
      run = [];
    };
    for (const point of rows) {
      if (point.remaining == null) { line(); continue; }
      const x = 8 + (Date.parse(point.fetched_at) - start) / Math.max(1, end - start) * 304;
      const y = 102 - (point.remaining - min) / (max - min) * 94;
      run.push(`${x.toFixed(2)},${y.toFixed(2)}`);
      const dot = doc.createElementNS(svg.namespaceURI, 'circle');
      dot.setAttribute('cx', String(x));
      dot.setAttribute('cy', String(y));
      dot.setAttribute('r', '2');
      const description = doc.createElementNS(svg.namespaceURI, 'title');
      description.textContent = `${fingerprint || '指纹未知'}：${timestamp(point.fetched_at)}，剩余 ${amount(point.remaining)}`;
      dot.append(description);
      svg.append(dot);
    }
    line();
    legend.append(el(doc, 'li', {}, `${fingerprint || '指纹未知'}：${['实线', '虚线', '点线'][(index - 1) % 3]}`));
  }
  figure.append(svg, el(doc, 'p', { class: 'usage-chart-range' },
    `${timestamp(points[0].fetched_at)} 至 ${timestamp(points.at(-1).fetched_at)}；范围 ${amount(min)}–${amount(max)}`));
  if (series.size > 1) figure.append(legend);
  return figure;
}

/** @param {Document} doc @param {import('./types.js').UsageProvider} provider */
function cardBody(doc, provider) {
  const body = el(doc, 'div', { class: 'usage-card-body' });
  if (provider.balance_supported) {
    if (!provider.current.length) body.append(el(doc, 'p', {}, '暂无余额信息，数据不足。'));
    for (const status of new Set(provider.current.map(row => row.status))) {
      body.append(el(doc, 'p', { class: 'usage-status', 'data-kind': status }, STATUSES[status] || '未知状态'));
    }
    for (const total of provider.totals) body.append(quota(doc, total));
    for (const report of provider.current) {
      const identity = provider.current.length > 1 ? `${report.key_fingerprint || '指纹未知'}：` : '';
      body.append(el(doc, 'p', { class: 'usage-note' },
        `${identity}重置时间：${timestamp(report.resets_at)}；更新时间：${timestamp(report.fetched_at)}`));
      if (report.message) body.append(el(doc, 'p', { class: 'usage-note' }, report.message));
    }
    if (!provider.pace.length) body.append(el(doc, 'p', { class: 'usage-pace' }, '数据不足'));
    for (const pace of provider.pace) {
      const identity = provider.pace.length > 1
        ? `${pace.key_fingerprint || '指纹未知'}（${scopeLabel(pace.scope)} / ${unitLabel(pace.unit)}）：` : '';
      body.append(el(doc, 'p', { class: 'usage-pace' }, `${identity}${paceText(pace)}`));
    }
    const groups = new Map();
    for (const row of [...provider.totals, ...provider.history]) groups.set(JSON.stringify([row.scope, row.unit]), row);
    for (const { scope, unit } of groups.values()) body.append(chart(doc, provider.history, scope, unit));
    const fingerprints = new Set(provider.current.map(row => row.key_fingerprint).filter(Boolean));
    if (fingerprints.size > 1) {
      const details = doc.createElement('details');
      details.className = 'usage-keys';
      const summary = el(doc, 'summary', {}, `展开 ${fingerprints.size} 个 Key`);
      details.append(summary);
      const rows = el(doc, 'div');
      for (const report of provider.current) {
        const row = quota(doc, { ...report, message: '' });
        row.prepend(el(doc, 'strong', {}, report.key_fingerprint || '指纹未知'));
        row.append(el(doc, 'p', {}, STATUSES[report.status] || '未知状态'));
        rows.append(row);
      }
      details.append(rows);
      details.addEventListener('toggle', () => {
        summary.textContent = details.open ? `收起 ${fingerprints.size} 个 Key` : `展开 ${fingerprints.size} 个 Key`;
      });
      body.append(details);
    }
  } else {
    body.append(el(doc, 'p', { class: 'usage-status' }, '不支持余额查询'));
    body.append(el(doc, 'p', { class: 'usage-note' }, provider.balance_note
      || provider.current.find(row => row.message)?.message || '该服务商未提供余额查询接口。'));
  }
  const calls = el(doc, 'dl', { class: 'usage-calls' });
  /** @type {Array<[string, import('./types.js').UsageCallCounts]>} */
  const periods = [['今天', provider.calls.today], ['近 7 天', provider.calls.last_7_days]];
  for (const [label, counts] of periods) {
    calls.append(el(doc, 'dt', {}, `本机调用 · ${label}`), el(doc, 'dd', {},
      `搜索 ${amount(counts.search)} 次，抓取 ${amount(counts.scrape)} 次，失败 ${amount(counts.failures)} 次`));
  }
  body.append(calls);
  return body;
}

/**
 * @param {HTMLElement} root
 * @param {any} api
 * @param {{number?: string, signal?: AbortSignal, navigate?: (id: string) => void}} [options]
 */
export async function mountUsage(root, api, { number = '05', signal, navigate } = {}) {
  root = pageRoot(root);
  root.classList.add('usage-page');
  const doc = root.ownerDocument;
  root.innerHTML = `<section class="heading usage-head"><div><p class="eyebrow"></p>
    <h1 tabindex="-1">用量</h1><p>查看各服务商的剩余额度、配速与近 30 天走势。</p></div>
    <button type="button" class="primary" data-action="refresh-all">刷新全部</button></section>
    <p class="usage-note">刷新遵守服务商缓存时长。本机统计不等于服务商计费次数；历史只保留 30 天。</p>
    <p class="usage-note" data-updated role="status">更新时间：未知</p>
    <p class="error-message" data-error role="alert"></p>
    <p class="usage-note" data-notice role="status"></p>
    <div class="usage-grid" data-providers></div>
    <section data-local-only hidden><h2>仅本机统计</h2><div class="usage-grid" data-local-providers></div></section>`;
  root.querySelector('.eyebrow').textContent = `${number} / USAGE`;
  const refreshAll = /** @type {HTMLButtonElement} */ (root.querySelector('[data-action="refresh-all"]'));
  const errorSlot = root.querySelector('[data-error]');
  const notice = root.querySelector('[data-notice]');
  const cards = new Map();
  let busy = false;
  let disposed = Boolean(signal?.aborted);

  function renderCard(provider) {
    let card = cards.get(provider.id);
    if (!card) {
      card = el(doc, 'article', { class: 'usage-card panel', 'data-provider': provider.id });
      const head = el(doc, 'div', { class: 'usage-card-head' });
      const title = el(doc, 'h3', {}, provider.label);
      const actions = el(doc, 'div', { class: 'usage-actions' });
      const refresh = el(doc, 'button', { type: 'button', 'data-action': 'refresh-provider',
        'aria-label': `刷新 ${provider.label} 用量` }, '刷新');
      const settings = el(doc, 'button', { type: 'button', 'data-action': 'settings',
        'aria-label': `${provider.label}：去设置` }, '去设置');
      refresh.addEventListener('click', () => { void load(provider.id); });
      settings.addEventListener('click', () => navigate?.('sources'));
      actions.append(refresh, settings);
      head.append(title, actions);
      card.append(head, cardBody(doc, provider));
      cards.set(provider.id, card);
    } else {
      card.querySelector('h3').textContent = provider.label;
      const oldDetails = card.querySelector('details');
      const body = cardBody(doc, provider);
      if (oldDetails?.open && body.querySelector('details')) body.querySelector('details').open = true;
      card.querySelector('.usage-card-body').replaceWith(body);
    }
    const target = root.querySelector(provider.balance_supported ? '[data-providers]' : '[data-local-providers]');
    if (card.parentNode !== target) target.append(card);
  }

  async function load(provider = null) {
    if (busy || disposed) return;
    if (typeof api?.usageView !== 'function') {
      notice.textContent = '请更新 CLI 和桌面应用后查看用量。';
      refreshAll.disabled = true;
      return;
    }
    busy = true;
    root.setAttribute('aria-busy', 'true');
    for (const button of root.querySelectorAll('button[data-action^="refresh"]')) button.setAttribute('disabled', '');
    refreshAll.textContent = provider ? '刷新全部' : '刷新中…';
    errorSlot.textContent = '';
    errorSlot.removeAttribute('title');
    try {
      // Opening the page and explicit refreshes query balances through the CLI's TTL cache.
      const view = /** @type {import('./types.js').UsageView} */ (await api.usageView(provider, true));
      if (disposed) return;
      const updateRequired = view.status === 'cli_update_required';
      notice.textContent = updateRequired ? (view.message || '请更新 CLI 后查看用量。')
        : view.usage_error || (!view.providers.length ? '暂无服务商用量信息。' : '');
      if (!provider || updateRequired) {
        cards.clear();
        root.querySelector('[data-providers]').replaceChildren();
        root.querySelector('[data-local-providers]').replaceChildren();
      }
      if (!updateRequired) for (const item of view.providers) renderCard(item);
      root.querySelector('[data-local-only]').toggleAttribute('hidden', !root.querySelector('[data-local-providers]').children.length);
      root.querySelector('[data-updated]').textContent = `更新时间：${updateRequired ? '未知' : timestamp(new Date().toISOString())}`;
    } catch (error) {
      if (!disposed) showError(errorSlot, error, '用量读取失败，请重试。');
    } finally {
      if (!disposed) {
        busy = false;
        root.setAttribute('aria-busy', 'false');
        refreshAll.textContent = '刷新全部';
        for (const button of root.querySelectorAll('button[data-action^="refresh"]')) {
          button.removeAttribute('disabled');
        }
      }
    }
  }
  function dispose() {
    disposed = true;
    signal?.removeEventListener('abort', dispose);
    disposePage(root);
  }
  signal?.addEventListener('abort', dispose, { once: true });
  refreshAll.addEventListener('click', () => { void load(); });
  await load();
  return { dispose };
}
