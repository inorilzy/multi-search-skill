// Recent test searches, kept in this window's local storage so a query can be re-run with one tap.
// Queries are private to this user account; nothing here leaves the machine, and "清空" removes them.
const KEY = 'multi-search.test-search-history';
export const HISTORY_LIMIT = 8;

const same = (a, b) => a.query === b.query && a.route === b.route && a.sources.join(',') === b.sources.join(',');

function clean(item) {
  if (!item || typeof item.query !== 'string' || !item.query.trim()) return null;
  return {
    query: item.query.slice(0, 2000),
    route: typeof item.route === 'string' ? item.route : 'default',
    sources: Array.isArray(item.sources) ? item.sources.filter(s => typeof s === 'string') : [],
    timeout: Number.isFinite(item.timeout) ? item.timeout : null,
  };
}

/** @param {Storage | null | undefined} storage */
export function createHistory(storage) {
  function read() {
    try {
      const raw = storage?.getItem(KEY);
      const list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list.map(clean).filter(Boolean).slice(0, HISTORY_LIMIT) : [];
    } catch { return []; }
  }
  function write(list) {
    // A full or disabled storage only loses the history, never the search.
    try { storage?.setItem(KEY, JSON.stringify(list)); } catch { /* ignore */ }
  }
  return {
    list: read,
    /** Newest first; re-running an entry moves it to the front instead of duplicating it. */
    add(entry) {
      const item = clean(entry);
      if (!item) return read();
      const next = [item, ...read().filter(old => !same(old, item))].slice(0, HISTORY_LIMIT);
      write(next);
      return next;
    },
    remove(index) {
      const next = read().filter((_, i) => i !== index);
      write(next);
      return next;
    },
    clear() {
      try { storage?.removeItem(KEY); } catch { /* ignore */ }
      return [];
    },
  };
}
