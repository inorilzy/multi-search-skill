//! Contract test for the shared source catalog (issue 09, review H-04/L-01).
//!
//! Rust consumes `desktop/source-catalog.json`, generated from Python core by
//! `scripts/export_source_catalog.py`. These assertions prove the desktop
//! settings, execution allowlist, and credential management all derive their
//! names from that one artifact rather than from a Rust-local copy. The JS
//! mirror lives in `desktop/tests/source-catalog.test.js`; the Python side pins
//! the artifact to core in `tests/test_source_catalog.py`.
use multi_search_desktop::source_catalog_fixture as fixture;

const SEARCH_SOURCE_ORDER: &[&str] = &[
    "baidu", "brave", "parallel", "tavily", "exa", "firecrawl", "serpapi",
    "github_repos", "hackernews", "stackoverflow", "sov2ex", "twitter",
];
const SOURCE_ORDER: &[&str] = &[
    "baidu", "brave", "parallel", "tavily", "exa", "firecrawl", "serpapi",
    "github_repos", "hackernews", "stackoverflow", "sov2ex", "twitter", "jina",
];

#[test]
fn catalog_shape_and_shared_metadata_are_stable() {
    let catalog = fixture::catalog();
    assert_eq!(catalog.schema_version, 1);
    assert_eq!(
        catalog.key_resolution.order,
        vec!["env".to_string(), "credential_store".to_string(), "keys_file".to_string()],
    );
    assert_eq!(catalog.key_resolution.env_alias_priority, "last_non_empty_wins");
    assert_eq!(catalog.env.alias_priority, "last_non_empty_wins");
    assert!(!catalog.key_resolution.description.is_empty());

    let names: Vec<&str> = catalog.sources.iter().map(|source| source.name.as_str()).collect();
    assert_eq!(names, SOURCE_ORDER, "catalog display order is stable");
    let searchable: Vec<&str> = catalog.search_sources().map(|source| source.name.as_str()).collect();
    assert_eq!(searchable, SEARCH_SOURCE_ORDER);
    // Eight keyed search sources plus Jina (reader/scrape backend keys, not a search source).
    assert_eq!(catalog.credential_sources().count(), 9);
    assert_eq!(catalog.test_sources().count(), 12);
    assert_eq!(catalog.credential_store_providers.len(), 9);
    assert!(catalog.credential_store_providers.iter().any(|provider| provider == "jina"));

    assert_eq!(catalog.source_aliases.len(), 5);
    for (alias, canonical) in &catalog.source_aliases {
        let source = catalog.source(alias).unwrap_or_else(|| panic!("alias {alias} must resolve"));
        assert_eq!(&source.name, canonical, "alias {alias}");
    }

    for source in &catalog.sources {
        assert!(!source.label.trim().is_empty(), "{} has a label", source.name);
        assert!(!source.description.trim().is_empty(), "{} has a description", source.name);
        assert!(!source.mark.trim().is_empty(), "{} has a display mark", source.name);
        assert!(!source.public_name.trim().is_empty());
        if source.keyed {
            assert!(!source.env.is_empty(), "{} documents its env aliases", source.name);
            assert!(catalog.credential_store_providers.contains(&source.key_provider));
        }
        if source.name != "twitter" {
            assert!(!source.cookie, "{} is not a cookie source", source.name);
        }
    }

    assert_eq!(catalog.routes.len(), 5);
    for route in &catalog.routes {
        assert!(!route.label.trim().is_empty());
        assert!(!route.sources.is_empty());
        for name in &route.sources {
            let source = catalog.source(name).unwrap_or_else(|| panic!("{name} must exist"));
            assert!(source.searchable, "{name} in route {} must be searchable", route.name);
            assert!(source.routes.contains(&route.name), "{name} must advertise route {}", route.name);
        }
        for alias in &route.aliases {
            assert_eq!(catalog.route(alias).map(|item| item.name.as_str()), Some(route.name.as_str()));
        }
    }
}

#[test]
fn execution_allowlist_reads_the_catalog() {
    let catalog = fixture::catalog();
    for source in catalog.search_sources() {
        assert!(fixture::execution_allows(&source.name), "{} must be accepted", source.name);
        for alias in &source.aliases {
            assert!(fixture::execution_allows(alias), "alias {alias} must be accepted");
        }
    }
    for rejected in ["jina", "", "  ", "ta vily", "../etc", "TAVILY", "unknown"] {
        assert!(!fixture::execution_allows(rejected), "{rejected:?} must be rejected");
    }
    let jina = catalog.source("jina").expect("Jina stays in the catalog as a scraper");
    assert!(!jina.searchable, "Jina is scrape-only");
}

#[test]
fn settings_use_catalog_names_and_route_order() {
    let catalog = fixture::catalog();
    for source in catalog.search_sources() {
        assert_eq!(
            fixture::settings_source(&source.name).map(str::to_string),
            Some(source.name.clone()),
        );
        for alias in &source.aliases {
            assert_eq!(
                fixture::settings_source(alias).map(str::to_string),
                Some(source.name.clone()),
                "alias {alias} canonicalizes in settings",
            );
        }
    }
    assert_eq!(fixture::settings_source("jina"), None);
    assert_eq!(fixture::settings_source("unknown"), None);

    for route in &catalog.routes {
        let (name, sources) = fixture::route(&route.name).expect("known route");
        assert_eq!(name, route.name);
        assert_eq!(sources, route.sources.as_slice());
        for alias in &route.aliases {
            assert_eq!(fixture::route(alias).expect("route alias").0, route.name.as_str());
        }
        assert!(!sources.is_empty());
    }
    assert_eq!(fixture::route("default").expect("default route").1.len(), 7);
    assert_eq!(fixture::route("web").expect("web alias").0, "default");
    assert!(fixture::route("unknown").is_none());
}

#[test]
fn credentials_use_catalog_key_provider_env_and_label() {
    let catalog = fixture::catalog();
    for source in catalog.credential_sources() {
        // Credential IPC speaks the public (UI/CLI `--source`) spelling, e.g. `github-repos`.
        let (name, provider, env, label) = fixture::credential_source(&source.name).expect("keyed source");
        assert_eq!(name, source.public_name);
        assert_eq!(provider, source.key_provider);
        assert_eq!(env, source.env.as_slice());
        assert_eq!(label, source.label);
        for alias in &source.aliases {
            assert_eq!(
                fixture::credential_source(alias).expect("alias").0,
                source.public_name,
                "alias {alias} resolves to its canonical source",
            );
        }
    }
    let (name, provider, env, label) = fixture::credential_source("github").expect("github alias");
    assert_eq!((name, provider, label), ("github-repos", "github", "GitHub 仓库"));
    assert_eq!(env.to_vec(), vec!["GITHUB_TOKEN".to_string(), "GH_TOKEN".to_string()]);
    assert_eq!(
        fixture::credential_source("github_repos").expect("canonical name").0,
        "github-repos",
    );
    // Jina is a stored key (reader/scrape backend) but never a search or test source.
    assert_eq!(fixture::credential_source("jina").expect("jina keys are stored").1, "jina");
    assert!(fixture::credential_source("hackernews").is_err());

    for source in catalog.search_sources().filter(|source| !source.keyed) {
        assert_eq!(
            fixture::credential_test_source(&source.name).expect("test source"),
            source.public_name.as_str(),
        );
        assert!(fixture::credential_source(&source.name).is_err(), "{} has no key CRUD", source.name);
    }
    assert!(fixture::credential_test_source("jina").is_err());
}
