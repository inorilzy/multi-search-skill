// Read-only accessors for the catalog generated from Python core metadata.
// Edit `multi_search_mcp/src/search/catalog.py` and run
// `python scripts/export_source_catalog.py`; never hand-edit source-catalog.js.
import { SOURCE_CATALOG } from './source-catalog.js';

export const CATALOG = SOURCE_CATALOG;
export const SEARCH_SOURCES = SOURCE_CATALOG.sources.filter(source => source.searchable);
export const ROUTES = SOURCE_CATALOG.routes;
export const SOURCE_ALIASES = SOURCE_CATALOG.source_aliases;
export const CREDENTIAL_STORE_PROVIDERS = SOURCE_CATALOG.credential_store_providers;

export function canonicalSource(name) {
  return SOURCE_ALIASES[name] || name;
}

export function sourceEntry(name) {
  const canonical = canonicalSource(name);
  return SEARCH_SOURCES.find(source => source.name === canonical) || null;
}

export function sourceLabel(name) {
  return sourceEntry(name)?.label || String(name);
}

export function isAllowedSource(name) {
  return sourceEntry(name) !== null;
}

export function routeEntry(route) {
  return ROUTES.find(item => item.name === route || item.aliases.includes(route)) || null;
}

export function routeSources(route) {
  return routeEntry(route)?.sources || [];
}
