// Provider balance panel for the 「搜索源与凭据」 page. The numbers come from the managed
// CLI (`balance --format json`); this module only renders them and never contacts a provider.
import { showError } from './api.js';
import { SOURCE_CATALOG } from './source-catalog.js';

const UNIT_LABELS = { credits: 'credits', tokens: 'tokens', searches: '次搜索', usd: '美元', requests: '次请求' };
const STATUS_LABELS = { ok: '正常', unsupported: '不支持余额查询', needs_credential: '需要凭据', error: '查询失败' };
const SCOPE_LABELS = { key: 'Key', team: '团队', account: '账户' };
const REFRESH_LABEL = '刷新余额';

/** Map a UI source name to the plugin id the balance CLI accepts. */
export function providerForSource(source) {
  const entry = SOURCE_CATALOG.sources.find(item => item.name === source);
  if (entry?.plugin) return entry.plugin;
  const plugin = SOURCE_CATALOG.plugins.find(item =>
    item.search_sources.includes(source) || item.scrape_channels.includes(source));
  return plugin?.id || source;
}

/** A null/unknown amount is never shown as zero. */
export function formatAmount(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
}

/** Deterministic UTC display, so the value does not depend on the machine time zone. */
export function formatTimestamp(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const pad = number => String(number).padStart(2, '0');
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} `
    + `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`;
}

const statusLabel = status => STATUS_LABELS[status] || status || '未知状态';

function reportRow(doc, report) {
  const row = doc.createElement('div');
  row.className = 'balance-row';
  row.dataset.kind = report.status;
  const status = doc.createElement('span');
  status.className = 'balance-status';
  status.textContent = statusLabel(report.status);
  const head = doc.createElement('div');
  head.className = 'balance-row-head';
  const title = doc.createElement('strong');
  const scope = SCOPE_LABELS[report.scope] || report.scope;
  title.textContent = scope ? `${scope}额度` : '额度';
  head.append(title, status);
  row.append(head);
  if (report.status === 'ok') {
    const values = doc.createElement('dl');
    values.className = 'balance-values';
    const pairs = [
      ['剩余', formatAmount(report.remaining)],
      ['上限', formatAmount(report.limit)],
      ['单位', UNIT_LABELS[report.unit] || report.unit || '—'],
      ['重置时间', formatTimestamp(report.resets_at)],
      ['更新时间', formatTimestamp(report.fetched_at)],
    ];
    for (const [name, value] of pairs) {
      const term = doc.createElement('dt');
      term.textContent = name;
      const detail = doc.createElement('dd');
      detail.textContent = value;
      values.append(term, detail);
    }
    row.append(values);
    if (report.message) {
      const message = doc.createElement('p');
      message.className = 'balance-message';
      message.textContent = report.message;
      row.append(message);
    }
  } else {
    const message = doc.createElement('p');
    message.className = 'balance-message';
    message.textContent = report.message || '暂无更多说明。';
    row.append(message);
    if (report.fetched_at) {
      const time = doc.createElement('p');
      time.className = 'balance-time';
      time.textContent = `更新时间：${formatTimestamp(report.fetched_at)}`;
      row.append(time);
    }
  }
  return row;
}

/**
 * Mount the balance panel for one plugin. The panel is omitted entirely when the injected API
 * predates `balanceView` (older tests and call sites); production always passes it.
 * @param {HTMLElement} root
 * @param {any} api
 * @param {{ provider?: string, source?: string, label?: string }} [options]
 */
export async function mountBalance(root, api, { provider, source, label } = {}) {
  const pluginId = provider || (source ? providerForSource(source) : '');
  if (!pluginId || typeof api?.balanceView !== 'function') {
    root.replaceChildren();
    root.hidden = true;
    return { dispose() {}, reload: async () => {} };
  }
  const doc = root.ownerDocument;
  root.hidden = false;
  const escaped = String(label ?? pluginId).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[ch]);
  root.innerHTML = `<section class="balance-block" aria-label="${escaped} 余额">
    <div class="balance-head"><div><h3>余额</h3><p class="balance-sub">余额与额度来自本机 CLI，可手动刷新。</p></div><button type="button" data-action="refresh-balance">${REFRESH_LABEL}</button></div>
    <div class="balance-rows" data-balance-rows aria-live="polite">正在读取余额…</div>
    <p class="error-message" data-info="balance-error" role="alert"></p></section>`;
  const q = selector => /** @type {any} */ (root.querySelector(selector));
  let disposed = false;
  let busy = false;
  let generation = 0;
  function render(view) {
    const plugin = view?.providers?.find(item => item.id === pluginId) || view?.providers?.[0];
    const rows = q('[data-balance-rows]');
    rows.replaceChildren();
    if (!plugin) {
      rows.textContent = '未找到该服务商的余额信息。';
      return;
    }
    if (!Array.isArray(plugin.reports) || plugin.reports.length === 0) {
      rows.textContent = plugin.balance_note || '暂无余额信息。';
      return;
    }
    for (const report of plugin.reports) rows.append(reportRow(doc, report));
  }
  async function load(refresh) {
    if (disposed) return;
    const ticket = ++generation;
    busy = true;
    root.setAttribute('aria-busy', 'true');
    q('[data-action="refresh-balance"]').disabled = true;
    q('[data-action="refresh-balance"]').textContent = '刷新中…';
    const errorSlot = q('[data-info="balance-error"]');
    errorSlot.textContent = '';
    errorSlot.title = '';
    try {
      const view = await api.balanceView(pluginId, refresh);
      if (disposed || ticket !== generation) return;
      render(view);
    } catch (error) {
      if (!disposed && ticket === generation) {
        showError(errorSlot, error, '余额读取失败，请重试。');
      }
    } finally {
      if (!disposed && ticket === generation) {
        busy = false;
        root.setAttribute('aria-busy', 'false');
        q('[data-action="refresh-balance"]').disabled = false;
        q('[data-action="refresh-balance"]').textContent = REFRESH_LABEL;
      }
    }
  }
  q('[data-action="refresh-balance"]').addEventListener('click', () => {
    if (!busy) void load(true);
  });
  await load(false);
  return {
    reload: load,
    dispose() {
      disposed = true;
      generation += 1;
      root.replaceChildren();
      root.hidden = true;
    },
  };
}
