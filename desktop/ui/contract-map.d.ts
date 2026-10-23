// Hand-written bridge between the generated declarations (`types.d.ts`) and
// the runtime schema names in `payloads.js`. Keep the keys in lock-step with
// `schemas` in payloads.js — `cargo test --test ui_contract
// payloads_js_matches_rust_field_types` fails if a payload type is missing
// there, and this file is what gives `expect(name, payload)` its return type.
//
// No payload type may be added here without also appearing in schemas.
import type * as T from './types';

// Dedicated command arguments: scraping never round-trips search settings.
export interface ScrapeSettingsSaveArgs { backends: string[] }
export interface CommandContracts {
  scrape_settings_save: { args: ScrapeSettingsSaveArgs; result: T.SettingsView };
}

export interface ContractMap {
  Discovery: T.Discovery;
  CliStatus: T.CliStatus;
  SearchOptions: T.SearchOptions;
  ExecutionStatus: T.ExecutionStatus;
  InstallPlan: T.InstallPlan;
  InstallStep: T.InstallStep;
  InstallOutcome: T.InstallOutcome;
  SkillPlan: T.SkillPlan;
  SkillInstall: T.SkillInstall;
  InstallState: T.InstallState;
  SkillStatus: T.SkillStatus;
  UpdatePlan: T.UpdatePlan;
  RemovePlan: T.RemovePlan;
  UpdateOutcome: T.UpdateOutcome;
  RemoveOutcome: T.RemoveOutcome;
  PathValue: T.PathValue;
  PathReceipt: T.PathReceipt;
  PathPlan: T.PathPlan;
  CredentialStatus: T.CredentialStatus;
  CredentialOverview: T.CredentialOverview;
  CredentialValue: T.CredentialValue;
  TestOutcome: T.TestOutcome;
  ProviderInfo: T.ProviderInfo;
  RouteConfig: T.RouteConfig;
  ScrapeBackendOption: T.ScrapeBackendOption;
  ScrapeMemoryRow: T.ScrapeMemoryRow;
  ScrapeMemoryView: T.ScrapeMemoryView;
  SettingsInput: T.SettingsInput;
  SettingsView: T.SettingsView;
}
