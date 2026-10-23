// @ts-check
// IPC surface for the management UI. Every command return value is run
// through `expect(TypeName, payload)` from `./payloads.js` so a malformed
// backend response fails fast at the boundary instead of propagating into
// page state. Types are imported from the generated `./types.d.ts` —
// `cargo test -p multi-search-desktop --test ui_contract` regenerates them
// whenever the Rust contract changes.
//
// @ts-check consumes the generated `.d.ts` so a contract drift between Rust
// and JS is a type error here, not just a runtime error.

import { expect } from './payloads.js';
import { ApiError } from './errors.js';
export { ApiError } from './errors.js';
/** @typedef {import('./types').CliStatus} CliStatus */
/** @typedef {import('./types').ExecutionStatus} ExecutionStatus */
/** @typedef {import('./types').InstallPlan} InstallPlan */
/** @typedef {import('./types').InstallOutcome} InstallOutcome */
/** @typedef {import('./types').SkillPlan} SkillPlan */
/** @typedef {import('./types').SkillInstall} SkillInstall */
/** @typedef {import('./types').SkillStatus} SkillStatus */
/** @typedef {import('./types').UpdatePlan} UpdatePlan */
/** @typedef {import('./types').UpdateOutcome} UpdateOutcome */
/** @typedef {import('./types').RemovePlan} RemovePlan */
/** @typedef {import('./types').RemoveOutcome} RemoveOutcome */
/** @typedef {import('./types').PathPlan} PathPlan */
/** @typedef {import('./types').CredentialOverview} CredentialOverview */
/** @typedef {import('./types').CredentialValue} CredentialValue */
/** @typedef {import('./types').TestOutcome} TestOutcome */
/** @typedef {import('./types').ProviderInfo} ProviderInfo */
/** @typedef {import('./types').SettingsInput} SettingsInput */
/** @typedef {import('./types').SettingsView} SettingsView */
/** @typedef {import('./types').ScrapeMemoryView} ScrapeMemoryView */
/** @typedef {import('./types').SearchOptions} SearchOptions */

/** @typedef {(cmd: string, args?: Record<string, unknown>) => Promise<unknown>} InvokeFn */

/**
 * Wrap a Tauri `invoke` function so each command's return value is checked
 * against the schema for that payload type before the caller sees it.
 *
 * @param {InvokeFn} rawInvoke
 */
