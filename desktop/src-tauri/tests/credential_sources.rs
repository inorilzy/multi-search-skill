//! Source allowlist, per-source overview and Jina editor semantics against a keys file in a
//! unique temp HOME; the real home is never read.
use multi_search_desktop::credential_fixture as fixture;
use serde_json::{json, Value};
use std::{collections::BTreeMap, path::PathBuf};

const SYNTHETIC_KEY: &str = "synthetic-source-key-0101";
const FILE_KEY_A: &str = "file-github-key-0102";
const FILE_KEY_B: &str = "file-github-key-0103";

const ALLOWED: &[&str] = &[
    "baidu",
    "brave",
    "parallel",
    "tavily",
    "exa",
    "firecrawl",
    "serpapi",
    "github-repos",
    "github-code",
    "stackoverflow",
];

struct Home(PathBuf);
impl Home {
    fn new(tag: &str) -> Self {
        let path = std::env::temp_dir().join(format!("ms-src-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).unwrap();
        Self(path)
    }
    fn vars(&self) -> BTreeMap<String, String> {
        BTreeMap::from([("USERPROFILE".into(), self.0.to_string_lossy().into_owned())])
    }
    fn file(&self) -> PathBuf {
        self.0.join(".multi-search/keys.json")
    }
    fn write_keys(&self, text: &str) {
        std::fs::create_dir_all(self.file().parent().unwrap()).unwrap();
        std::fs::write(self.file(), text).unwrap();
    }
    fn keys_text(&self) -> String {
        std::fs::read_to_string(self.file()).unwrap()
    }
    fn entry(&self, provider: &str) -> Value {
        serde_json::from_str::<Value>(&self.keys_text()).unwrap()[provider].clone()
    }
}
impl Drop for Home {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[test]
fn github_repos_maps_to_github_provider_and_unknown_names_are_rejected() {
    assert_eq!(fixture::resolve("github-repos").unwrap(), ("github-repos", "github"));
    assert_eq!(fixture::resolve("github_repos").unwrap(), ("github-repos", "github"));
    // `github` is a documented CLI alias routed to the `github` provider like the CLI does.
    assert_eq!(fixture::resolve("github").unwrap(), ("github-repos", "github"));
    // github-code shares the same `github` token entry.
    assert_eq!(fixture::resolve("github-code").unwrap(), ("github-code", "github"));
    assert_eq!(fixture::resolve("github_code").unwrap(), ("github-code", "github"));
    assert_eq!(fixture::resolve("tavily").unwrap(), ("tavily", "tavily"));
    for bad in ["", "  ", "../tavily", "tavily/../brave", "ns-src/tavily", "TAVILY"] {
        let error = fixture::resolve(bad).unwrap_err();
        assert_eq!(error, "不支持的搜索源", "input {bad:?}");
    }
}

#[test]
fn jina_credentials_round_trip_without_becoming_a_search_source() {
    let home = Home::new("jina");
    assert_eq!(fixture::resolve("jina").unwrap(), ("jina", "jina"));
    let row = fixture::save_for(&home.vars(), "jina", "synthetic-jina-a\nsynthetic-jina-b").unwrap();
    assert_eq!(row.source, "jina");
    assert_eq!(row.store.state, "present");
    assert_eq!(row.effective_source, "file");
    assert_eq!(fixture::read_for(&home.vars(), "jina").unwrap(), "synthetic-jina-a\nsynthetic-jina-b");
    assert_eq!(serde_json::from_str::<Value>(&home.keys_text()).unwrap().as_object().unwrap().len(), 1);
    assert!(fixture::source_test("jina", &json!({})).is_err());
    assert!(multi_search_desktop::provider::resolve_canonical("jina").is_none());
    let info = multi_search_desktop::provider::list().into_iter().find(|row| row.source == "jina").unwrap();
    assert!(info.keyed);
    assert!(!info.search);
}

#[test]
fn jina_structured_keys_are_visible_in_editor_without_silent_omission() {
    let home = Home::new("jina-structured");
    for value in [
        json!({"key":"synthetic-jina-a", "exhausted":true}),
        json!([{"key":"synthetic-jina-a", "exhausted":true}, "synthetic-jina-b"]),
    ] {
        let expected = if value.is_array() { "synthetic-jina-a\nsynthetic-jina-b" } else { "synthetic-jina-a" };
        home.write_keys(&json!({"jina": value}).to_string());
        assert_eq!(fixture::read_for(&home.vars(), "jina").unwrap(), expected);
    }
}

#[test]
fn jina_editor_save_preserves_metadata_of_unchanged_lines() {
    let home = Home::new("jina-merge");
    let vars = home.vars();
    let stored = json!([
        {"key":"synthetic-jina-a","exhausted":true,"note":"legacy"},
        "synthetic-jina-b",
        {"key":"synthetic-jina-c","exhausted":false}
    ]);
    let seed = |value: &Value| home.write_keys(&json!({"jina": value, "brave": "keep"}).to_string());
    seed(&stored);
    // Round-trip of unchanged editor text keeps every entry verbatim.
    let text = fixture::read_for(&vars, "jina").unwrap();
    assert_eq!(text, "synthetic-jina-a\nsynthetic-jina-b\nsynthetic-jina-c");
    fixture::save_for(&vars, "jina", &text).unwrap();
    assert_eq!(home.entry("jina"), stored);
    assert_eq!(home.entry("brave"), json!("keep"));
    // Reorder + remove c + add d: a keeps metadata, d is a plain new key, c is dropped.
    fixture::save_for(&vars, "jina", "synthetic-jina-d\nsynthetic-jina-a").unwrap();
    assert_eq!(home.entry("jina"), json!(["synthetic-jina-d", {"key":"synthetic-jina-a","exhausted":true,"note":"legacy"}]));
    // Editing a key's text is a new key: old metadata does not carry over.
    fixture::save_for(&vars, "jina", "synthetic-jina-a2").unwrap();
    assert_eq!(home.entry("jina"), json!("synthetic-jina-a2"));
    // A single structured entry stays an object.
    seed(&json!({"key":"synthetic-jina-a","exhausted":true}));
    fixture::save_for(&vars, "jina", "synthetic-jina-a").unwrap();
    assert_eq!(home.entry("jina"), json!({"key":"synthetic-jina-a","exhausted":true}));
    // Duplicate lines do not clone one entry's metadata.
    fixture::save_for(&vars, "jina", "synthetic-jina-a\nsynthetic-jina-a").unwrap();
    assert_eq!(home.entry("jina"), json!([{"key":"synthetic-jina-a","exhausted":true}, "synthetic-jina-a"]));
    let duplicate = json!(["synthetic-jina-a", {"key":"synthetic-jina-a","exhausted":true}]);
    seed(&duplicate);
    fixture::save_for(&vars, "jina", "synthetic-jina-a\nsynthetic-jina-a").unwrap();
    assert_eq!(home.entry("jina"), duplicate);
    // An unreadable existing entry must not silently erase metadata.
    home.write_keys(r#"{"jina":{"key":5}}"#);
    assert!(fixture::save_for(&vars, "jina", "synthetic-jina-a").is_err());
    assert_eq!(home.keys_text(), r#"{"jina":{"key":5}}"#);
}

#[test]
fn jina_editor_roundtrip_preserves_metadata_for_padded_stored_keys() {
    let home = Home::new("jina-padded");
    let stored = json!([
        {"key":" synthetic-jina-a ","exhausted":true,"note":{"legacy":true}},
        {"key":"synthetic-jina-b","exhausted":false}
    ]);
    home.write_keys(&json!({"jina": stored}).to_string());
    let text = fixture::read_for(&home.vars(), "jina").unwrap();
    fixture::save_for(&home.vars(), "jina", &text).unwrap();
    assert_eq!(home.entry("jina"), stored);
}

#[test]
fn non_jina_save_ignores_structured_merge() {
    let home = Home::new("non-jina");
    fixture::save_for(&home.vars(), "tavily", "synthetic-t-a\nsynthetic-t-b").unwrap();
    assert_eq!(home.entry("tavily"), json!(["synthetic-t-a", "synthetic-t-b"]));
}

#[test]
fn unknown_source_never_reaches_the_keys_file() {
    let home = Home::new("unknown");
    assert!(fixture::overview_for(&home.vars(), "../../other").is_err());
    assert!(fixture::save_for(&home.vars(), "../../other", "k").is_err());
    assert!(!home.file().exists());
}

#[test]
fn every_allowlisted_source_reads_only_its_own_provider_entry() {
    let home = Home::new("each");
    let mut map = serde_json::Map::new();
    for source in ALLOWED {
        let (_, provider) = fixture::resolve(source).unwrap();
        map.insert(provider.into(), json!(format!("{SYNTHETIC_KEY}-{provider}")));
    }
    home.write_keys(&Value::Object(map).to_string());
    for source in ALLOWED {
        let (_, provider) = fixture::resolve(source).unwrap();
        let row = fixture::overview_for(&home.vars(), source).unwrap();
        assert_eq!(row.source, *source);
        assert_eq!(row.store.state, "present", "{source} must read its own provider entry");
        assert_eq!(fixture::read_for(&home.vars(), source).unwrap(), format!("{SYNTHETIC_KEY}-{provider}"));
    }
    let providers: std::collections::BTreeSet<&str> = ALLOWED.iter().map(|s| fixture::resolve(s).unwrap().1).collect();
    // github-repos and github-code deliberately share the `github` token entry.
    assert_eq!(providers.len(), ALLOWED.len() - 1);
    assert_eq!(fixture::resolve("github-code").unwrap().1, fixture::resolve("github-repos").unwrap().1);
}

#[test]
fn github_repos_uses_github_entry_and_tavily_entry_does_not_satisfy_it() {
    let home = Home::new("github");
    home.write_keys(&json!({"tavily": SYNTHETIC_KEY}).to_string());
    let row = fixture::overview_for(&home.vars(), "github-repos").unwrap();
    assert_eq!(row.store.state, "absent", "tavily entry must not satisfy github-repos");
    assert_eq!(row.effective_source, "none");
    home.write_keys(&json!({"github": SYNTHETIC_KEY}).to_string());
    let row = fixture::overview_for(&home.vars(), "github-repos").unwrap();
    assert_eq!(row.store.state, "present");
    assert_eq!(row.effective_source, "file");
}

#[test]
fn file_list_is_reported_without_values() {
    let home = Home::new("filecount");
    let original = format!(r#"{{"github":["{FILE_KEY_A}","{FILE_KEY_B}"]}}"#);
    home.write_keys(&original);
    let row = fixture::overview_for(&home.vars(), "github-repos").unwrap();
    assert_eq!(row.effective_source, "file");
    // The count is Core's answer; the local overview omits it.
    assert!(!serde_json::to_value(&row).unwrap().as_object().unwrap().contains_key("file_key_count"));
    let text = format!("{row:?}");
    assert!(!text.contains(FILE_KEY_A));
    assert!(!text.contains(FILE_KEY_B));
    assert_eq!(home.keys_text(), original, "reading never rewrites the file");
}

#[test]
fn all_thirteen_source_tests_use_typed_cli_arguments_and_independent_status() {
    for source in ALLOWED.iter().copied().chain(["hackernews", "sov2ex", "twitter"]) {
        let payload = json!({"provider_status": [{"source": source.replace('-', "_"), "status": "ok"}]});
        let (args, outcome) = fixture::source_test(source, &payload).unwrap();
        assert_eq!(args[args.iter().position(|arg| arg == "--source").unwrap() + 1], source);
        assert_eq!(outcome.result, "success");
        let failed = json!({"provider_status": [{"source": source, "status": "failed", "errors": [{"error_type": "network"}]}]});
        assert_eq!(fixture::source_test(source, &failed).unwrap().1.result, "network");
        if !ALLOWED.contains(&source) {
            assert!(fixture::resolve(source).is_err(), "non-key source cannot access key CRUD");
        }
    }
    assert!(fixture::source_test("jina", &json!({})).is_err());
}

#[test]
fn environment_aliases_are_never_derived_locally() {
    let home = Home::new("alias");
    let mut vars = home.vars();
    for name in ["BAIDU_QIANFAN_API_KEY", "BRAVE_API_KEY", "TAVILY_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"] {
        vars.insert(name.into(), "synthetic-alias".into());
    }
    for source in ALLOWED {
        let row = fixture::overview_for(&vars, source).unwrap();
        assert_eq!(row.effective_source, "none");
        assert!(!serde_json::to_value(&row).unwrap().as_object().unwrap().contains_key("env_var"));
    }
}

#[test]
fn core_source_result_overrides_local_derivation() {
    let home = Home::new("core-source");
    home.write_keys(&format!(r#"{{"github":"{FILE_KEY_A}"}}"#));
    let doctor = json!({
        "key_sources": {
            "env": ["GITHUB_TOKEN"],
            "file": "~/.multi-search/keys.json",
            "github": {"effective_source": "file", "env_vars_set": [], "file_present": true, "file_key_count": 1},
            "exa": {"effective_source": "env", "env_vars_set": ["EXA_API_KEY"], "file_present": false, "file_key_count": 0}
        }
    });
    let row = fixture::overview_with_core(&home.vars(), "github-repos", &doctor).unwrap();
    assert_eq!(row.effective_source, "file");
    assert_eq!(row.file_key_count, Some(1), "Core's count is displayed");
    assert_eq!(row.env_var.as_deref(), Some(""));
    assert!(!format!("{row:?}").contains(FILE_KEY_A));

    // Core decides env precedence and which alias is effective, even with no local entry.
    let row = fixture::overview_with_core(&home.vars(), "exa", &doctor).unwrap();
    assert_eq!(row.store.state, "absent");
    assert_eq!(row.effective_source, "env");
    assert_eq!(row.env_var.as_deref(), Some("EXA_API_KEY"));
    assert_eq!(row.file_key_count, Some(0));
}

#[test]
fn payload_without_per_provider_rows_keeps_the_local_answer() {
    // `doctor --no-keys` (or an older CLI) has no per-provider section: nothing is applied, so the
    // overview shows `file` when keys.json has the provider and omits the Core-owned fields.
    let home = Home::new("no-core");
    home.write_keys(&format!(r#"{{"github":"{FILE_KEY_A}"}}"#));
    let doctor = json!({"key_sources": {"env": [], "file": "~/.multi-search/keys.json"}});
    let row = fixture::overview_with_core(&home.vars(), "github-repos", &doctor).unwrap();
    assert_eq!(row.effective_source, "file");
    let object = serde_json::to_value(&row).unwrap();
    for absent in ["env_var", "file_key_count"] {
        assert!(!object.as_object().unwrap().contains_key(absent), "{absent}");
    }
    let row = fixture::overview_with_core(&home.vars(), "brave", &doctor).unwrap();
    assert_eq!(row.effective_source, "none");
}
