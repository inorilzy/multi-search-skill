// Legacy key migration panel. The CLI owns every rule; this page only shows masked previews,
// collects per-item confirmation and conflict choices, and sends source names back.
// It never receives or renders key values: the CLI returns masked previews and provider names only.

import { SEARCH_SOURCES } from './catalog.js';
import { showError } from './api.js';

const actionLabels = {
  migrate: '可迁移',
  already_current: '已是最新，无需迁移',
  conflict: '与凭据库中的 Key 冲突',
  unsupported: '不支持，保留在旧文件中',
  blocked: '无法检查，已跳过',
};

// The catalog is the only place that knows a key provider's public source name.
const providerSource = Object.fromEntries(SEARCH_SOURCES.map(source => [source.key_provider, source.name]));
const sourceOf = provider => providerSource[provider] || provider;

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
}

export async function mountMigration(root, api, { number = '08' } = {}) {
  root.innerHTML = `<section class="heading"><p class="eyebrow">${number} / LEGACY MIGRATION</p><h1 tabindex="-1">迁移旧 Key 文件。</h1>
    <p>只迁移单个 Key 的搜索源。多 Key 列表、Jina 及无法识别的条目会保留在旧文件中，不做任何改动。旧文件不会被删除。</p></section>
    <section class="panel"><div class="section-title"><h2>预览</h2><button type="button" data-action="preview">预览旧文件</button></div>
      <p data-info="error" role="alert"></p><div data-plan></div></section>`;

  const text = (selector, value) => { root.querySelector(selector).textContent = value; };
  let plan = null;
  let busy = false;
  let disposed = false;
  // Each preview owns a generation id. A late or out-of-order response only renders while it is
  // still the latest generation; anything older can never reactivate its plan or approvals.
  let generation = 0;
  const previewButton = root.querySelector('[data-action="preview"]');
  // One request at a time: while a preview or apply runs, both buttons are disabled and the
  // running one shows a loading label, so a double click cannot send a second migration.
  function setBusy(next, action) {
    busy = next;
    previewButton.disabled = next;
    previewButton.textContent = next && action === 'preview' ? '预览中…' : '预览旧文件';
    previewButton.setAttribute('aria-busy', String(next && action === 'preview'));
    const applyButton = root.querySelector('[data-action="apply"]');
    if (applyButton) {
      applyButton.disabled = next || plan === null || plan.store_supported !== true;
      applyButton.textContent = next && action === 'apply' ? '迁移中…' : '确认并迁移已选项';
      applyButton.setAttribute('aria-busy', String(next && action === 'apply'));
    }
  }

  function renderPlan(result) {
    plan = result;
    // Format compatibility is not executability: the CLI reports the plan, the
    // backend reports whether the encrypted store can write on this platform.
    const supported = result.store_supported === true;
    const rows = result.items.map(item => {
      const source = sourceOf(item.provider);
      // Without store support a "migrate" entry only matches the format; it is not executable.
      const label = !supported && item.action === 'migrate'
        ? '格式符合，当前平台不可执行'
        : (actionLabels[item.action] || item.action);
      const preview = item.preview ? `<code data-preview="${esc(source)}">${esc(item.preview)}</code>` : '';
      const detail = item.reason ? `<p class="note">${esc(item.reason)}</p>` : '';
      let control = '';
      if (supported && (item.action === 'migrate' || item.action === 'conflict')) {
        control = `<label><input type="checkbox" data-approve="${esc(source)}"> 确认迁移 ${esc(source)}</label>`;
      }
      if (supported && item.action === 'conflict') {
        control += `<label>冲突选择 <select data-choice="${esc(source)}">
          <option value="">请选择</option><option value="keep">保留凭据库中的 Key</option><option value="replace">用旧文件中的 Key 替换</option></select></label>`;
      }
      return `<li data-item="${esc(source)}"><strong>${esc(source)}</strong> ${esc(label)} ${preview} ${control} ${detail}</li>`;
    }).join('');
    // Format fit and executability are separate facts. Without store support the summary
    // reports only how many entries match the format, never that they can be migrated.
    const summary = supported
      ? `可迁移 ${result.migratable.length} 项；跳过 ${result.skipped.length} 项。`
      : `当前平台不可执行迁移：格式符合 ${result.migratable.length} 项；跳过 ${result.skipped.length} 项。`;
    const limitation = supported ? '' : `<p class="note" data-info="capability">预览仅展示旧文件格式分类。加密迁移写入仅支持 Windows 当前用户 DPAPI；当前平台无法执行迁移，旧文件不会被改动。</p>`;
    root.querySelector('[data-plan]').innerHTML = `<p data-info="summary">${esc(summary)}</p>${limitation}
      <ul data-items>${rows}</ul>
      <div class="run-controls"><button type="button" class="primary" data-action="apply" ${supported ? '' : 'disabled'}>确认并迁移已选项</button></div>
      <p data-info="result" role="status"></p>`;
    root.querySelector('[data-action="apply"]').addEventListener('click', apply);
  }

  function selections() {
    const approved = [];
    const choices = {};
    for (const box of root.querySelectorAll('[data-approve]')) {
      if (!box.checked) continue;
      const source = box.getAttribute('data-approve');
      approved.push(source);
      // No selector is built from a backend value: look the control up inside this row.
      const select = box.closest('li')?.querySelector('select[data-choice]');
      if (select && select.value) choices[source] = select.value;
    }
    return { approved, choices };
  }

  async function preview() {
    if (busy || disposed) return;
    // Starting a new preview immediately invalidates the previous plan and its approvals:
    // nothing from an earlier preview can be submitted while the query is in flight.
    generation += 1;
    const mine = generation;
    plan = null;
    root.querySelector('[data-plan]').replaceChildren();
    text('[data-info="error"]', '');
    setBusy(true, 'preview');
    try {
      const result = await api.migrationPlan();
      if (disposed || mine !== generation) return;
      renderPlan(result);
    } catch (error) {
      if (disposed || mine !== generation) return;
      // A failed preview keeps nothing committable and renders no success summary. The error
      // text comes from the backend code, so an unreadable or invalid file reads differently
      // from a capability or platform failure, and the preview button stays available.
      showError(root.querySelector('[data-info="error"]'), error, '无法预览旧文件，请检查 CLI 或文件。');
    } finally {
      if (!disposed && mine === generation) setBusy(false);
    }
  }

  async function apply() {
    if (!plan || busy || disposed || plan.store_supported !== true) return;
    const { approved, choices } = selections();
    const missingChoice = plan.items.find(item => item.action === 'conflict'
      && approved.includes(sourceOf(item.provider)) && !choices[sourceOf(item.provider)]);
    if (missingChoice) {
      text('[data-info="result"]', `请为 ${sourceOf(missingChoice.provider)} 选择保留或替换。`);
      return;
    }
    if (approved.length === 0) {
      text('[data-info="result"]', '未选择任何要迁移的项。');
      return;
    }
    setBusy(true, 'apply');
    text('[data-info="result"]', '迁移中…');
    try {
      const result = await api.migrationApply(plan.plan_token, approved, choices);
      if (disposed) return;
      const parts = [
        `已写入：${result.written.join('、') || '无'}`,
        `保留：${result.kept.join('、') || '无'}`,
        `未变化：${result.unchanged.join('、') || '无'}`,
        `失败：${result.failed.join('、') || '无'}`,
        `未完成：${result.not_done.join('、') || '无'}`,
      ];
      let message = result.complete ? `迁移完成。${parts.join('；')}` : `迁移未全部完成。${parts.join('；')}`;
      if (result.legacy_file_has_plaintext) {
        // The CLI never edits or deletes the source file; the key material stays there in plaintext.
        message += ` 旧文件仍含明文 Key：${result.legacy_file}。确认已迁移后请手动删除，或执行 chmod 600 收紧权限。`;
      }
      if (Array.isArray(result.warnings) && result.warnings.length > 0) {
        message += ` 提示：${result.warnings.join('；')}`;
      }
      text('[data-info="result"]', message);
      // A plan token is single-use; require a fresh preview before another apply.
      plan = null;
    } catch (error) {
      if (!disposed) showError(root.querySelector('[data-info="result"]'), error, '迁移未完成：旧文件或凭据库可能已变化，请重新预览。');
    } finally { if (!disposed) setBusy(false); }
  }

  previewButton.addEventListener('click', preview);
  return { dispose() { disposed = true; } };
}
