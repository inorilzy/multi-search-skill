// Core still owns balance TTLs and saved credentials. This application-level clock only asks
// configured providers for balances; it never starts a login, search or browser session.
export const USAGE_REFRESH_INTERVAL = 10 * 60 * 1000;

/**
 * @param {any} api
 * @param {{now?: () => number, schedule?: (callback: () => any, delay: number) => any,
 *   cancel?: (timer: any) => void, document?: Document, window?: Window}} [options]
 */
export function createUsageAutoRefresh(api, {
  now = Date.now, schedule = setTimeout, cancel = clearTimeout, document: doc, window: win,
} = {}) {
  let disposed = false;
  let started = false;
  let timer = null;
  let completedAt = null;
  let inFlight = null;
  let queue = Promise.resolve();
  const listeners = new Set();

  // Pages use this same queue, so an explicit refresh cannot overlap an automatic query.
  function serialized(method) {
    return (...args) => {
      const result = queue.then(() => api[method](...args));
      queue = result.catch(() => {});
      return result;
    };
  }
  const sharedApi = { ...api };
  for (const method of ['usageView', 'balanceView', 'accountsView']) {
    if (typeof api[method] === 'function') sharedApi[method] = serialized(method);
  }

  async function refresh() {
    try {
      if (typeof sharedApi.usageView !== 'function') return;
      const cached = await sharedApi.usageView(null, false);
      if (disposed || cached.status !== 'ready') return;
      // Usage includes virtual environment keys; accounts adds balance-only login references.
      // Unreadable account metadata never makes an otherwise empty provider eligible.
      let groups = {};
      try {
        const accounts = await sharedApi.accountsView?.(null);
        if (accounts?.status === 'ready') groups = accounts.accounts;
      } catch { /* available usage keys can still refresh; retry metadata next cycle */ }
      for (const provider of cached.providers) {
        if (disposed) return;
        const configured = [...provider.accounts, ...(groups[provider.id] || [])].some(account =>
          account.keys.length || Object.keys(account.balance_credentials || {}).length);
        if (!provider.balance_supported || !configured) continue;
        try {
          // refresh=true asks usage to honor Core's existing cache, without forcing a TTL bypass.
          const view = await sharedApi.usageView(provider.id, true);
          if (!disposed) for (const listener of listeners) listener(view, provider.id);
        } catch { /* no tight retries, including rate limits; other providers may still succeed */ }
      }
    } catch { /* offline/CLI failures are retried on the next full cycle */ }
    finally {
      inFlight = null;
      if (!disposed) {
        completedAt = now();
        timer = schedule(refreshIfDue, USAGE_REFRESH_INTERVAL);
      }
    }
  }

  function refreshIfDue() {
    if (disposed) return Promise.resolve();
    if (inFlight) return inFlight;
    if (completedAt !== null && now() - completedAt < USAGE_REFRESH_INTERVAL) return Promise.resolve();
    if (timer !== null) cancel(timer);
    timer = null;
    inFlight = Promise.resolve().then(refresh);
    return inFlight;
  }
  const resume = () => doc?.visibilityState === 'hidden' ? Promise.resolve() : refreshIfDue();

  return {
    api: sharedApi,
    start() {
      if (!started && !disposed) {
        started = true;
        doc?.addEventListener('visibilitychange', resume);
        win?.addEventListener('focus', resume);
        win?.addEventListener('pageshow', resume);
      }
      return refreshIfDue();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    dispose() {
      disposed = true;
      if (timer !== null) cancel(timer);
      timer = null;
      listeners.clear();
      doc?.removeEventListener('visibilitychange', resume);
      win?.removeEventListener('focus', resume);
      win?.removeEventListener('pageshow', resume);
    },
  };
}
