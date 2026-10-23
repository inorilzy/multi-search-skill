// @ts-check
/** @param {unknown} error @param {string} [fallback] */
export function toMessage(error, fallback = '操作失败，请重试。') {
  if (typeof error === 'string' && error.trim()) return error;
  if (error instanceof Error && error.message) return error.message;
  if (error && typeof error === 'object' && 'message' in error && typeof error.message === 'string') return error.message;
  return fallback;
}
export class ApiError extends Error {
  /** @param {unknown} cause @param {string} [code] */
  constructor(cause, code = 'IPC_ERROR') {
    super(toMessage(cause), { cause });
    this.name = 'ApiError';
    this.code = cause && typeof cause === 'object' && 'code' in cause ? String(cause.code) : code;
  }
}
