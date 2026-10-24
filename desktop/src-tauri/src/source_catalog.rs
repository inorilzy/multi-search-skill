//! Shared source, route, alias, and env catalog generated from Python core.
//!
//! `desktop/source-catalog.json` is rendered by `scripts/export_source_catalog.py`
//! from `multi_search_mcp/src/search/catalog.py` and checked in. This module is
//! the only place the desktop reads those names from: settings, execution, and
//! credential management derive their lists from it instead of hand-copying
//! Python constants. The Python regression suite fails when the artifact drifts
//! from core, and the desktop contract tests fail when these accessors diverge
//! from the artifact.
use serde::Deserialize;
use std::collections::BTreeMap;
use std::sync::OnceLock;

const CATALOG_JSON: &str = include_str!("../../source-catalog.json");

#[derive(Debug, Deserialize)]
pub struct Catalog {
    pub schema_version: u32,
    pub key_resolution: KeyResolution,
    pub env: EnvCatalog,
    pub credential_store_providers: Vec<String>,
    pub source_aliases: BTreeMap<String, String>,
    pub sources: Vec<Source>,
    pub routes: Vec<Route>,
}

#[derive(Debug, Deserialize)]
pub struct KeyResolution {
    pub order: Vec<String>,
    pub env_alias_priority: String,
    pub description: String,
}

#[derive(Debug, Deserialize)]
pub struct EnvCatalog {
    pub alias_priority: String,
    pub providers: BTreeMap<String, Vec<String>>,
}

#[derive(Debug, Deserialize)]
pub struct Source {
    pub name: String,
    pub public_name: String,
    pub label: String,
    pub description: String,
    pub mark: String,
    pub kind: String,
    pub searchable: bool,
    pub aliases: Vec<String>,
    pub key_provider: String,
    pub keyed: bool,
    pub cookie: bool,
    pub env: Vec<String>,
    pub routes: Vec<String>,
    pub max_count: Option<u32>,
}

#[derive(Debug, Deserialize)]
pub struct Route {
    pub name: String,
    pub label: String,
    pub aliases: Vec<String>,
    pub sources: Vec<String>,
}

/// Parse once; the embedded catalog is immutable for the process lifetime.
pub fn catalog() -> &'static Catalog {
    static CATALOG: OnceLock<Catalog> = OnceLock::new();
    CATALOG.get_or_init(|| {
        serde_json::from_str(CATALOG_JSON)
            .expect("desktop/source-catalog.json must be a valid generated catalog")
    })
}

impl Catalog {
    /// Resolve a canonical name or CLI alias. Trailing/leading whitespace is ignored.
    pub fn source(&self, name: &str) -> Option<&Source> {
        let trimmed = name.trim();
        let canonical = self
            .source_aliases
            .get(trimmed)
            .map(String::as_str)
            .unwrap_or(trimmed);
        self.sources.iter().find(|source| source.name == canonical)
    }

    /// Resolve a canonical route name or alias (`web`).
    pub fn route(&self, route: &str) -> Option<&Route> {
        let trimmed = route.trim();
        self.routes
            .iter()
            .find(|item| item.name == trimmed || item.aliases.iter().any(|alias| alias == trimmed))
    }

    pub fn search_sources(&self) -> impl Iterator<Item = &Source> {
        self.sources.iter().filter(|source| source.searchable)
    }

    pub fn credential_sources(&self) -> impl Iterator<Item = &Source> {
        self.sources.iter().filter(|source| source.keyed)
    }

    /// Sources the native credential test accepts: every search source, keyed or not.
    pub fn test_sources(&self) -> impl Iterator<Item = &Source> {
        self.sources.iter().filter(|source| source.searchable)
    }
}
