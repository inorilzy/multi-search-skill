// Unified IPC boundary. This module is the only place where a backend rejection is turned into
// display text and the only place where an invoke result is shape-checked.
//
// Errors: the backend rejects every command with a serialized `{ code, message }` object (see
// src/errors.rs). `normalizeError` parses that shape, maps known codes onto Chinese UI text, and
// falls back to the backend's Chinese message or a generic fallback for anything else — an English
// worker name or enum never reaches the user. All rejection values (string, Error, {code,message},
// unknown objects) go through here.
//
// Payloads: every declared result is run through `expect(TypeName, value)` from `./payloads.js`, so
// a malformed backend response fails at the boundary instead of corrupting page state. A violation
// is reported as an `IpcError` with code `INVALID_PAYLOAD` and a Chinese message.
//
// No call carries an executable path: the backend always runs the managed CLI (then PATH).

import { expect } from './payloads.js';

const ERROR_MESSAGES = {
  cli_detect_failed: 'CLI 检测失败，请重新检测。',
  search_start_failed: '启动搜索的工作器失败，请重试。',
  execution_poll_failed: '执行状态读取失败，请稍后重试或取消本次执行。',
  execution_cancel_failed: '执行取消工作器失败，请重试。',
  skill_plan_failed: 'Skill 预览失败，请重试。',
  skill_install_failed: 'Skill 安装工作器失败，请重新预览。',
  install_plan_failed: '安装计划检查失败，请重新检查。',
  install_failed: '安装工作器失败，请重新检查。',
  update_failed: '更新工作器失败，请重新检查。',
  uninstall_failed: '卸载工作器失败，请重新检查。',
  user_path_check_failed: 'PATH 检查失败，请重新检查。',
  user_path_change_failed: 'PATH 修改失败，请重新检查；原有或被修改项目会保留。',
  credential_status_failed: '凭据状态读取失败，请重试。',
  credential_read_failed: '已保存凭据读取失败，请重试。',
  credential_reveal_failed: '凭据显示失败，请重试。',
  credential_save_failed: '凭据保存失败，请检查凭据库访问后重试。',
  credential_append_failed: '凭据保存失败，已输入的 Key 仍保留在编辑框中。',
  credential_remove_failed: '凭据删除失败，已保存的值没有改变。',
  credential_delete_failed: '凭据删除失败，请重试。',
  credential_test_failed: '凭据测试启动失败，请检查 CLI 后重试。',
  credential_application_failed: '无法打开系统浏览器，请手动访问服务商页面。',
  cookie_status_failed: 'Cookie 托管状态读取失败，请重试。',
  cookie_import_failed: 'Cookie 导入失败，原文件与已有的托管 Cookie 都没有改动。',
  cookie_delete_failed: 'Cookie 删除失败，仍保持托管模式，不会回退到旧文件。',
  scrape_settings_save_failed: '抓取设置保存失败，原配置未改变。',
  rerank_key_save_failed: '重排 API 密钥保存失败，原密钥文件未改变。',
  scrape_memory_view_failed: '站点抓取记忆读取失败，请重试。',
  scrape_memory_pin_failed: '固定的抓取后端没有保存，请重试。',
  scrape_memory_reset_failed: '站点抓取记忆清除失败，请重试。',
  provider_list_failed: '搜索源清单读取失败，请重试。',
  migration_plan_failed: '迁移预览失败，请检查 CLI 或旧文件。',
  migration_apply_failed: '迁移执行失败，请重新预览。',
  settings_view_failed: '设置读取失败，请重新读取。',
  settings_save_failed: '设置保存失败，原配置未改变。',
  skill_status_failed: 'Skill 状态检查失败，请重试。',
  skill_update_failed: 'Skill 更新失败，请重新检查。',
  skill_remove_plan_failed: 'Skill 移除预览失败，请重试。',
  skill_remove_failed: 'Skill 移除失败，请重新检查目标。',
  legacy_keys_file_missing: '无法定位旧 key 文件。',
  cli_not_verified: '请先安装并验证受管 CLI。',
  // A backend payload that does not match the declared contract. Never actionable by the user.
  INVALID_PAYLOAD: '界面收到的数据格式不符合约定，请更新应用后重试。',
  // A call refused before it reached the backend (missing confirmation, empty site, …).
  INVALID_ARGUMENT: '请求参数无效，未发送到后台。',
};

const DEFAULT_FALLBACK = '操作失败，请重试。';

