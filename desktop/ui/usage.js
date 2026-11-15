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

const finite = value => typeof value === 'number' && Number.isFinite(value);
const hasQuota = row => row && [row.remaining, row.limit, row.used].some(finite);
const visibleAccounts = provider => provider.accounts.filter(account =>
  account.id !== 'default' || account.keys.length);

// Fingerprints remain grouping keys; presentation names also cover old, inactive keys.
function labelsFor(provider) {
  const replacements = new Map();
  const keys = new Map();
  for (const account of provider.accounts) for (const key of account.keys) {
    if (!keys.has(key.key_fingerprint)) keys.set(key.key_fingerprint, `Key ${keys.size + 1}`);
  }
  for (const [fingerprint, label] of keys) replacements.set(fingerprint, label);
  provider.accounts.forEach((account, index) => {
    if (account.id !== 'default') replacements.set(account.id, `账号 ${index + 1}`);
  });
  const historical = new Map();
  const pools = new Map();
  const label = row => {
    if (row.scope === 'key') {
      if (keys.has(row.key_fingerprint)) return keys.get(row.key_fingerprint);
      if (!historical.has(row.key_fingerprint)) historical.set(row.key_fingerprint, `历史 Key ${historical.size + 1}`);
      return historical.get(row.key_fingerprint);
    }
    const kind = row.scope === 'team' ? '团队额度' : '账户余额';
    const group = JSON.stringify([row.scope, row.key_fingerprint]);
    if (!pools.has(group)) {
      const count = [...pools.values()].filter(value => value.startsWith(kind)).length;
      pools.set(group, `${kind} ${count + 1}`);
    }
    return pools.get(group);
  };
  for (const row of [...provider.current, ...provider.history, ...provider.pace]) {
    const name = label(row);
    if (row.key_fingerprint && !replacements.has(row.key_fingerprint)) replacements.set(row.key_fingerprint, name);
  }
  const text = value => safeText(value, replacements);
  return { label, text, key: fingerprint => keys.get(fingerprint),
    account: (account, index) => account.id === 'default' ? '独立 Key'
      : text(account.name).trim() || `账号 ${index + 1}` };
}

function safeText(value, replacements = new Map()) {
  let text = String(value ?? '');
  for (const [identity, label] of [...replacements].sort((a, b) => b[0].length - a[0].length)) {
    if (identity) text = text.split(identity).join(label);
  }
  return text.replace(/\bsha256\b(?:\s*:\s*[a-z0-9_-]+)?/gi, 'Key')
    .replace(/\bfingerprint\b(?:\s*[:=]\s*[a-z0-9_-]+)?/gi, 'Key')
    .replace(/\boauth-login(?:[-_:][a-z0-9_-]+)?\b/gi, '浏览器登录')
    .replace(/\bacc_[a-z0-9_-]+\b/gi, '账号');
}

function quotaText(row, text = safeText) {
  const parts = [];
  if (finite(row?.remaining)) parts.push(`剩余 ${amount(row.remaining)}`);
  if (finite(row?.limit)) parts.push(`上限 ${amount(row.limit)}`);
  if (!parts.length && finite(row?.used)) parts.push(`已用 ${amount(row.used)}`);
  const unit = row?.unit ? ` ${text(unitLabel(row.unit))}` : '';
  return parts.length ? `${parts.join(' / ')}${unit}` : '额度暂不可查询';
}

function quotaMeter(doc, row, label, text = safeText) {
  const meter = createMeter(doc, { ...row, unit: text(row?.unit) }, { label, thin: true });
  meter.querySelectorAll('.meter-value, .meter-empty, .meter-state').forEach(node => node.remove());
  return meter.querySelector('[role="progressbar"]') ? meter : null;
}

/** @param {import('./types.js').UsageProvider} provider @param {import('./types.js').BalanceReport} report */
function sharedTavilyAccount(provider, report) {
  if (provider.id !== 'tavily' || report?.scope !== 'key' || report.unit !== 'credits'
    || report.status !== 'ok' || !report.key_fingerprint) return null;
  return provider.current.find(row => row.scope === 'account' && row.unit === report.unit
    && row.status === 'ok' && row.key_fingerprint === report.key_fingerprint
    && (finite(row.remaining) || finite(row.limit))) || null;
}

