//! Single provider manifest shared by credential commands, settings validation,
//! and the execution allowlist.
//!
//! The data is *not* hand-written here: it is derived at first use from the
//! generated `desktop/source-catalog.json` (`crate::source_catalog`), which
//! `scripts/export_source_catalog.py` renders from
//! `multi_search_mcp/src/search/catalog.py`. That keeps one single source of
//! truth for source names, aliases, `cli_source` spellings and credential
//! providers; `tests/source_catalog.rs` and the Python catalog test fail when
//! the artifact drifts from Core.
//!
//! Consumers keep the same interface as before (`resolve`, `list`,
//! `is_allowed_source`, `ProviderInfo`) so the UI contract and every domain
//! view stay unchanged.

use std::sync::OnceLock;

/// UI/CLI-facing source identifier used on the `--source` flag and the
/// sources page. Differs from `source` only for `github-repos`: settings and
/// Python use `github_repos`, while the CLI/UI label uses `github-repos`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct ProviderEntry {
    /// Canonical source name used in settings (`disabled_sources`, `routes.sources`).
    pub source: &'static str,
    /// UI/CLI form for credential commands and `--source` arguments.
    pub cli_source: &'static str,
    /// Credential store primary key. May differ from `source` (`github-repos`
    /// stores under `github`). `None` for sources that never take a key.
    pub provider: Option<&'static str>,
    /// Aliases that resolve to this entry.
    pub aliases: &'static [&'static str],
    /// Display name shown in the UI.
    pub label: &'static str,
    /// `true` if a credential can be saved for this source.
    pub keyed: bool,
    /// Whether this provider is a search source (false for scraper-only providers).
    pub search: bool,
    /// `true` if the source uses a local Cookie file instead of an API key.
    /// Mutually exclusive with `keyed` in the UI editor.
    pub cookie: bool,
}

/// Build the manifest from the generated catalog. Strings are borrowed from the
/// process-lifetime catalog (or leaked once for the alias slices), so the table
/// is as `&'static` as the hand-written one it replaces.
fn derive() -> Vec<ProviderEntry> {
    let catalog = crate::source_catalog::catalog();
    catalog
        .sources
        .iter()
        .map(|source| ProviderEntry {
            source: source.name.as_str(),
            cli_source: source.public_name.as_str(),
            provider: source.keyed.then_some(source.key_provider.as_str()),
            aliases: Box::leak(
                source
                    .aliases
                    .iter()
                    .map(|alias| alias.as_str())
                    .collect::<Vec<_>>()
                    .into_boxed_slice(),
            ),
            label: source.label.as_str(),
            keyed: source.keyed,
            search: source.searchable,
            cookie: source.cookie,
        })
        .collect()
}

/// All providers the desktop knows about, including scraper-only credentials.
/// Search consumers must filter by `search`. Ordering follows the generated
/// catalog, so the sources page is deterministic.
pub(crate) fn entries() -> &'static [ProviderEntry] {
    static PROVIDERS: OnceLock<Vec<ProviderEntry>> = OnceLock::new();
    PROVIDERS.get_or_init(derive)
}

/// Resolve a raw source name or alias to its canonical entry.
/// Trims surrounding whitespace before matching. Only search sources resolve:
/// scrape-only providers address credentials through settings, not `--source`.
pub(crate) fn resolve(raw: &str) -> Result<&'static ProviderEntry, String> {
    let trimmed = raw.trim();
    entries()
        .iter()
        .find(|entry| {
            entry.search
                && (entry.source == trimmed
                    || entry.cli_source == trimmed
                    || entry.aliases.contains(&trimmed))
        })
        .ok_or_else(|| "不支持的搜索源".into())
}

/// Test seam: returns the canonical `source` for a given input, or `None`.
/// External tests use this so they do not depend on the `ProviderEntry` type.
#[doc(hidden)]
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
pub fn resolve_canonical(raw: &str) -> Option<&'static str> {
    resolve(raw).ok().map(|entry| entry.source)
}

/// All names (canonical + aliases + cli_source) the CLI `--source` flag accepts.
/// Used by `execution.rs::is_allowed_source` to gate the start_search path.
pub(crate) fn allowed_source_names() -> impl Iterator<Item = &'static str> + 'static {
    entries().iter().filter(|entry| entry.search).flat_map(|entry| {
        std::iter::once(entry.source)
            .chain(std::iter::once(entry.cli_source))
            .chain(entry.aliases.iter().copied())
    })
}

/// Whether `name` is a valid `--source` value (canonical, cli_source, or alias).
pub(crate) fn is_allowed_source(name: &str) -> bool {
    allowed_source_names().any(|allowed| allowed == name)
}

/// Public payload returned to the UI: the same provider list the desktop uses
/// internally. Serialized as `source`/`cliSource`/`provider`/`label`/`keyed`/
/// `search`/`cookie`/`aliases` so the UI does not hardcode a copy.
#[derive(serde::Serialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
pub struct ProviderInfo {
    pub source: &'static str,
    #[serde(rename = "cliSource")]
    #[cfg_attr(feature = "ts", ts(rename = "cliSource"))]
    pub cli_source: &'static str,
    pub provider: Option<&'static str>,
    pub label: &'static str,
    pub keyed: bool,
    /// Whether this provider is a search source (false for scraper-only providers).
    pub search: bool,
    pub cookie: bool,
    pub aliases: &'static [&'static str],
}

/// Snapshot of the manifest for the UI and for tests that need to enumerate
/// the table without depending on internals.
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
pub fn list() -> Vec<ProviderInfo> {
    entries()
        .iter()
        .map(|entry| ProviderInfo {
            source: entry.source,
            cli_source: entry.cli_source,
            provider: entry.provider,
            label: entry.label,
            keyed: entry.keyed,
            search: entry.search,
            cookie: entry.cookie,
            aliases: entry.aliases,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_matches_canonical_cli_source_and_alias() {
        assert_eq!(resolve("github-repos").unwrap().source, "github_repos");
        assert_eq!(resolve("github").unwrap().source, "github_repos");
        assert_eq!(resolve("github_repos").unwrap().cli_source, "github-repos");
        assert_eq!(resolve(" v2ex ").unwrap().source, "sov2ex");
        assert!(resolve("jina").is_err(), "scrape-only providers are not --source values");
        assert!(resolve("nope").is_err());
    }

    #[test]
    fn allowed_source_names_cover_canonical_alias_and_cli() {
        for name in ["github_repos", "github-repos", "github", "v2ex", "sov2ex"] {
            assert!(is_allowed_source(name), "{name}");
        }
        assert!(!is_allowed_source("jina"));
        assert!(!is_allowed_source("unknown"));
    }

    #[test]
    fn keyed_and_cookie_are_mutually_exclusive() {
        for entry in entries() {
            assert!(!(entry.keyed && entry.cookie), "{}", entry.source);
        }
    }

    #[test]
    fn canonical_sources_are_unique() {
        let mut names: Vec<&str> = entries().iter().map(|entry| entry.source).collect();
        let total = names.len();
        names.sort_unstable();
        names.dedup();
        assert_eq!(names.len(), total);
    }
}
