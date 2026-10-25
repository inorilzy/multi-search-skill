// IPC boundary: the frontend can never name an executable, and the Tauri config exposes only the
// app's own typed commands through a capability (no global Tauri API object).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { managementApi } from '../ui/api.js';

const here = new URL('.', import.meta.url);
const read = path => readFileSync(new URL(path, here), 'utf8');

// Each command returns a payload that satisfies its declared contract, so the boundary validator
// lets the call complete and the test can inspect exactly what was sent.
const RESPONSES = {
  detect_cli: { app: { status: 'ready', path: null, version: null, reason: '' }, user: { status: 'ready', path: null, version: null, reason: '' }, restart_required: false, execution: { status: 'ready', path: null, version: null, reason: '' }, managed: true },
  start_test_search: 1,
  credential_test: { result: 'success', message: '' },
};
function recorder() {
  const calls = [];
  return { calls, api: managementApi(async (cmd, args) => { calls.push([cmd, args]); return RESPONSES[cmd] ?? null; }) };
}

test('no CLI-running command sends a path, even when a caller passes one', async () => {
  const { calls, api } = recorder();
  await api.detect('C:\\evil\\multi-search.exe');
  await api.start({ query: 'q', route: 'default', sources: [], timeout: 5 }, 'C:\\evil\\multi-search.exe');
  await api.credentialTest('tavily', 'C:\\evil\\multi-search.exe');
  await api.migrationPlan('C:\\evil\\multi-search.exe');
  await api.migrationApply('token', ['tavily'], {}, 'C:\\evil\\multi-search.exe');
  for (const [cmd, args] of calls) {
    assert.ok(!args || !('path' in args), `${cmd} must not forward a path`);
    assert.doesNotMatch(JSON.stringify(args ?? {}), /evil/, `${cmd} must not forward caller-chosen executables`);
  }
  assert.deepEqual(calls.map(([cmd]) => cmd), ['detect_cli', 'start_test_search', 'credential_test', 'migration_plan', 'migration_apply']);
});

test('the Rust command signatures accept no executable path parameter', () => {
  const window = read('../src-tauri/src/window.rs');
  assert.doesNotMatch(window, /path:\s*Option<String>/, 'no command takes a frontend path');
  assert.doesNotMatch(window, /execution_cli\(\s*path/, 'execution never uses a frontend path');
});

test('withGlobalTauri is off and the app does not rely on window.__TAURI__', () => {
  const conf = JSON.parse(read('../src-tauri/tauri.conf.json'));
  assert.equal(conf.app.withGlobalTauri, false);
  assert.doesNotMatch(read('../ui/app.js'), /window\.__TAURI__\b(?!_)/);
});

test('the capability grants exactly the registered app commands and nothing from core or plugins', () => {
  const capability = JSON.parse(read('../src-tauri/capabilities/management.json'));
  assert.deepEqual(capability.windows, ['main']);
  const window = read('../src-tauri/src/window.rs');
  const handler = window.match(/generate_handler!\[([\s\S]*?)\]/)[1].split(',').map(s => s.trim()).filter(Boolean);
  const build = read('../src-tauri/build.rs');
  const manifest = [...build.match(/const APP_COMMANDS: &\[&str\] = &\[([\s\S]*?)\];/)[1].matchAll(/"([a-z_]+)"/g)].map(m => m[1]);
  assert.deepEqual([...manifest].sort(), [...handler].sort(), 'build.rs app manifest lists every registered command');
  const granted = capability.permissions.map(p => {
    assert.equal(typeof p, 'string');
    assert.match(p, /^allow-[a-z-]+$/, `${p} must be an app command permission, not core:/plugin:`);
    return p.slice('allow-'.length).replaceAll('-', '_');
  });
  assert.deepEqual([...granted].sort(), [...handler].sort());
});
