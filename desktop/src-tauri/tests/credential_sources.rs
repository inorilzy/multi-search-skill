//! Source allowlist and per-source credential overview, against an in-memory backend.
//! The keys file lives in a unique temp directory; the real store and home are never read.
use multi_search_desktop::credential_fixture as fixture;
use std::{collections::BTreeMap, path::PathBuf, sync::Mutex};

const SYNTHETIC_KEY: &str = "synthetic-source-key-0101";
const FILE_KEY_A: &str = "file-github-key-0102";
const FILE_KEY_B: &str = "file-github-key-0103";

const ALLOWED: &[&str] = &["baidu", "brave", "parallel", "tavily", "exa", "firecrawl", "serpapi", "github-repos"];

#[derive(Default)]
struct Memory(Mutex<BTreeMap<String, Vec<u8>>>);
impl fixture::Backend for Memory {
    fn read(&self, target: &str) -> Result<Option<Vec<u8>>, String> {
        Ok(self.0.lock().unwrap().get(target).cloned())
    }
    fn write(&self, target: &str, blob: &[u8]) -> Result<(), String> {
        self.0.lock().unwrap().insert(target.into(), blob.to_vec());
        Ok(())
    }
    fn delete(&self, target: &str) -> Result<bool, String> {
        Ok(self.0.lock().unwrap().remove(target).is_some())
    }
}

