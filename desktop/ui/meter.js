// @ts-check
// Shared quota components for the usage and provider pages (T06/T07).
// createMeter(doc, total, { label?, thin? }) -> HTMLElement; percent is on a 0–100 scale.
// createAlertBadge(doc, kind, message?) -> HTMLElement | null; null/unknown kinds omit the badge.
// Components: .meter[.meter--thin][data-level=normal|low|critical|unknown], .meter-track,
// .meter-fill, .meter-value, .meter-relative, .meter-empty, .meter-state;
// .meter-alert[data-kind=low|critical|wont_last|needs_credential].
// Page structure: .provider-list > .provider-row > (.provider-summary + .provider-details).
// Summary cells: .provider-icon, .provider-identity (.provider-name, .provider-counts),
// .provider-meter, .provider-status, .provider-toggle.source-toggle (existing switch), .provider-expand (button).
// A summary may be a native <summary> in <details class="provider-row">; keep enable switches
// outside that summary. Otherwise use aria-expanded/aria-controls on .provider-expand and hidden
// on .provider-details. Row state: [open] or [data-expanded=true].
// Details: .provider-actions, .account-list > .account-row > (.account-summary + .account-keys).
// Account cells: .account-identity (.account-name, .account-source), .meter, .account-actions.
// Keys: .account-keys > .key-row > (.key-identity (.key-fingerprint, .key-kind), .meter, .key-actions).
// Editors/notes: .account-form, .provider-note. Actions wrap; all names may wrap without truncation.
import { el } from './dom.js';

const ALERTS = {
  low: '余额低',
  critical: '余额即将用尽',
  wont_last: '撑不到重置',
  needs_credential: '需要凭据',
};
const UNITS = { credits: 'credits', tokens: 'tokens', searches: '次搜索', usd: '美元', requests: '次请求' };
const finite = value => typeof value === 'number' && Number.isFinite(value);
const amount = value => value.toLocaleString('zh-CN', { maximumFractionDigits: 2 });

/**
 * Render a remaining quota without deriving history or combining different units/scopes.
 * A relative total supplies percent from Core's historical maximum, never an invented limit.
 * @param {Document} doc
 * @param {{remaining?: number|null, limit?: number|null, percent?: number|null,
 *   relative?: boolean, unit?: string|null}|null} [total]
 * @param {{label?: string, thin?: boolean}} [options]
 * @returns {HTMLElement}
 */
export function createMeter(doc, total = {}, { label = '剩余额度', thin = false } = {}) {
  total ??= {};
  const { remaining, limit, percent, relative = false, unit } = total;
  const raw = finite(percent) ? percent
    : finite(remaining) && finite(limit) && limit > 0 ? remaining / limit * 100 : null;
  const value = raw == null ? null : Math.max(0, Math.min(100, raw));
  const level = value == null ? 'unknown' : value < 5 ? 'critical' : value < 20 ? 'low' : 'normal';
  const root = el(doc, 'div', { class: `meter${thin ? ' meter--thin' : ''}`, 'data-level': level });
  const unitText = Object.hasOwn(UNITS, unit) ? UNITS[unit] : unit || '';
  const balance = finite(remaining) ? `${amount(remaining)}${unitText ? ` ${unitText}` : ''}` : '未知';
  const text = value == null || relative ? `剩余 ${balance}` : `${amount(value)}%`;
  root.append(el(doc, 'span', { class: 'meter-value' }, text));
  if (relative) root.append(el(doc, 'span', { class: 'meter-relative' }, '相对'));
  if (value == null) {
    root.append(el(doc, 'span', { class: 'meter-empty' }, '暂无上限'));
    return root;
  }
  const state = ALERTS[level] || '';
  const description = `${text}${relative ? `（相对值 ${amount(value)}%）` : ''}${state ? `，${state}` : ''}`;
  const track = el(doc, 'div', { class: 'meter-track', role: 'progressbar', 'aria-label': label,
    'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(value),
    'aria-valuetext': description });
  const fill = el(doc, 'span', { class: 'meter-fill' });
  fill.style.width = `${value}%`;
  track.append(fill);
  root.prepend(track);
  if (state) root.append(el(doc, 'span', { class: 'meter-state' }, state));
  return root;
}

/**
 * The caller selects the highest-priority alert; external messages remain literal text.
 * @param {Document} doc
 * @param {string|null|undefined} kind
 * @param {string} [message]
 * @returns {HTMLElement|null}
 */
export function createAlertBadge(doc, kind, message) {
  if (!Object.hasOwn(ALERTS, kind)) return null;
  return el(doc, 'span', { class: 'meter-alert', 'data-kind': kind, role: 'status' }, message || ALERTS[kind]);
}
