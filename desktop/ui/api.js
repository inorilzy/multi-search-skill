// Commands reject with the backend's string reason, an Error, or a structured object. Normalize
// all three so a page can show why an operation failed instead of a generic retry hint.
export function errorReason(error, fallback = '未知错误') {
  if (typeof error === 'string' && error.trim()) return error.trim();
  if (error && typeof error === 'object') {
    if (typeof error.message === 'string' && error.message.trim()) return error.message.trim();
    try {
      const json = JSON.stringify(error);
      if (json && json !== '{}') return json;
    } catch { /* circular or opaque rejection */ }
  }
  return fallback;
}

export function managementApi(invoke) {
  return {
    // No call carries an executable path: the backend always runs the managed CLI (then PATH).
    detect: () => invoke('detect_cli'),
    start: options => invoke('start_test_search', { options }),
    poll: id => invoke('poll_execution', { id }),
    cancel: id => invoke('cancel_test_search', { id }),
    skillPlan: (scope, project) => invoke('skill_plan', { scope, project }),
    skillInstall: (scope, project) => invoke('skill_install', { scope, project }),
    skillStatus: (scope, project) => invoke('skill_status', { scope, project }),
    skillUpdate: (scope, project, confirmOverwrite) => invoke('skill_update', { scope, project, confirmOverwrite }),
    skillRemovePlan: (scope, project) => invoke('skill_remove_plan', { scope, project }),
    skillRemove: (scope, project, confirmed) => invoke('skill_remove', { scope, project, confirmed }),
    installPlan: () => invoke('install_plan'),
    install: () => invoke('install_cli'),
    update: () => invoke('update_cli'),
    uninstall: () => invoke('uninstall_cli'),
    userPathPlan: () => invoke('user_path_plan'),
    userPathChange: (remove, confirmed) => invoke('user_path_change', { remove, confirmed }),
    credentialStatus: source => invoke('credential_status', { source }),
    credentialSave: (source, key) => invoke('credential_save', { source, key }),
    credentialDelete: source => invoke('credential_delete', { source }),
    credentialTest: source => invoke('credential_test', { source }),
    settingsView: () => invoke('settings_view'),
    settingsSave: input => invoke('settings_save', { input }),
    migrationPlan: () => invoke('migration_plan'),
    migrationApply: (planToken, approved, choices) => invoke('migration_apply', { planToken, approved, choices }),
  };
}
