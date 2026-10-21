//! Single provider manifest shared by credential commands, settings validation,
//! and the execution allowlist. Add or remove a search source by editing this
//! table — every consumer derives its view from `PROVIDERS`.
//!
//! The Python CLI keeps its own registry in `multi_search_mcp`; a contract test
//! compares this table against the Python `PROVIDERS`/`ALL_SOURCE_NAMES`
//! metadata so drift is caught at build time instead of by users.

/// UI/CLI-facing source identifier used on the `--source` flag and the
/// sources page. Differs from `source` only for `github-repos`: settings and
/// Python use `github_repos`, while the CLI/UI label uses `github-repos`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct ProviderEntry {
    /// Canonical source name used in settings (`disabled_sources`, `routes.sources`).
    /// Matches the Python `ALL_SOURCE_NAMES` normalization (underscore form).
    pub source: &'static str,
    /// UI/CLI form for credential commands and `--source` arguments. Equals
    /// `source` except for `github-repos`, which is the credential/UI label
    /// for the canonical `github_repos` source.
    pub cli_source: &'static str,
    /// Credential store primary key. May differ from `source` (`github-repos`
    /// stores under `github`). `None` for sources that never take a key.
    pub provider: Option<&'static str>,
    /// Aliases that resolve to this entry. Aliases are accepted in
    /// `disabled_sources`, route source lists, and `--source` arguments.
    pub aliases: &'static [&'static str],
    /// Display name shown in the UI.
    pub label: &'static str,
    /// `true` if a credential can be saved for this source.
    pub keyed: bool,
    /// `true` if the source uses a local Cookie file instead of an API key
    /// (Twitter). Mutually exclusive with `keyed` in the UI editor.
    pub cookie: bool,
}

/// All search sources the desktop knows about. Ordering defines UI listing
/// order; keep it stable so the sources page is deterministic.
///
/// To add a source: append one entry here, register the provider in
/// `multi_search_mcp/src/support/credential_store.py` `PROVIDERS` and
/// `multi_search_mcp/src/search/capabilities.py` `PROVIDER_CAPABILITIES`,
/// and update `sources.js` `DESCRIPTIONS`/`MARKS` with display strings.
pub(crate) const PROVIDERS: &[ProviderEntry] = &[
    ProviderEntry {
        source: "baidu",
        cli_source: "baidu",
        provider: Some("baidu"),
        aliases: &["baidu-ai-search", "qianfan"],
        label: "Baidu AI 搜索",
        keyed: true,
        cookie: false,
    },
    ProviderEntry {
        source: "brave",
        cli_source: "brave",
        provider: Some("brave"),
        aliases: &[],
        label: "Brave 搜索",
        keyed: true,
        cookie: false,
    },
    ProviderEntry {
        source: "parallel",
        cli_source: "parallel",
        provider: Some("parallel"),
        aliases: &[],
        label: "Parallel",
        keyed: true,
        cookie: false,
    },
    ProviderEntry {
        source: "tavily",
        cli_source: "tavily",
        provider: Some("tavily"),
        aliases: &[],
        label: "Tavily",
        keyed: true,
        cookie: false,
    },
    ProviderEntry {
        source: "exa",
        cli_source: "exa",
        provider: Some("exa"),
        aliases: &[],
        label: "Exa",
        keyed: true,
        cookie: false,
    },
    ProviderEntry {
        source: "firecrawl",
        cli_source: "firecrawl",
        provider: Some("firecrawl"),
        aliases: &[],
        label: "Firecrawl",
        keyed: true,
        cookie: false,
    },
    ProviderEntry {
        source: "serpapi",
        cli_source: "serpapi",
        provider: Some("serpapi"),
        aliases: &[],
        label: "SerpAPI",
        keyed: true,
        cookie: false,
    },
    ProviderEntry {
        source: "github_repos",
        cli_source: "github-repos",
        provider: Some("github"),
        aliases: &["github", "github-repos"],
        label: "GitHub 仓库",
        keyed: true,
        cookie: false,
    },
    ProviderEntry {
        source: "hackernews",
        cli_source: "hackernews",
        provider: None,
        aliases: &[],
        label: "Hacker News",
        keyed: false,
        cookie: false,
    },
    ProviderEntry {
        source: "stackoverflow",
        cli_source: "stackoverflow",
        provider: None,
        aliases: &[],
        label: "Stack Overflow",
        keyed: false,
        cookie: false,
    },
    ProviderEntry {
        source: "sov2ex",
        cli_source: "sov2ex",
        provider: None,
        aliases: &["v2ex"],
        label: "V2EX",
        keyed: false,
        cookie: false,
    },
    ProviderEntry {
        source: "twitter",
        cli_source: "twitter",
        provider: None,
        aliases: &[],
        label: "Twitter",
        keyed: false,
        cookie: true,
    },
];

