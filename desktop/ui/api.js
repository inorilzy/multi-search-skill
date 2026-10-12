export function managementApi(invoke) {
  return {
    detect: path => invoke('detect_cli', { path }),
    start: (path, options) => invoke('start_test_search', { path, options }),
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
  };
}
