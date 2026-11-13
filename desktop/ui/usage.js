import { el, pageRoot, disposePage } from './dom.js';
import { showError } from './api.js';
import { formatTimestamp } from './balance.js';
import { createMeter, createAlertBadge } from './meter.js';
import { SOURCE_CATALOG } from './source-catalog.js';

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

const quotaText = row => `剩余 ${amount(row?.remaining)} / 上限 ${amount(row?.limit)} ${unitLabel(row?.unit)}`;
const visibleAccounts = provider => provider.accounts.filter(account =>
  account.id !== 'default' || account.keys.length || provider.accounts.length === 1);

/** @param {import('./types.js').UsageProvider} provider @param {import('./types.js').BalanceReport} report */
function sharedTavilyAccount(provider, report) {
  if (provider.id !== 'tavily' || report?.scope !== 'key' || report.unit !== 'credits'
    || report.status !== 'ok' || !report.key_fingerprint) return null;
  return provider.current.find(row => row.scope === 'account' && row.unit === report.unit
    && row.status === 'ok' && row.key_fingerprint === report.key_fingerprint
    && (Number.isFinite(row.remaining) || Number.isFinite(row.limit))) || null;
}

/** @param {Document} doc @param {import('./types.js').UsageProvider} provider */
function accountList(doc, provider) {
  const list = el(doc, 'ul', { class: 'account-list', 'aria-label': '账号用量' });
  for (const account of visibleAccounts(provider)) {
    const row = el(doc, 'li', { class: 'account-row', 'data-account': account.id });
    const summary = el(doc, 'div', { class: 'account-summary' });
    const identity = el(doc, 'div', { class: 'account-identity' });
    identity.append(el(doc, 'h3', { class: 'account-name' }, account.name),
      el(doc, 'p', { class: 'account-source' },
        ({ oauth: '浏览器登录', manual: '手动添加' })[account.source] || account.source || '未知来源'));
    summary.append(identity);
    if (provider.balance_supported) {
      identity.append(el(doc, 'p', { class: 'provider-note' }, quotaText(account.total)));
      summary.append(createMeter(doc, account.total, { label: `${account.name}剩余额度` }));
    }
    const keys = el(doc, 'ul', { class: 'account-keys', 'aria-label': `${account.name}的 Key` });
    for (const key of account.keys) {
      const keyRow = el(doc, 'li', { class: 'key-row' });
      const keyIdentity = el(doc, 'div', { class: 'key-identity' });
      keyIdentity.append(el(doc, 'span', { class: 'key-fingerprint' }, key.key_fingerprint));
      keyRow.append(keyIdentity);
      if (provider.balance_supported) {
        const shared = sharedTavilyAccount(provider, key.report);
        if (shared) {
          keyIdentity.append(el(doc, 'p', { class: 'key-kind' }, '共享账户余额 · 正常'));
          const details = [];
          if (Number.isFinite(key.report.limit) && key.report.limit !== shared.limit) {
            details.push(`Key 上限 ${amount(key.report.limit)} credits`);
          }
          if (Number.isFinite(key.report.used) && (key.report.used !== shared.used || details.length)) {
            details.push(`Key 已用 ${amount(key.report.used)} credits`);
          }
          if (details.length) keyIdentity.append(el(doc, 'p', { class: 'provider-note' }, details.join('；')));
        } else {
          keyIdentity.append(el(doc, 'p', { class: 'provider-note' }, quotaText(key.report)),
            el(doc, 'p', { class: 'key-kind' }, key.report
              ? `${scopeLabel(key.report.scope)}额度 · ${STATUSES[key.report.status] || '未知状态'}` : '余额未知（无缓存）'));
          keyRow.append(createMeter(doc, key.report, { label: `${key.key_fingerprint}剩余额度` }));
        }
      }
      keys.append(keyRow);
    }
    row.append(summary, keys);
    list.append(row);
  }
  return list;
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
  const body = el(doc, 'div', { 'data-body': '' });
  body.append(accountList(doc, provider));
  if (provider.balance_supported) {
    // Tavily key credits constrain the account pool; they are not another balance.
    const sharedKeys = new Set(provider.current.filter(row => sharedTavilyAccount(provider, row))
      .map(row => row.key_fingerprint));
    const separateBalance = row => !(row.scope === 'key' && row.unit === 'credits' && sharedKeys.has(row.key_fingerprint));
    const totals = provider.totals.filter(row => !(sharedKeys.size && row.scope === 'key' && row.unit === 'credits'));
    const history = provider.history.filter(separateBalance);
    const paces = provider.pace.filter(separateBalance);
    if (!provider.current.length) body.append(el(doc, 'p', {}, '暂无余额信息，数据不足。'));
    for (const status of new Set(provider.current.map(row => row.status))) {
      body.append(el(doc, 'p', { class: 'usage-status', 'data-kind': status }, STATUSES[status] || '未知状态'));
    }
    for (const total of totals) {
      body.append(el(doc, 'p', { class: 'provider-note', 'data-total': '' },
        `${scopeLabel(total.scope)}额度：${quotaText(total)}`));
      if (total.message) body.append(el(doc, 'p', { class: 'provider-note' }, total.message));
    }
    for (const report of provider.current) {
      const identity = provider.current.length > 1 ? `${report.key_fingerprint || '指纹未知'}：` : '';
      body.append(el(doc, 'p', { class: 'usage-note' },
        `${identity}重置时间：${timestamp(report.resets_at)}；更新时间：${timestamp(report.fetched_at)}`));
      if (report.message) body.append(el(doc, 'p', { class: 'usage-note' }, report.message));
    }
    if (!paces.length) body.append(el(doc, 'p', { class: 'usage-pace' }, '数据不足'));
    for (const pace of paces) {
      const identity = paces.length > 1
        ? `${pace.key_fingerprint || '指纹未知'}（${scopeLabel(pace.scope)} / ${unitLabel(pace.unit)}）：` : '';
      body.append(el(doc, 'p', { class: 'usage-pace' }, `${identity}${paceText(pace)}`));
    }
    const groups = new Map();
    for (const row of [...totals, ...history]) groups.set(JSON.stringify([row.scope, row.unit]), row);
    for (const { scope, unit } of groups.values()) body.append(chart(doc, history, scope, unit));
  } else {
    body.append(el(doc, 'p', { class: 'usage-status' }, '无余额接口'));
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
 * @param {{number?: string, signal?: AbortSignal, navigate?: (id: string) => void,
 *   usageRefresh?: ReturnType<typeof import('./usage-auto-refresh.js').createUsageAutoRefresh>}} [options]
 */
export async function mountUsage(root, api, { number = '05', signal, navigate, usageRefresh } = {}) {
  root = pageRoot(root);
  root.classList.add('usage-page');
  const doc = root.ownerDocument;
  root.innerHTML = `<p class="eyebrow visually-hidden"></p><h1 class="visually-hidden" tabindex="-1">用量</h1>
    <section class="usage-head" aria-label="用量刷新">
      <button type="button" class="primary" data-action="refresh-all">刷新全部</button>
      <p class="provider-note" data-updated role="status">最近更新：未知</p></section>
    <p class="error-message" data-error role="alert"></p>
    <p class="provider-note" data-notice role="status"></p>
    <div class="provider-list" data-providers></div>
    <p class="provider-note" data-footnote>刷新遵守服务商缓存时长。本机统计不等于服务商计费次数；历史只保留 30 天。</p>`;
  root.querySelector('.eyebrow').textContent = `${number} / USAGE`;
  const refreshAll = /** @type {HTMLButtonElement} */ (root.querySelector('[data-action="refresh-all"]'));
  const errorSlot = root.querySelector('[data-error]');
  const notice = root.querySelector('[data-notice]');
  const cards = new Map();
  let busy = false;
  let disposed = Boolean(signal?.aborted);
  let updatedAt = null;
  const updated = root.querySelector('[data-updated]');
  const updateTimestamp = () => {
    updated.textContent = `${usageRefresh ? '每10分钟自动刷新 · ' : ''}最近更新：${timestamp(updatedAt)}`;
  };
  updateTimestamp();

  function renderCard(provider) {
    let card = cards.get(provider.id);
    if (!card) {
      card = doc.createElement('details');
      card.className = 'provider-row';
      card.setAttribute('data-provider', provider.id);
      const head = el(doc, 'summary', { class: 'provider-summary' });
      const identity = el(doc, 'div', { class: 'provider-identity' });
      identity.append(el(doc, 'h2', { class: 'provider-name' }), el(doc, 'p', { class: 'provider-counts' }));
      const expand = el(doc, 'span', { class: 'provider-expand', 'aria-hidden': 'true' });
      expand.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m7 9 5 5 5-5"/></svg>';
      head.append(el(doc, 'span', { class: 'provider-icon', 'aria-hidden': 'true' }), identity,
        el(doc, 'div', { class: 'provider-meter' }), el(doc, 'span', { class: 'provider-status' }), expand);
      const details = el(doc, 'div', { class: 'provider-details' });
      const actions = el(doc, 'div', { class: 'provider-actions' });
      const refresh = el(doc, 'button', { type: 'button', 'data-action': 'refresh-provider' }, '刷新');
      const settings = el(doc, 'button', { type: 'button', 'data-action': 'settings' }, '去设置');
      refresh.addEventListener('click', () => { void load(provider.id); });
      settings.addEventListener('click', () => navigate?.('sources'));
      actions.append(refresh, settings);
      details.append(actions, el(doc, 'div', { 'data-body': '' }));
      card.append(head, details);
      cards.set(provider.id, card);
    }
    card.querySelector('.provider-icon').textContent = SOURCE_CATALOG.sources.find(source => source.plugin === provider.id)?.mark
      || provider.label.slice(0, 1);
    card.querySelector('.provider-name').textContent = provider.label;
    const accounts = visibleAccounts(provider);
    card.querySelector('.provider-counts').textContent =
      `${accounts.length} 个账号 · ${accounts.reduce((sum, account) => sum + account.keys.length, 0)} 个 Key`;
    const meter = card.querySelector('.provider-meter');
    const status = card.querySelector('.provider-status');
    meter.replaceChildren();
    status.replaceChildren();
    if (provider.balance_supported) {
      const total = createMeter(doc, provider.total, { label: `${provider.label}合计剩余额度` });
      // The summary has one reminder, selected by Core's alert priority.
      total.querySelector('.meter-state')?.remove();
      meter.append(total);
      const alert = createAlertBadge(doc, provider.alert);
      if (alert) status.append(alert);
      else {
        const reset = provider.current.map(row => row.resets_at).filter(value => Number.isFinite(Date.parse(value)))
          .sort((a, b) => Date.parse(a) - Date.parse(b))[0];
        status.textContent = provider.current.some(row => row.status === 'error') ? '查询失败'
          : !provider.current.length ? '数据不足' : `重置时间：${timestamp(reset)}`;
      }
    } else {
      const { search, scrape } = provider.calls.today;
      const today = typeof search === 'number' && typeof scrape === 'number' ? search + scrape : null;
      status.textContent = `无余额接口 · 今天调用 ${amount(today)} 次`;
    }
    card.querySelector('[data-action="refresh-provider"]').setAttribute('aria-label', `刷新 ${provider.label} 用量`);
    card.querySelector('[data-action="settings"]').setAttribute('aria-label', `${provider.label}：去设置`);
    card.querySelector('[data-body]').replaceWith(cardBody(doc, provider));
    const target = root.querySelector('[data-providers]');
    if (card.parentNode !== target) target.append(card);
  }

  function applyView(view, provider = null) {
    if (disposed) return;
    errorSlot.textContent = '';
    errorSlot.removeAttribute('title');
    const updateRequired = view.status === 'cli_update_required';
    notice.textContent = updateRequired ? (view.message || '请更新 CLI 后查看用量。')
      : view.usage_error || (!view.providers.length ? '暂无服务商用量信息。' : '');
    if (!provider || updateRequired) {
      updatedAt = null;
      const ids = new Set(updateRequired ? [] : view.providers.map(item => item.id));
      for (const [id, card] of cards) if (!ids.has(id)) card.remove();
    }
    if (!updateRequired) for (const item of view.providers) {
      renderCard(item);
      for (const report of item.current) {
        if (Number.isFinite(Date.parse(report.fetched_at))
          && (!updatedAt || Date.parse(report.fetched_at) > Date.parse(updatedAt))) updatedAt = report.fetched_at;
      }
    }
    updateTimestamp();
  }
  const unsubscribe = usageRefresh?.subscribe((view, provider) => applyView(view, provider));

  async function load(provider = null, refresh = true) {
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
      // The application owns automatic refreshes. Route entry reads the latest local cache;
      // explicit buttons retain the existing refresh=true behavior and Core's TTL.
      const view = /** @type {import('./types.js').UsageView} */ (await api.usageView(provider, refresh));
      applyView(view, provider);
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
    unsubscribe?.();
    disposePage(root);
  }
  signal?.addEventListener('abort', dispose, { once: true });
  refreshAll.addEventListener('click', () => { void load(); });
  await load(null, !usageRefresh);
  return { dispose };
}