export class IpcError extends Error {
  /**
   * @param {string} code
   * @param {string} message display-ready Chinese text
   * @param {string} [detail] raw backend reason, kept out of the visible text
   */
  constructor(code, message, detail) {
    super(message);
    this.name = 'IpcError';
    this.code = code;
    this.detail = detail;
  }
}

/**
 * Error raised at this boundary. `code` is the backend code when there is one, else the caller's
 * fallback code (`IPC_ERROR`, `INVALID_PAYLOAD`, …). The visible `message` is always Chinese.
 */
export class ApiError extends IpcError {
  /** @param {unknown} cause @param {string} [code] */
  constructor(cause, code = 'IPC_ERROR') {
    const normalized = normalizeError(cause, DEFAULT_FALLBACK);
    // A backend code wins; otherwise the boundary's own code supplies the Chinese text.
    const own = normalized.code === 'unknown';
    super(own ? code : normalized.code, own && ERROR_MESSAGES[code] ? ERROR_MESSAGES[code] : normalized.message, normalized.detail);
    this.name = 'ApiError';
    this.cause = cause;
  }
}

/// Parse any IPC rejection into an IpcError: `message` is display-ready Chinese for known
/// codes; `detail` keeps the raw reason (never shown unless it is already Chinese).
export function normalizeError(error, fallback = DEFAULT_FALLBACK) {
  if (error == null) return new IpcError('unknown', fallback, '');
  if (error instanceof IpcError) return error;
  let code = '';
  let message = '';
  let detail = '';
  if (typeof error === 'string') {
    try {
      const parsed = JSON.parse(error);
      if (parsed && typeof parsed === 'object' && typeof parsed.code === 'string') {
        code = parsed.code;
        message = typeof parsed.message === 'string' ? parsed.message : '';
        detail = message;
      }
    } catch { /* plain string reason */ }
    if (!code) detail = error;
  } else if (typeof error === 'object') {
    if (typeof error.code === 'string') code = error.code;
    if (typeof error.message === 'string') message = error.message;
    detail = message || String(error.detail || '');
    if (!code && !detail) {
      try { detail = JSON.stringify(error); } catch { detail = ''; }
    }
  } else {
    detail = String(error);
  }
  const looksChinese = value => /[\u4e00-\u9fff]/.test(value);
  const mapped = ERROR_MESSAGES[code];
  const text = mapped || (looksChinese(detail) ? detail : looksChinese(message) ? message : fallback);
  return new IpcError(code || 'unknown', text, detail || message);
}

/// Shorthand kept for call sites that only want the display text.
export function errorReason(error, fallback = '未知错误') {
  return normalizeError(error, fallback).message;
}

/// Show a normalized IPC error on an element, keeping the raw reason in the title for support.
export function showError(node, error, fallback) {
  const normalized = normalizeError(error, fallback);
  node.textContent = normalized.message;
  if (normalized.detail && normalized.detail !== normalized.message) node.title = normalized.detail;
  return normalized;
}

/**
 * Wrap a Tauri `invoke` function so that:
 *   1. every rejection becomes an IpcError (one normalization entry), and
 *   2. every result declared with a payload type is validated by `expect` before a page sees it.
 * @param {(cmd: string, args?: Record<string, unknown>) => Promise<unknown>} invoke
 */
