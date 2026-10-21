// Boundary validator for the Rust ↔ UI contract, hand-written and kept in
// lock-step with `types.d.ts` by `cargo test -p multi-search-desktop --test
// ui_contract`. It checks ONLY the structural shape of each invoke payload —
// required fields, primitive kind, optionality — never the exact set of
// `status`/`state`/`result`/`kind` strings. When Rust adds a new status
// variant the UI must keep working; that is the entire point of the
// `statusLabels[status] || status` fallback pattern.
//
// Schemas use a tiny type tag vocabulary:
//   's'  = string
//   'n'  = finite number (i32/f64/u32 are all fine; u64 must NOT be used here)
//   'b'  = boolean
//   'sn' = string | null      ('s?' would collide with optional-field syntax)
//   'nn' = number | null
//   'sa' = Array<string>
//   'a'  = Array<unknown>     (any array, contents untyped)
//   'o'  = plain object
//   'x'  = any non-undefined value (e.g. JsonValue payloads)
//
// Compound tags look like 'sa?', 'sn', 'nn', 'o?' — the trailing '?' makes
// the field optional-and-nullable; the bare 'n' / 's' marks non-null. The
// schema for a compound type lists its own fields under `fields`, nested
// inline so the runtime does no name resolution.

const schema = (fields) => ({ fields });
const S = 's', N = 'n', B = 'b', SN = 'sn', NN = 'nn', SA = 'sa', A = 'a', O = 'o', X = 'x';

// One entry per public command payload type emitted by tests/ui_contract.rs.
// Field order matches `types.d.ts`. Adding a new status variant in Rust does
// NOT require updating this file — only adding a *field* does.
export const schemas = {
  Discovery: schema({ status: S, path: SN, version: SN, reason: S }),
  CliStatus: schema({ app: 'Discovery', user: 'Discovery', restart_required: B }),
  SearchOptions: schema({ query: S, route: S, sources: SA, timeout: N }),
  ExecutionStatus: schema({ id: N, status: S, exit_code: NN, payload: X, error: S }),
  InstallPlan: schema({
    status: S, root: S, bin: S, version: SN, current_version: SN, source: SN,
    compatibility: S, compatibility_reason: S, reason: S, path_hint: S,
  }),
  InstallStep: schema({ name: S, ok: B, detail: S }),
  InstallOutcome: schema({
    status: S, steps: 'InstallStep[]', version: SN, bin: SN, path_hint: S, reason: S,
  }),
  SkillPlan: schema({
    host: S, scope: S, target: SN, status: S, reason: S, files: SA, can_install: B,
  }),
  SkillInstall: schema({
    status: S, target: SN, verified: B, reason: S, files: SA,
  }),
  // InstallState is a plain string union in the wire format. We accept any
  // string and let the UI degrade; that is the contract for forward-compat.
  InstallState: schema({}),
  SkillStatus: schema({
    host: S, scope: S, target: SN, state: S, installed_version: SN,
    release_version: S, cli_requirements: S, cli_compatible: B,
    compatibility_reason: S, can_update: B,
    managed_files: SA, modified_files: SA, unknown_entries: SA, reason: S,
  }),
  UpdatePlan: schema({
    status: S, reason: S, state: S, backup_required: B,
    modified_files: SA, unknown_entries: SA, can_update: B,
  }),
  RemovePlan: schema({
    status: S, reason: S, will_delete: SA, will_keep: SA, can_remove: B,
  }),
  UpdateOutcome: schema({ status: S, verified: B, backup: SN, reason: S }),
  RemoveOutcome: schema({ status: S, deleted: SA, kept: SA, reason: S }),
  PathValue: schema({ text: S, kind: N, exists: B }),
  PathReceipt: schema({ before: 'PathValue', after: 'PathValue', entry: S }),
  PathPlan: schema({
    status: S, directory: S, reason: S, can_add: B, can_remove: B,
  }),
  CredentialStatus: schema({ state: S, saved_at: NN, error: S }),
  CredentialOverview: schema({
    source: S, store: 'CredentialStatus', effective_source: S,
    key_application_available: B,
  }),
  CredentialValue: schema({ value: S }),
  TestOutcome: schema({ result: S, message: S }),
  ProviderInfo: schema({
    source: S, cliSource: S, provider: SN, label: S,
    keyed: B, cookie: B, aliases: SA,
  }),
  RouteConfig: schema({ label: S, sources: SA, timeout: NN }),
  SettingsInput: schema({
    route: S, timeout: N, disabled_sources: SA, routes: 'RouteMapN',
    twitter_cookies_path: SN,
  }),
  SettingsView: schema({
    config_path: SN, path_source: S, file_present: B, read_source: S,
    route: S, timeout: N, timeout_configured: B, effective_timeout: N,
    effective_timeouts: 'NumMap', routes: 'RouteMap', builtin_routes: 'RouteMap',
    disabled_sources: SA, twitter_cookies_path: SN, active_sources: SA,
    status: S, message: S,
  }),
};

// Map<T> helpers for `BTreeMap<String, _>` payloads.
const isRecord = v => v !== null && typeof v === 'object' && !Array.isArray(v);

function typeOk(tag, value) {
  if (tag === S) return typeof value === 'string';
  if (tag === N) return typeof value === 'number' && Number.isFinite(value);
  if (tag === B) return typeof value === 'boolean';
  if (tag === SN) return value === null || typeof value === 'string';
  if (tag === NN) return value === null || (typeof value === 'number' && Number.isFinite(value));
  if (tag === SA) return Array.isArray(value) && value.every(v => typeof v === 'string');
  if (tag === A) return Array.isArray(value);
  if (tag === O) return isRecord(value);
  if (tag === X) return value !== undefined;
  if (tag === 'NumMap') return isRecord(value) && Object.values(value).every(v => typeof v === 'number' && Number.isFinite(v));
  if (tag === 'RouteMap') return isRecord(value) && Object.values(value).every(v => checkShape(schemas.RouteConfig.fields, v) === null);
  if (tag === 'RouteMapN') return value === null || typeOk('RouteMap', value);
  if (tag.endsWith('[]')) {
    const inner = tag.slice(0, -2);
    if (!Array.isArray(value)) return false;
    const innerSchema = schemas[inner];
    if (!innerSchema) return false;
    return value.every(v => checkShape(innerSchema.fields, v) === null);
  }
  const nested = schemas[tag];
  if (nested) return checkShape(nested.fields, value) === null;
  return false;
}

function checkShape(fields, value) {
  if (!isRecord(value)) return 'payload is not an object';
  for (const [field, tag] of Object.entries(fields)) {
    const v = value[field];
    if (!typeOk(tag, v)) return `field "${field}" expected ${tag}, got ${describe(v)}`;
  }
  return null;
}

function describe(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) return `Array(${value.length})`;
  return typeof value;
}

/// Validate `payload` against `schemas[typeName]`. Returns `null` on success
/// or a short English reason on failure (the caller decides whether to throw).
export function check(typeName, payload) {
  const entry = schemas[typeName];
  if (!entry) return `unknown payload type ${typeName}`;
  return checkShape(entry.fields, payload);
}

/// Throw a descriptive error when `payload` does not satisfy `schemas[typeName]`.
/// api.js calls this for every invoke result so a malformed backend response
/// blows up at the boundary instead of corrupting page state.
export function expect(typeName, payload) {
  const reason = check(typeName, payload);
  if (reason !== null) {
    throw new TypeError(`IPC payload for ${typeName} violated the contract: ${reason}`);
  }
  return payload;
}