export function managementApi(rawInvoke) {
  /** @type {InvokeFn} */
  const invoke = async (cmd, args) => { try { return await rawInvoke(cmd, args); } catch (cause) { throw new ApiError(cause); } };
  const api = {
    /** @param {string|null} path @returns {Promise<CliStatus>} */
    detect: async path => (expect('CliStatus', await invoke('detect_cli', { path }))),
    /** @param {string|null} path @param {SearchOptions} options @returns {Promise<number>} */
    start: async (path, options) => {
      const id = await invoke('start_test_search', { path, options });
      if (typeof id !== 'number' || !Number.isFinite(id)) {
        throw new TypeError('IPC payload for start_test_search expected a numeric execution id');
      }
      return id;
    },
    /** @param {number} id @returns {Promise<ExecutionStatus>} */
    poll: async id => (expect('ExecutionStatus', await invoke('poll_execution', { id }))),
    /** @param {number} id @returns {Promise<ExecutionStatus>} */
    cancel: async id => (expect('ExecutionStatus', await invoke('cancel_test_search', { id }))),
    /** @param {string} scope @param {string|null} project @returns {Promise<SkillPlan>} */
    skillPlan: async (scope, project) => (expect('SkillPlan', await invoke('skill_plan', { scope, project }))),
    /** @param {string} scope @param {string|null} project @returns {Promise<SkillInstall>} */
    skillInstall: async (scope, project) => (expect('SkillInstall', await invoke('skill_install', { scope, project }))),
    /** @param {string} scope @param {string|null} project @returns {Promise<SkillStatus>} */
    skillStatus: async (scope, project) => (expect('SkillStatus', await invoke('skill_status', { scope, project }))),
    /** @param {string} scope @param {string|null} project @param {boolean} confirmOverwrite @returns {Promise<UpdateOutcome>} */
    skillUpdate: async (scope, project, confirmOverwrite) => (expect('UpdateOutcome', await invoke('skill_update', { scope, project, confirmOverwrite }))),
    /** @param {string} scope @param {string|null} project @returns {Promise<RemovePlan>} */
    skillRemovePlan: async (scope, project) => (expect('RemovePlan', await invoke('skill_remove_plan', { scope, project }))),
    /** @param {string} scope @param {string|null} project @param {boolean} confirmed @returns {Promise<RemoveOutcome>} */
    skillRemove: async (scope, project, confirmed) => (expect('RemoveOutcome', await invoke('skill_remove', { scope, project, confirmed }))),
    /** @returns {Promise<InstallPlan>} */
    installPlan: async () => (expect('InstallPlan', await invoke('install_plan'))),
    /** @returns {Promise<InstallOutcome>} */
    install: async () => (expect('InstallOutcome', await invoke('install_cli'))),
    /** @returns {Promise<InstallOutcome>} */
    update: async () => (expect('InstallOutcome', await invoke('update_cli'))),
    /** @returns {Promise<InstallOutcome>} */
    uninstall: async () => (expect('InstallOutcome', await invoke('uninstall_cli'))),
    /** @returns {Promise<PathPlan>} */
    userPathPlan: async () => (expect('PathPlan', await invoke('user_path_plan'))),
    /** @param {boolean} remove @param {boolean} confirmed @returns {Promise<PathPlan>} */
    userPathChange: async (remove, confirmed) => (expect('PathPlan', await invoke('user_path_change', { remove, confirmed }))),
    /** @param {string} source @returns {Promise<CredentialOverview>} */
    credentialStatus: async source => (expect('CredentialOverview', await invoke('credential_status', { source }))),
    /** @param {string} source @returns {Promise<CredentialValue>} */
    credentialReveal: async source => (expect('CredentialValue', await invoke('credential_reveal', { source }))),
    /** @param {string} source @returns {Promise<CredentialValue>} */
    credentialRead: async source => (expect('CredentialValue', await invoke('credential_read', { source }))),
    /** @param {string} source @returns {Promise<void>} */
    credentialApplicationOpen: async source => /** @type {void} */ (await invoke('credential_application_open', { source })),
    /** @param {string} source @param {string} key @returns {Promise<CredentialOverview>} */
    credentialSave: async (source, key) => (expect('CredentialOverview', await invoke('credential_save', { source, key }))),
    /** @param {string} source @param {string[]} keys @returns {Promise<CredentialOverview>} */
    credentialAppend: async (source, keys) => (expect('CredentialOverview', await invoke('credential_append', { source, keys }))),
    /** @param {string} source @param {number} index @param {string} expected @returns {Promise<CredentialOverview>} */
    credentialRemove: async (source, index, expected) => (expect('CredentialOverview', await invoke('credential_remove', { source, index, expected }))),
    /** @param {string} source @returns {Promise<CredentialOverview>} */
    credentialDelete: async source => (expect('CredentialOverview', await invoke('credential_delete', { source }))),
    /** @param {string} source @param {string|null} path @returns {Promise<TestOutcome>} */
    credentialTest: async (source, path) => (expect('TestOutcome', await invoke('credential_test', { source, path }))),
    /** @returns {Promise<SettingsView>} */
    settingsView: async () => (expect('SettingsView', await invoke('settings_view'))),
    /** @param {SettingsInput} input @returns {Promise<SettingsView>} */
    settingsSave: async input => (expect('SettingsView', await invoke('settings_save', { input }))),
    /** @param {import('./contract-map').ScrapeSettingsSaveArgs['backends']} backends @returns {Promise<SettingsView>} */
    scrapeSettingsSave: async backends => {
      if (!Array.isArray(backends) || !backends.length || backends.some(value => typeof value !== 'string' || !value.trim())) throw new TypeError('scrape backends require a non-empty string array');
      return expect('SettingsView', await invoke('scrape_settings_save', { backends }));
    },
    /** @param {string|null} site @returns {Promise<ScrapeMemoryView>} */
    scrapeMemoryView: async site => expect('ScrapeMemoryView', await invoke('scrape_memory_view', { site })),
    /** @param {string} site @param {string} scraper @returns {Promise<ScrapeMemoryView>} */
    scrapeMemoryPin: async (site, scraper) => expect('ScrapeMemoryView', await invoke('scrape_memory_pin', { site, scraper })),
    /** @param {string} site @returns {Promise<ScrapeMemoryView>} */
    scrapeMemoryReset: async site => {
      if (typeof site !== 'string' || !site.trim()) throw new TypeError('memory reset requires a site');
      return expect('ScrapeMemoryView', await invoke('scrape_memory_reset', { site }));
    },
    /** @returns {Promise<ProviderInfo[]>} */
    providerList: async () => {
      const rows = await invoke('provider_list');
      if (!Array.isArray(rows)) throw new TypeError('IPC payload for provider_list expected an array');
      for (const row of rows) expect('ProviderInfo', row);
      return /** @type {ProviderInfo[]} */ (rows);
    },
  };
  for (const name of Object.keys(api)) {
    const call = api[name];
    api[name] = async (...args) => {
      try { return await call(...args); }
      catch (cause) { throw cause instanceof ApiError ? cause : new ApiError(cause, cause instanceof TypeError ? 'INVALID_PAYLOAD' : 'IPC_ERROR'); }
    };
  }
  return api;
}