/// Resolve a raw source name or alias to its canonical entry.
/// Trims surrounding whitespace before matching. Returns the canonical
/// `ProviderEntry`; callers should use `entry.source` (settings) or
/// `entry.cli_source` (CLI `--source`) depending on context.
pub(crate) fn resolve(raw: &str) -> Result<&'static ProviderEntry, String> {
    let trimmed = raw.trim();
    PROVIDERS
        .iter()
        .find(|entry| {
            entry.source == trimmed
                || entry.cli_source == trimmed
                || entry.aliases.contains(&trimmed)
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
    PROVIDERS.iter().flat_map(|entry| {
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
/// `cookie`/`aliases` so the UI does not hardcode a copy.
#[derive(serde::Serialize, ts_rs::TS)]
#[ts(export_to = "types.d.ts")]
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
pub struct ProviderInfo {
    pub source: &'static str,
    #[serde(rename = "cliSource")]
    #[ts(rename = "cliSource")]
    pub cli_source: &'static str,
    pub provider: Option<&'static str>,
    pub label: &'static str,
    pub keyed: bool,
    pub cookie: bool,
    pub aliases: &'static [&'static str],
}

/// Snapshot of the manifest for the UI and for tests that need to enumerate
/// the table without depending on internals.
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
pub fn list() -> Vec<ProviderInfo> {
    PROVIDERS
        .iter()
        .map(|entry| ProviderInfo {
            source: entry.source,
            cli_source: entry.cli_source,
            provider: entry.provider,
            label: entry.label,
            keyed: entry.keyed,
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
        for (input, expected_source) in [
            ("baidu", "baidu"),
            ("qianfan", "baidu"),
            ("baidu-ai-search", "baidu"),
            ("github_repos", "github_repos"),
            ("github-repos", "github_repos"),
            ("github", "github_repos"),
            ("sov2ex", "sov2ex"),
            ("v2ex", "sov2ex"),
            ("twitter", "twitter"),
        ] {
            let entry = resolve(input).expect(input);
            assert_eq!(entry.source, expected_source, "input={input}");
        }
        for bad in ["", "   ", "../tavily", "tavily/../brave", "TAVILY", "jina"] {
            assert!(resolve(bad).is_err(), "input={bad:?} must be rejected");
        }
    }

    #[test]
    fn allowed_source_names_cover_canonical_alias_and_cli() {
        for name in [
            "baidu",
            "brave",
            "exa",
            "firecrawl",
            "github",
            "github_repos",
            "github-repos",
            "hackernews",
            "parallel",
            "serpapi",
            "sov2ex",
            "stackoverflow",
            "tavily",
            "twitter",
            "v2ex",
            "baidu-ai-search",
            "qianfan",
        ] {
            assert!(is_allowed_source(name), "{name}");
        }
        for bad in ["jina", "../etc", "TAVILY", ""] {
            assert!(!is_allowed_source(bad), "{bad}");
        }
    }

    #[test]
    fn keyed_and_cookie_are_mutually_exclusive() {
        for entry in PROVIDERS {
            assert!(
                !(entry.keyed && entry.cookie),
                "{} cannot be both keyed and cookie",
                entry.source
            );
            // Non-keyed non-cookie sources are still legitimate (hackernews, etc).
            // Cookie-only is exclusive to twitter.
            if entry.cookie {
                assert_eq!(entry.source, "twitter");
            }
        }
    }

    #[test]
    fn canonical_sources_are_unique() {
        let mut seen = std::collections::BTreeSet::new();
        for entry in PROVIDERS {
            assert!(
                seen.insert(entry.source),
                "duplicate canonical source {}",
                entry.source
            );
        }
        assert_eq!(seen.len(), PROVIDERS.len());
    }
}
