// Unified IPC error contract. The backend rejects every command with a serialized
// `{ code, message }` object (see src/errors.rs). `normalizeError` parses that shape, maps
// known codes onto Chinese UI text, and falls back to the backend's Chinese message or a
// generic fallback for anything else — an English worker name or enum never reaches the user.
// All rejection values (string, Error, {code,message}, unknown objects) go through here.

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
  credential_save_failed: '凭据保存失败，请检查凭据库访问后重试。',
  credential_delete_failed: '凭据删除失败，请重试。',
  credential_test_failed: '凭据测试启动失败，请检查 CLI 后重试。',
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
};

export class IpcError extends Error {
  constructor(code, message, detail) {
    super(message);
    this.name = 'IpcError';
    this.code = code;
    this.detail = detail;
  }
}

/// Parse any IPC rejection into an IpcError: `message` is display-ready Chinese for known
/// codes; `detail` keeps the raw reason (never shown unless it is already Chinese).
export function normalizeError(error, fallback = '操作失败，请重试。') {
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

export function managementApi(invoke) {
  // One wrap: normalize every rejection into IpcError before a page sees it.
  const call = (command, args) => invoke(command, args).catch(error => { throw normalizeError(error); });
  return {
    // No call carries an executable path: the backend always runs the managed CLI (then PATH).
    detect: () => call('detect_cli'),
    start: options => call('start_test_search', { options }),
    poll: id => call('poll_execution', { id }),
    cancel: id => call('cancel_test_search', { id }),
    skillPlan: (scope, project) => call('skill_plan', { scope, project }),
    skillInstall: (scope, project) => call('skill_install', { scope, project }),
    skillStatus: (scope, project) => call('skill_status', { scope, project }),
    skillUpdate: (scope, project, confirmOverwrite) => call('skill_update', { scope, project, confirmOverwrite }),
    skillRemovePlan: (scope, project) => call('skill_remove_plan', { scope, project }),
    skillRemove: (scope, project, confirmed) => call('skill_remove', { scope, project, confirmed }),
    installPlan: () => call('install_plan'),
    install: () => call('install_cli'),
    update: () => call('update_cli'),
    uninstall: () => call('uninstall_cli'),
    userPathPlan: () => call('user_path_plan'),
    userPathChange: (remove, confirmed) => call('user_path_change', { remove, confirmed }),
    credentialStatus: source => call('credential_status', { source }),
    credentialSave: (source, key) => call('credential_save', { source, key }),
    credentialDelete: source => call('credential_delete', { source }),
    credentialTest: source => call('credential_test', { source }),
    settingsView: () => call('settings_view'),
    settingsSave: input => call('settings_save', { input }),
    migrationPlan: () => call('migration_plan'),
    migrationApply: (planToken, approved, choices) => call('migration_apply', { planToken, approved, choices }),
  };
}