/// Unique temp home per test; removed on drop.
struct Home(PathBuf);
impl Home {
    fn new(tag: &str) -> Self {
        let path = std::env::temp_dir().join(format!("ms-src-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).unwrap();
        Self(path)
    }
    fn vars(&self) -> BTreeMap<String, String> {
        BTreeMap::from([
            ("MULTI_SEARCH_CREDENTIAL_NAMESPACE".into(), "ns-src".into()),
            ("USERPROFILE".into(), self.0.to_string_lossy().into_owned()),
        ])
    }
    fn write_keys(&self, text: &str) {
        std::fs::write(self.0.join(".search-keys.json"), text).unwrap();
    }
    fn keys_text(&self) -> String {
        std::fs::read_to_string(self.0.join(".search-keys.json")).unwrap()
    }
}
impl Drop for Home {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn store_blob(key: &str) -> Vec<u8> {
    format!(r#"{{"v":1,"key":"{key}","saved_at":1.0}}"#).into_bytes()
}

#[test]
fn github_repos_maps_to_github_provider_and_unknown_names_are_rejected() {
    assert_eq!(fixture::resolve("github-repos").unwrap(), ("github-repos", "github"));
    assert_eq!(fixture::resolve("github_repos").unwrap(), ("github-repos", "github"));
    assert_eq!(fixture::resolve("tavily").unwrap(), ("tavily", "tavily"));
    for bad in ["", "  ", "../tavily", "tavily/../brave", "github", "jina", "ns-src/tavily", "TAVILY"] {
        let error = fixture::resolve(bad).unwrap_err();
        assert_eq!(error, "不支持的搜索源", "input {bad:?}");
    }
}

#[test]
fn unknown_source_never_reaches_the_backend() {
    let backend = Memory::default();
    let home = Home::new("unknown");
    assert!(fixture::overview_for(&backend, &home.vars(), "../../other").is_err());
    assert!(backend.0.lock().unwrap().is_empty());
}

#[test]
fn every_allowlisted_source_reads_only_its_own_provider_target() {
    let backend = Memory::default();
    let home = Home::new("each");
    // Pre-seed one entry per provider; each source must see only its own.
    for source in ALLOWED {
        let (_, provider) = fixture::resolve(source).unwrap();
        backend
            .0
            .lock()
            .unwrap()
            .insert(format!("ns-src/{provider}"), store_blob(SYNTHETIC_KEY));
    }
    for source in ALLOWED {
        let row = fixture::overview_for(&backend, &home.vars(), source).unwrap();
        assert_eq!(row.source, *source);
        assert_eq!(row.store.state, "present", "{source} must read its own provider entry");
    }
    // github-repos and github share one provider entry, so 8 sources map to 8 distinct targets
    // (tavily, baidu, brave, parallel, exa, firecrawl, serpapi, github).
    let providers: std::collections::BTreeSet<&str> =
        ALLOWED.iter().map(|s| fixture::resolve(s).unwrap().1).collect();
    assert_eq!(providers.len(), ALLOWED.len());
    assert_eq!(backend.0.lock().unwrap().len(), ALLOWED.len());
}

#[test]
fn github_repos_uses_github_entry_and_tavily_entry_does_not_satisfy_it() {
    let backend = Memory::default();
    let home = Home::new("github");
    backend.0.lock().unwrap().insert("ns-src/tavily".into(), store_blob(SYNTHETIC_KEY));
    let row = fixture::overview_for(&backend, &home.vars(), "github-repos").unwrap();
    assert_eq!(row.store.state, "absent", "tavily entry must not satisfy github-repos");
    assert_eq!(row.effective_source, "none");

    backend.0.lock().unwrap().insert("ns-src/github".into(), store_blob(SYNTHETIC_KEY));
    let row = fixture::overview_for(&backend, &home.vars(), "github-repos").unwrap();
    assert_eq!(row.store.state, "present");
    assert_eq!(row.effective_source, "credential_store");
}

#[test]
fn file_list_is_reported_by_count_and_never_by_value() {
    let backend = Memory::default();
    let home = Home::new("filecount");
    home.write_keys(&format!(r#"{{"github":["{FILE_KEY_A}","{FILE_KEY_B}"]}}"#));
    let row = fixture::overview_for(&backend, &home.vars(), "github-repos").unwrap();
    assert_eq!(row.effective_source, "file");
    assert_eq!(row.file_key_count, 2);
    let text = format!("{row:?}");
    assert!(!text.contains(FILE_KEY_A));
    assert!(!text.contains(FILE_KEY_B));
}

#[test]
fn store_overrides_file_list_and_file_is_untouched() {
    let backend = Memory::default();
    let home = Home::new("override");
    let original = format!(r#"{{"github":["{FILE_KEY_A}","{FILE_KEY_B}"]}}"#);
    home.write_keys(&original);
    backend.0.lock().unwrap().insert("ns-src/github".into(), store_blob(SYNTHETIC_KEY));
    let row = fixture::overview_for(&backend, &home.vars(), "github-repos").unwrap();
    assert_eq!(row.effective_source, "credential_store");
    assert_eq!(row.file_key_count, 2, "file list stays listed and counted");
    assert!(!format!("{row:?}").contains(SYNTHETIC_KEY));
    assert_eq!(home.keys_text(), original);
}

#[test]
fn env_override_is_named_by_variable_and_never_valued() {
    let backend = Memory::default();
    let home = Home::new("env");
    backend.0.lock().unwrap().insert("ns-src/exa".into(), store_blob(SYNTHETIC_KEY));
    let mut vars = home.vars();
    vars.insert("EXA_API_KEY".into(), "synthetic-env-exa-0104".into());
    let row = fixture::overview_for(&backend, &vars, "exa").unwrap();
    assert_eq!(row.effective_source, "env");
    assert!(row.env_overrides_store);
    assert_eq!(row.env_var, "EXA_API_KEY");
    assert!(!format!("{row:?}").contains("synthetic-env-exa-0104"));
}

#[test]
fn all_twelve_source_tests_use_typed_cli_arguments_and_independent_status() {
    for source in ALLOWED.iter().copied().chain(["hackernews", "stackoverflow", "sov2ex", "twitter"]) {
        let payload = serde_json::json!({"provider_status": [{"source": source.replace('-', "_"), "status": "ok"}]});
        let (args, outcome) = fixture::source_test(source, &payload).unwrap();
        assert_eq!(args[args.iter().position(|arg| arg == "--source").unwrap() + 1], source);
        assert_eq!(outcome.result, "success");
        let failed = serde_json::json!({"provider_status": [{"source": source, "status": "failed", "errors": [{"error_type": "network"}]}]});
        assert_eq!(fixture::source_test(source, &failed).unwrap().1.result, "network");
        if !ALLOWED.contains(&source) { assert!(fixture::resolve(source).is_err(), "non-key source cannot access key CRUD"); }
    }
    assert!(fixture::source_test("jina", &serde_json::json!({})).is_err());
}

#[test]
fn environment_alias_precedence_matches_real_python_load_keys_contract() {
    let home = Home::new("cross-language-alias");
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"
import json, sys
from pathlib import Path
from multi_search_mcp.src.state.keys import KEY_ENV_PAIRS, CREDENTIAL_STORE_PROVIDERS, load_keys
cases = []
for provider in CREDENTIAL_STORE_PROVIDERS:
    aliases = [name for name, key in KEY_ENV_PAIRS if key == provider]
    for length in range(1, len(aliases) + 1):
        present = aliases[:length]
        env = {name: 'synthetic-alias-' + str(i) for i, name in enumerate(present)}
        env.update({name: '' for name in aliases[length:]})
        loaded = load_keys(keys_file=Path(sys.argv[1]) / 'absent.json', environ=env)
        expected = next(name for name in present if env[name] == loaded[provider])
        cases.append({'provider': provider, 'present': present, 'empty': aliases[length:], 'expected': expected})
print(json.dumps(cases))
"#;
    let output = std::process::Command::new("python").args(["-B", "-c", script])
        .arg(&home.0).env("PYTHONPATH", &root).env("HOME", &home.0).env("USERPROFILE", &home.0)
        .env("MULTI_SEARCH_TEST_ISOLATION", "1").output().unwrap();
    assert!(output.status.success(), "Python contract process failed");
    let cases: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let backend = Memory::default();
    for case in cases.as_array().unwrap() {
        let provider = case["provider"].as_str().unwrap();
        let source = if provider == "github" { "github-repos" } else { provider };
        let mut vars = home.vars();
        for name in case["present"].as_array().unwrap() { vars.insert(name.as_str().unwrap().into(), "synthetic-alias".into()); }
        for name in case["empty"].as_array().unwrap() { vars.insert(name.as_str().unwrap().into(), String::new()); }
        let row = fixture::overview_for(&backend, &vars, source).unwrap();
        assert_eq!(row.env_var, case["expected"].as_str().unwrap(), "{source}");
        assert_eq!(row.effective_source, "env");
    }
}

#[test]
fn corrupt_keys_file_counts_as_zero_and_is_not_echoed() {
    let backend = Memory::default();
    let home = Home::new("corrupt");
    home.write_keys(&format!("{{not json {FILE_KEY_A}"));
    let row = fixture::overview_for(&backend, &home.vars(), "brave").unwrap();
    assert_eq!(row.file_key_count, 0);
    assert_eq!(row.effective_source, "none");
    assert!(!format!("{row:?}").contains(FILE_KEY_A));
}