export function managementApi(invoke) {
  /**
   * @param {string} command
   * @param {Record<string, unknown>} [args]
   * @param {keyof import('./contract-map').ContractMap} [typeName] payload contract checked by `expect`
   * @returns {Promise<any>}
   */
  async function call(command, args, typeName) {
    let result;
    try {
      result = await invoke(command, args);
    } catch (error) {
      throw error instanceof IpcError ? error : normalizeError(error);
    }
    if (!typeName) return result;
    try {
      return expect(typeName, result);
    } catch (error) {
      throw new ApiError(error, 'INVALID_PAYLOAD');
    }
  }
  return {
    // No call carries an executable path: the backend always runs the managed CLI (then PATH).
    detect: () => call('detect_cli', undefined, 'CliStatus'),
    start: async options => {
      const id = await call('start_test_search', { options });
      if (typeof id !== 'number' || !Number.isFinite(id)) {
        throw new ApiError(new TypeError('IPC payload for start_test_search expected a numeric execution id'), 'INVALID_PAYLOAD');
      }
      return id;
    },
    poll: id => call('poll_execution', { id }, 'ExecutionStatus'),
    cancel: id => call('cancel_test_search', { id }, 'ExecutionStatus'),
    skillPlan: (scope, project) => call('skill_plan', { scope, project }, 'SkillPlan'),
    skillInstall: (scope, project) => call('skill_install', { scope, project }, 'SkillInstall'),
    skillStatus: (scope, project) => call('skill_status', { scope, project }, 'SkillStatus'),
    skillUpdate: (scope, project, confirmOverwrite) => call('skill_update', { scope, project, confirmOverwrite }, 'UpdateOutcome'),
    skillRemovePlan: (scope, project) => call('skill_remove_plan', { scope, project }, 'RemovePlan'),
    skillRemove: (scope, project, confirmed) => call('skill_remove', { scope, project, confirmed }, 'RemoveOutcome'),
    installPlan: () => call('install_plan', undefined, 'InstallPlan'),
    install: () => call('install_cli', undefined, 'InstallOutcome'),
    update: () => call('update_cli', undefined, 'InstallOutcome'),
    uninstall: () => call('uninstall_cli', undefined, 'InstallOutcome'),
    userPathPlan: () => call('user_path_plan', undefined, 'PathPlan'),
    userPathChange: (remove, confirmed) => call('user_path_change', { remove, confirmed }, 'PathPlan'),
    credentialStatus: source => call('credential_status', { source }, 'CredentialOverview'),
    credentialRead: source => call('credential_read', { source }, 'CredentialValue'),
    credentialReveal: source => call('credential_reveal', { source }, 'CredentialValue'),
    credentialApplicationOpen: source => call('credential_application_open', { source }),
    credentialSave: (source, key) => call('credential_save', { source, key }, 'CredentialOverview'),
    credentialAppend: (source, keys) => call('credential_append', { source, keys }, 'CredentialOverview'),
    credentialRemove: (source, index, expected) => call('credential_remove', { source, index, expected }, 'CredentialOverview'),
    credentialDelete: source => call('credential_delete', { source }, 'CredentialOverview'),
    credentialTest: source => call('credential_test', { source }, 'TestOutcome'),
    cookieStatus: () => call('cookie_status', undefined, 'CookieStatus'),
    cookieImport: async (path, confirmed) => {
      if (confirmed !== true || typeof path !== 'string' || !path.trim()) {
        throw new ApiError(new TypeError('Cookie 导入需要路径和显式确认。'), 'INVALID_ARGUMENT');
      }
      return call('cookie_import', { path, confirmed }, 'CookieStatus');
    },
    cookieDelete: async confirmed => {
      if (confirmed !== true) throw new ApiError(new TypeError('Cookie 删除需要显式确认。'), 'INVALID_ARGUMENT');
      return call('cookie_delete', { confirmed }, 'CookieStatus');
    },
    settingsView: () => call('settings_view', undefined, 'SettingsView'),
    settingsSave: input => call('settings_save', { input }, 'SettingsView'),
    scrapeSettingsSave: async backends => {
      if (!Array.isArray(backends) || !backends.length || backends.some(value => typeof value !== 'string' || !value.trim())) {
        throw new ApiError(new TypeError('scrape backends require a non-empty string array'), 'INVALID_ARGUMENT');
      }
      return call('scrape_settings_save', { backends }, 'SettingsView');
    },
    rerankKeySave: async key => {
      if (typeof key !== 'string') throw new ApiError(new TypeError('rerank key must be a string'), 'INVALID_ARGUMENT');
      return call('rerank_key_save', { key }, 'SettingsView');
    },
    scrapeMemoryView: site => call('scrape_memory_view', { site }, 'ScrapeMemoryView'),
    scrapeMemoryPin: (site, scraper) => call('scrape_memory_pin', { site, scraper }, 'ScrapeMemoryView'),
    scrapeMemoryReset: async site => {
      if (typeof site !== 'string' || !site.trim()) {
        throw new ApiError(new TypeError('memory reset requires a site'), 'INVALID_ARGUMENT');
      }
      return call('scrape_memory_reset', { site }, 'ScrapeMemoryView');
    },
    providerList: async () => {
      const rows = await call('provider_list');
      if (!Array.isArray(rows)) {
        throw new ApiError(new TypeError('IPC payload for provider_list expected an array'), 'INVALID_PAYLOAD');
      }
      for (const row of rows) {
        try { expect('ProviderInfo', row); }
        catch (error) { throw new ApiError(error, 'INVALID_PAYLOAD'); }
      }
      return rows;
    },
    migrationPlan: () => call('migration_plan'),
    migrationApply: (planToken, approved, choices) => call('migration_apply', { planToken, approved, choices }),
  };
}
