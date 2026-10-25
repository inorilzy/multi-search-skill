// Compatibility module for the modular UI: `errors.js` owns no normalization logic of its own.
//
// The single normalization entry is `api.js` (`normalizeError` / `showError`), because that is also
// where every IPC rejection becomes an `IpcError`. Pages and modules that only need a display
// string import `toMessage` from here; anything that owns an error slot uses `showError`.
//
// `ApiError` keeps its historical name (and its `(cause, code)` constructor) so ported modules stay
// unchanged; it is the same class `api.js` raises for boundary and payload failures.

import { normalizeError } from './api.js';

export { IpcError, ApiError, normalizeError, errorReason, showError } from './api.js';

/**
 * Display text for any rejection value. Never returns an English backend reason: unknown codes and
 * English details fall back to `fallback` (the raw reason stays available via `normalizeError`).
 * @param {unknown} error
 * @param {string} [fallback]
 */
export function toMessage(error, fallback = '操作失败，请重试。') {
  return normalizeError(error, fallback).message;
}
