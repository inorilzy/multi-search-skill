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
//   'sn' = string | null
//   'nn' = number | null
//   'sa' = Array<string>
//   'a'  = Array<unknown>     (any array, contents untyped)
//   'o'  = plain object
//   'x'  = any non-undefined value (e.g. JsonValue payloads)
//   'xn' = any value including null (e.g. Option<JsonValue>)
//
// Compound tags name another schema ('Discovery', 'InstallStep[]'), so the
// runtime resolves them by lookup. Type tags are written as string literals
// (not constants) because `tests/ui_contract.rs` parses this table to prove
// each field's kind and nullability matches the generated `types.d.ts`.

const schema = (fields) => ({ fields });

// One entry per public command payload type emitted by tests/ui_contract.rs.
// Field order matches `types.d.ts`. Adding a new status variant in Rust does
// NOT require updating this file — only adding a *field* does.
export const schemas = {
  Discovery: schema({ status: 's', path: 'sn', version: 'sn', reason: 's' }),
  CliStatus: schema({ app: 'Discovery', user: 'Discovery', restart_required: 'b' }),
  SearchOptions: schema({ query: 's', route: 's', sources: 'sa', timeout: 'n' }),
  ExecutionStatus: schema({ id: 'n', status: 's', exit_code: 'nn', payload: 'xn', error: 's' }),
  InstallPlan: schema({
    status: 's', root: 's', bin: 's', version: 'sn', current_version: 'sn', source: 'sn',
    compatibility: 's', compatibility_reason: 's', reason: 's', path_hint: 's',
  }),
  InstallStep: schema({ name: 's', ok: 'b', detail: 's' }),
  InstallOutcome: schema({
    status: 's', steps: 'InstallStep[]', version: 'sn', bin: 'sn', path_hint: 's', reason: 's',
  }),
  SkillPlan: schema({
    host: 's', scope: 's', target: 'sn', status: 's', reason: 's', files: 'sa', can_install: 'b',
  }),
  SkillInstall: schema({
    status: 's', target: 'sn', verified: 'b', reason: 's', files: 'sa',
  }),
  // InstallState is a plain string union in the wire format. We accept any
  // string and let the UI degrade; that is the contract for forward-compat.
  InstallState: schema({}),
  SkillStatus: schema({
    host: 's', scope: 's', target: 'sn', state: 's', installed_version: 'sn',
    release_version: 's', cli_requirements: 's', cli_compatible: 'b',
    compatibility_reason: 's', can_update: 'b',
    managed_files: 'sa', modified_files: 'sa', unknown_entries: 'sa', reason: 's',
  }),
  UpdatePlan: schema({
    status: 's', reason: 's', state: 's', backup_required: 'b',
    modified_files: 'sa', unknown_entries: 'sa', can_update: 'b',
  }),
  RemovePlan: schema({
    status: 's', reason: 's', will_delete: 'sa', will_keep: 'sa', can_remove: 'b',
  }),
  UpdateOutcome: schema({ status: 's', verified: 'b', backup: 'sn', reason: 's' }),
  RemoveOutcome: schema({ status: 's', deleted: 'sa', kept: 'sa', reason: 's' }),
  PathValue: schema({ text: 's', kind: 'n', exists: 'b' }),
  PathReceipt: schema({ before: 'PathValue', after: 'PathValue', entry: 's' }),
  PathPlan: schema({
    status: 's', directory: 's', reason: 's', can_add: 'b', can_remove: 'b',
  }),
  CredentialStatus: schema({ state: 's', saved_at: 'nn', error: 's' }),
  CredentialOverview: schema({
    source: 's', store: 'CredentialStatus', effective_source: 's',
    key_application_available: 'b',
  }),
  CredentialValue: schema({ value: 's' }),
  TestOutcome: schema({ result: 's', message: 's' }),
  ProviderInfo: schema({
    source: 's', cliSource: 's', provider: 'sn', label: 's',
    keyed: 'b', cookie: 'b', aliases: 'sa',
  }),
  RouteConfig: schema({ label: 's', sources: 'sa', timeout: 'nn' }),
  SettingsInput: schema({
    route: 's', timeout: 'n', disabled_sources: 'sa', routes: 'RouteMapN',
    twitter_cookies_path: 'sn',
  }),
  SettingsView: schema({
    config_path: 'sn', path_source: 's', file_present: 'b', read_source: 's',
    route: 's', timeout: 'n', timeout_configured: 'b', effective_timeout: 'n',
    effective_timeouts: 'NumMap', routes: 'RouteMap', builtin_routes: 'RouteMap',
    disabled_sources: 'sa', twitter_cookies_path: 'sn', active_sources: 'sa',
    status: 's', message: 's',
  }),
};

