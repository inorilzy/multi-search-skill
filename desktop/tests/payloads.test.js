import test from 'node:test';
import assert from 'node:assert/strict';
import { check, expect, schemas } from '../ui/payloads.js';

const cliStatus = (status = 'ready') => ({
  app: { status, path: 'C:\\cli\\multi-search.exe', version: '0.4.0', reason: '' },
  user: { status, path: null, version: null, reason: '' },
  restart_required: false,
});

test('expect returns the payload when it matches the schema', () => {
  const payload = cliStatus();
  assert.equal(expect('CliStatus', payload), payload);
});

test('expect throws a descriptive TypeError on a missing or mistyped field', () => {
  const missing = cliStatus();
  delete missing.restart_required;
  assert.throws(
    () => expect('CliStatus', missing),
    /IPC payload for CliStatus violated the contract: field "restart_required" expected b, got undefined/,
  );

  const mistyped = cliStatus();
  mistyped.app.version = 42;
  assert.throws(
    () => expect('CliStatus', mistyped),
    /field "app.version" expected sn, got number/,
  );
});

test('nullable fields accept null and reject the wrong primitive', () => {
  // CredentialStatus.saved_at is number | null.
  assert.equal(check('CredentialStatus', { state: 'absent', saved_at: null, error: '' }), null);
  assert.match(
    check('CredentialStatus', { state: 'absent', saved_at: 'yesterday', error: '' }),
    /field "saved_at" expected nn, got string/,
  );
});

test('unknown status values fall back instead of failing the shape check', () => {
  // A future Rust variant must not be rejected here; the UI renders the raw
  // wire value via `labels[status] || status`.
  const future = cliStatus('quantum_flux');
  assert.equal(check('CliStatus', future), null);
  // The skill state is a string union; an unknown variant is still a string.
  assert.equal(
    check('SkillStatus', {
      host: 'claude-code', scope: 'global', target: null, state: 'temporarily_confused',
      installed_version: null, release_version: '1', cli_requirements: '',
      cli_compatible: false, compatibility_reason: '', can_update: false,
      managed_files: [], modified_files: [], unknown_entries: [], reason: '',
    }),
    null,
  );
});

test('unknown schema names fail closed', () => {
  assert.match(check('NoSuchPayload', {}), /unknown payload type NoSuchPayload/);
  assert.throws(() => expect('NoSuchPayload', {}), /unknown payload type NoSuchPayload/);
});

test('nested payloads are validated, not just the top level', () => {
  assert.match(
    check('CliStatus', { ...cliStatus(), app: { status: 'ready' } }),
    /field "app\.path" expected sn, got undefined/,
  );
});

test('empty schema accepts any object shape (InstallState is a string union)', () => {
  assert.equal(check('InstallState', {}), null);
  assert.equal(schemas.InstallState.fields && Object.keys(schemas.InstallState.fields).length, 0);
});