/** @param {Document} doc @param {import('./types.js').UsageProvider} provider */
function accountList(doc, provider, labels) {
  const list = el(doc, 'ul', { class: 'account-list', 'aria-label': '账号与 Key 用量' });
  for (const [index, account] of visibleAccounts(provider).entries()) {
    const standalone = account.id === 'default';
    const name = labels.account(account, index);
    const row = el(doc, 'li', { class: 'account-row', 'data-account': account.id,
      'data-standalone': String(standalone) });
    const summary = el(doc, 'div', { class: 'account-summary' });
    const identity = el(doc, 'div', { class: 'account-identity' });
    identity.append(el(doc, 'h3', { class: 'account-name' }, name));
    summary.append(identity);
    if (!standalone && provider.balance_supported && hasQuota(account.total)) {
      identity.append(el(doc, 'p', { class: 'quota-value' }, quotaText(account.total, labels.text)));
      const meter = quotaMeter(doc, account.total, `${name}剩余额度`, labels.text);
      if (meter) summary.append(meter);
    } else if (!standalone && !account.keys.length) {
      identity.append(el(doc, 'p', { class: 'quota-value' }, provider.balance_supported ? '额度暂不可查询' : '未提供额度'));
    }
    const keys = el(doc, 'ul', { class: 'account-keys', 'aria-label': standalone ? name : `${name}的 Key` });
    for (const key of account.keys) {
      const keyName = labels.key(key.key_fingerprint);
      const keyRow = el(doc, 'li', { class: 'key-row', 'data-fingerprint': key.key_fingerprint });
      const keyIdentity = el(doc, 'div', { class: 'key-identity' });
      keyIdentity.append(el(doc, 'span', { class: 'key-label' }, keyName));
      keyRow.append(keyIdentity);
      const reports = new Map();
      if (provider.balance_supported) for (const report of [key.report, ...provider.current.filter(report =>
        report.scope === 'key' && report.key_fingerprint === key.key_fingerprint)]) {
        if (!report) continue;
        const group = JSON.stringify([report.scope, report.unit]);
        if (!reports.has(group) || (!hasQuota(reports.get(group)) && hasQuota(report))) reports.set(group, report);
      }
      const known = [...reports.values()].filter(hasQuota);
      for (const report of known.length ? known : [[...reports.values()][0] || null]) {
        const shared = sharedTavilyAccount(provider, report);
        const usesAccount = !standalone && report?.scope !== 'key' && hasQuota(account.total)
          && report?.unit === account.total.unit && report?.remaining === account.total.remaining
          && report?.limit === account.total.limit;
        if (shared || usesAccount) {
          if (standalone || (shared && (!hasQuota(account.total) || account.total.unit !== shared.unit))) {
            keyIdentity.append(el(doc, 'p', { class: 'quota-value' }, quotaText(shared, labels.text)));
            const meter = quotaMeter(doc, shared, `${keyName}账户剩余额度`, labels.text);
            if (meter) keyRow.append(meter);
          } else keyIdentity.append(el(doc, 'span', { class: 'key-kind' }, shared ? '共享账户余额' : '使用账号额度'));
          const details = [];
          if (shared && finite(report.limit) && report.limit !== shared.limit) details.push(`Key 上限 ${amount(report.limit)} credits`);
          if (shared && finite(report.used) && (report.used !== shared.used || details.length)) {
            details.push(`Key 已用 ${amount(report.used)} credits`);
          }
          if (details.length) keyIdentity.append(el(doc, 'p', { class: 'quota-value key-quota' }, details.join('；')));
        } else {
          keyIdentity.append(el(doc, 'p', { class: 'quota-value' }, provider.balance_supported
            ? quotaText(report, labels.text) : '未提供额度'));
          const meter = report && quotaMeter(doc, report, `${keyName}剩余额度`, labels.text);
          if (meter) keyRow.append(meter);
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
function chart(doc, history, scope, unit, labels) {
  const figure = el(doc, 'figure', { class: 'usage-chart' });
  const label = labels.text(`近 30 天剩余走势 · ${scopeLabel(scope)} · ${unitLabel(unit)}`);
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
  for (const rows of series.values()) {
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
      description.textContent = `${labels.label(point)}：${timestamp(point.fetched_at)}，剩余 ${amount(point.remaining)}`;
      dot.append(description);
      svg.append(dot);
    }
    line();
    legend.append(el(doc, 'li', {}, `${labels.label(rows[0])}：${['实线', '虚线', '点线'][(index - 1) % 3]}`));
  }
  figure.append(svg, el(doc, 'p', { class: 'usage-chart-range' },
    `${timestamp(points[0].fetched_at)} 至 ${timestamp(points.at(-1).fetched_at)}；范围 ${amount(min)}–${amount(max)}`));
  if (series.size > 1) figure.append(legend);
  return figure;
}

/** @param {Document} doc @param {import('./types.js').UsageProvider} provider */
function cardBody(doc, provider, labels) {
  const body = el(doc, 'div', { 'data-body': '' });
  body.append(accountList(doc, provider, labels));
  const extra = el(doc, 'details', { class: 'usage-extra' });
  const more = el(doc, 'div', { class: 'usage-extra-body' });
  extra.append(el(doc, 'summary', {}, '趋势与明细'), more);
  const messages = new Set();
  const note = (target, message, className = 'usage-note') => {
    const text = labels.text(message).trim();
    if (!text || messages.has(text)) return;
    messages.add(text);
    target.append(el(doc, 'p', { class: className }, text));
  };
  if (provider.balance_supported) {
    // A shared Tavily report is paired by fingerprint and unit, never by a provider-wide total.
    const sharedKeys = new Set(provider.current.filter(row => sharedTavilyAccount(provider, row))
      .map(row => row.key_fingerprint));
    const separateBalance = row => !(row.scope === 'key' && row.unit === 'credits' && sharedKeys.has(row.key_fingerprint));
    const history = provider.history.filter(separateBalance);
    const paces = provider.pace.filter(separateBalance);
    for (const report of provider.current) {
      const failed = report.status === 'error' || report.status === 'needs_credential';
      if (failed) note(body, report.message || STATUSES[report.status], 'usage-error error-message');
      else if (report.message) note(more, report.message);
    }
    for (const total of provider.totals) if (total.message) note(more, total.message);
    for (const report of provider.current.filter(separateBalance)) {
      const times = [];
      if (Number.isFinite(Date.parse(report.resets_at))) times.push(`重置时间：${timestamp(report.resets_at)}`);
      if (Number.isFinite(Date.parse(report.fetched_at))) times.push(`最近更新：${timestamp(report.fetched_at)}`);
      if (times.length) more.append(el(doc, 'p', { class: 'usage-note usage-time' },
        `${labels.label(report)}：${times.join('；')}`));
    }
    if (!paces.length) more.append(el(doc, 'p', { class: 'usage-pace' }, '数据不足'));
    for (const pace of paces) {
      const identity = paces.length > 1 ? `${labels.label(pace)}（${unitLabel(pace.unit)}）：` : '';
      more.append(el(doc, 'p', { class: 'usage-pace' }, labels.text(`${identity}${paceText(pace)}`)));
    }
    const groups = new Map();
    for (const row of history) groups.set(JSON.stringify([row.scope, row.unit]), row);
    for (const { scope, unit } of groups.values()) more.append(chart(doc, history, scope, unit, labels));
  } else {
    note(more, provider.balance_note || provider.current.find(row => row.message)?.message || '该服务商未提供余额查询接口。');
  }
  const calls = el(doc, 'dl', { class: 'usage-calls' });
  /** @type {Array<[string, import('./types.js').UsageCallCounts]>} */
  const periods = [['今天', provider.calls.today], ['近 7 天', provider.calls.last_7_days]];
  for (const [label, counts] of periods) {
    calls.append(el(doc, 'dt', {}, `本机调用 · ${label}`), el(doc, 'dd', {},
      `搜索 ${amount(counts.search)} 次，抓取 ${amount(counts.scrape)} 次，失败 ${amount(counts.failures)} 次`));
  }
  more.append(calls);
  body.append(extra);
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
  let userText = safeText;
  const updated = root.querySelector('[data-updated]');
  const updateTimestamp = () => {
    updated.textContent = `${usageRefresh ? '每10分钟自动刷新 · ' : ''}最近更新：${timestamp(updatedAt)}`;
  };
  updateTimestamp();

  function renderCard(provider) {
    const labels = labelsFor(provider);
    const providerName = labels.text(provider.label);
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
      || providerName.slice(0, 1);
    card.querySelector('.provider-name').textContent = providerName;
    const accounts = visibleAccounts(provider);
    const accountCount = accounts.filter(account => account.id !== 'default').length;
    const keyCount = accounts.reduce((sum, account) => sum + account.keys.length, 0);
    card.querySelector('.provider-counts').textContent = accountCount
      ? `${accountCount} 个账号 · ${keyCount} 个 Key` : `${keyCount} 个独立 Key`;
    const meter = card.querySelector('.provider-meter');
    const status = card.querySelector('.provider-status');
    meter.replaceChildren();
    status.replaceChildren();
    if (provider.balance_supported) {
      if (hasQuota(provider.total)) {
        const total = createMeter(doc, { ...provider.total, unit: labels.text(provider.total.unit) },
          { label: `${providerName}合计剩余额度` });
        // The summary has one reminder, selected by Core's alert priority.
        total.querySelectorAll('.meter-state, .meter-empty').forEach(node => node.remove());
        if (!finite(provider.total.remaining)) total.querySelector('.meter-value').textContent = quotaText(provider.total, labels.text);
        meter.append(total);
      }
      const alert = createAlertBadge(doc, provider.alert,
        provider.alert === 'needs_credential' && finite(provider.total.remaining) ? '部分额度未提供' : undefined);
      if (alert) status.append(alert);
      else {
        const reset = provider.current.map(row => row.resets_at).filter(value => Number.isFinite(Date.parse(value)))
          .sort((a, b) => Date.parse(a) - Date.parse(b))[0];
        status.textContent = provider.current.some(row => row.status === 'error') ? '查询失败'
          : reset ? `重置时间：${timestamp(reset)}` : '';
      }
    } else {
      const { search, scrape } = provider.calls.today;
      const today = finite(search) && finite(scrape) ? search + scrape : null;
      status.textContent = today == null ? '未提供额度' : `今天调用 ${amount(today)} 次`;
    }
    card.querySelector('[data-action="refresh-provider"]').setAttribute('aria-label', `刷新 ${providerName} 用量`);
    card.querySelector('[data-action="settings"]').setAttribute('aria-label', `${providerName}：去设置`);
    const previousExtra = card.querySelector('.usage-extra');
    const focused = /** @type {HTMLElement|null} */ (doc.activeElement);
    const body = cardBody(doc, provider, labels);
    if (previousExtra) {
      previousExtra.querySelector('.usage-extra-body').replaceWith(body.querySelector('.usage-extra-body'));
      body.querySelector('.usage-extra').replaceWith(previousExtra);
    }
    card.querySelector('[data-body]').replaceWith(body);
    if (focused && previousExtra?.contains(focused)) focused.focus();
    const target = root.querySelector('[data-providers]');
    if (card.parentNode !== target) target.append(card);
  }

  function applyView(view, provider = null) {
    if (disposed) return;
    errorSlot.textContent = '';
    errorSlot.removeAttribute('title');
    const labelSets = view.providers.map(labelsFor);
    userText = value => safeText(labelSets.reduce((text, labels) => labels.text(text), String(value ?? '')));
    const updateRequired = view.status === 'cli_update_required';
    notice.textContent = userText(updateRequired ? (view.message || '请更新 CLI 后查看用量。')
      : view.usage_error || (!view.providers.length ? '暂无服务商用量信息。' : ''));
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
      if (!disposed) {
        showError(errorSlot, error, '用量读取失败，请重试。');
        errorSlot.textContent = userText(errorSlot.textContent);
        if (errorSlot.hasAttribute('title')) errorSlot.setAttribute('title', userText(errorSlot.getAttribute('title')));
      }
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