// Map<T> helpers for `BTreeMap<String, _>` payloads.
const isRecord = v => v !== null && typeof v === 'object' && !Array.isArray(v);

function typeOk(tag, value) {
  if (tag === 's') return typeof value === 'string';
  if (tag === 'n') return typeof value === 'number' && Number.isFinite(value);
  if (tag === 'b') return typeof value === 'boolean';
  if (tag === 'sn') return value === null || typeof value === 'string';
  if (tag === 'nn') return value === null || (typeof value === 'number' && Number.isFinite(value));
  if (tag === 'sa') return Array.isArray(value) && value.every(v => typeof v === 'string');
  if (tag === 'a') return Array.isArray(value);
  if (tag === 'o') return isRecord(value);
  if (tag === 'x') return value !== undefined;
  if (tag === 'xn') return true;
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

function checkShape(fields, value, prefix = '') {
  if (!isRecord(value)) return 'payload is not an object';
  for (const [field, tag] of Object.entries(fields)) {
    const v = value[field];
    if (typeOk(tag, v)) continue;
    const path = prefix ? `${prefix}.${field}` : field;
    // Surface the nested reason when the failure is inside a named schema, so
    // a bad `app.version` reads as such rather than "app is wrong".
    const nested = schemas[tag];
    if (nested && isRecord(v)) {
      const nestedReason = checkShape(nested.fields, v, path);
      if (nestedReason) return nestedReason;
    }
    return `field "${path}" expected ${tag}, got ${describe(v)}`;
  }
  return null;
}

function describe(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) return `Array(${value.length})`;
  return typeof value;
}

/**
 * Validate `payload` against `schemas[typeName]`. Returns `null` on success
 * or a short English reason on failure (the caller decides whether to throw).
 * @param {string} typeName
 * @param {unknown} payload
 * @returns {string|null}
 */
export function check(typeName, payload) {
  const entry = schemas[typeName];
  if (!entry) return `unknown payload type ${typeName}`;
  return checkShape(entry.fields, payload);
}

/**
 * Throw a descriptive error when `payload` does not satisfy `schemas[typeName]`.
 * api.js calls this for every invoke result so a malformed backend response
 * blows up at the boundary instead of corrupting page state.
 *
 * The template binds the schema name to its generated TypeScript type through
 * `contract-map.d.ts`, so `expect('CliStatus', raw)` returns `CliStatus`.
 * `// @ts-check` in api.js therefore constrains what `invoke` may return
 * instead of relying on an unchecked cast.
 *
 * @template {keyof import('./contract-map').ContractMap} K
 * @param {K} typeName
 * @param {unknown} payload
 * @returns {import('./contract-map').ContractMap[K]}
 */
export function expect(typeName, payload) {
  const reason = check(typeName, payload);
  if (reason !== null) {
    throw new TypeError(`IPC payload for ${typeName} violated the contract: ${reason}`);
  }
  // The runtime check above is the boundary; this single assertion hands the
  // caller the generated type.
  return /** @type {import('./contract-map').ContractMap[K]} */ (payload);
}
