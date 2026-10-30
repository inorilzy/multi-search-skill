//! Credential editor against `~/.multi-search/keys.json` in a disposable HOME (never the real one).
use multi_search_desktop::credential_fixture as fixture;
use serde_json::{json, Value};
use std::{collections::BTreeMap, path::PathBuf};

const SYNTHETIC_KEY: &str = "synthetic-tavily-key-0001";

/// Unique temp home per test; removed on drop.
struct Home(PathBuf);
impl Home {
    fn new(tag: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "ms-keys-{tag}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).unwrap();
        Self(path)
    }
    fn vars(&self) -> BTreeMap<String, String> {
        BTreeMap::from([("HOME".into(), self.0.to_string_lossy().into_owned())])
    }
    fn file(&self) -> PathBuf {
        self.0.join(".multi-search/keys.json")
    }
    fn legacy(&self) -> PathBuf {
        self.0.join(".search-keys.json")
    }
    fn write(&self, text: &str) {
        std::fs::create_dir_all(self.file().parent().unwrap()).unwrap();
        std::fs::write(self.file(), text).unwrap();
    }
    fn json(&self) -> Value {
        serde_json::from_str(&std::fs::read_to_string(self.file()).unwrap()).unwrap()
    }
}
impl Drop for Home {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
fn keys(list: &[&str]) -> Vec<String> {
    list.iter().map(|s| s.to_string()).collect()
}
fn snapshot_of(home: &Home, source: &str) -> String {
    fixture::masked_for(&home.vars(), source).unwrap().snapshot
}

#[test]
fn keys_file_path_is_under_dot_multi_search_and_prefers_userprofile() {
    let home = Home::new("path");
    assert_eq!(fixture::keys_file_path(&home.vars()), Some(home.file()));
    let mut both = home.vars();
    both.insert("USERPROFILE".into(), "/profile".into());
    assert_eq!(fixture::keys_file_path(&both), Some(PathBuf::from("/profile/.multi-search/keys.json")));
    assert_eq!(fixture::keys_file_path(&BTreeMap::new()), None);
}

#[test]
fn save_creates_the_directory_trims_and_keeps_other_entries() {
    let home = Home::new("save");
    // No ~/.multi-search yet: the first save creates it.
    let row = fixture::save_for(&home.vars(), "tavily", &format!("  {SYNTHETIC_KEY}  ")).unwrap();
    assert_eq!(row.store.state, "present");
    assert_eq!(row.effective_source, "file");
    assert_eq!(home.json(), json!({"tavily": SYNTHETIC_KEY}));
    assert!(!format!("{row:?}").contains(SYNTHETIC_KEY));

    home.write(r#"{"brave":"b-key","future":{"x":[1,2]},"systemone":"s1","tavily":"old"}"#);
    fixture::save_for(&home.vars(), "tavily", "first-key\nsecond-key").unwrap();
    assert_eq!(
        home.json(),
        json!({"brave":"b-key","future":{"x":[1,2]},"systemone":"s1","tavily":["first-key","second-key"]})
    );
    // Key order on disk is preserved, so a diff of the file shows only the touched entry.
    let text = std::fs::read_to_string(home.file()).unwrap();
    assert!(text.find("brave").unwrap() < text.find("future").unwrap());
    assert!(text.find("systemone").unwrap() < text.find("tavily").unwrap());
}

#[test]
fn append_and_remove_rows_change_only_that_provider() {
    let home = Home::new("rows");
    home.write(r#"{"brave":["b1","b2"],"tavily":"k1"}"#);
    fixture::append_for(&home.vars(), "tavily", &keys(&["k2", " k3 "])).unwrap();
    assert_eq!(home.json(), json!({"brave":["b1","b2"],"tavily":["k1","k2","k3"]}));

    let snapshot = snapshot_of(&home, "tavily");
    assert_eq!(snapshot, fixture::snapshot("k1\nk2\nk3"));
    fixture::remove_row_for(&home.vars(), "tavily", 1, &snapshot).unwrap();
    assert_eq!(home.json(), json!({"brave":["b1","b2"],"tavily":["k1","k3"]}));

    // Removing the last rows deletes the entry, never the other providers.
    fixture::remove_row_for(&home.vars(), "tavily", 0, &fixture::snapshot("k1\nk3")).unwrap();
    let row = fixture::remove_row_for(&home.vars(), "tavily", 0, &fixture::snapshot("k3")).unwrap();
    assert_eq!(row.store.state, "absent");
    assert_eq!(row.effective_source, "none");
    assert_eq!(home.json(), json!({"brave":["b1","b2"]}));
}

#[test]
fn append_creates_an_absent_entry_and_a_single_key_stays_scalar() {
    let home = Home::new("append-absent");
    fixture::append_for(&home.vars(), "tavily", &keys(&["only"])).unwrap();
    assert_eq!(home.json(), json!({"tavily":"only"}));
}

#[test]
fn append_rejects_invalid_and_over_limit_without_writing() {
    let home = Home::new("append-invalid");
    home.write(r#"{"tavily":"orig"}"#);
    let before = std::fs::read(home.file()).unwrap();
    for bad in [keys(&[""]), keys(&["   "]), keys(&["line\u{7}break"]), keys(&[&"x".repeat(1025)]), vec![]] {
        assert!(fixture::append_for(&home.vars(), "tavily", &bad).is_err());
    }
    let many: Vec<String> = (0..257).map(|i| format!("synthetic-bulk-{i}")).collect();
    assert!(fixture::append_for(&home.vars(), "tavily", &many).is_err());
    assert_eq!(std::fs::read(home.file()).unwrap(), before);
}

#[test]
fn remove_is_guarded_by_the_snapshot_hash() {
    let home = Home::new("stale");
    home.write(r#"{"tavily":["k1","k2"]}"#);
    let before = std::fs::read(home.file()).unwrap();
    assert!(fixture::remove_row_for(&home.vars(), "tavily", 0, &fixture::snapshot("k1\nCHANGED")).is_err());
    assert!(fixture::remove_row_for(&home.vars(), "tavily", 5, &fixture::snapshot("k1\nk2")).is_err());
    assert!(fixture::remove_row_for(&home.vars(), "tavily", 0, "k1\nk2").is_err(), "raw text is not a hash");
    assert!(fixture::remove_row_for(&home.vars(), "brave", 0, &fixture::snapshot("k1")).is_err(), "absent entry");
    assert_eq!(std::fs::read(home.file()).unwrap(), before);
}

#[test]
fn remove_exact_duplicate_jina_row_drops_its_metadata() {
    let home = Home::new("dup-jina");
    let original = json!([
        {"key":"synthetic-dup","exhausted":true,"note":{"owner":"first"}},
        "synthetic-dup",
        {"key":"synthetic-dup","exhausted":false,"note":["second"]}
    ]);
    home.write(&json!({"jina": original}).to_string());
    fixture::remove_row_for(&home.vars(), "jina", 0, &fixture::snapshot("synthetic-dup\nsynthetic-dup\nsynthetic-dup")).unwrap();
    assert_eq!(home.json()["jina"], json!(["synthetic-dup", {"key":"synthetic-dup","exhausted":false,"note":["second"]}]));
    fixture::append_for(&home.vars(), "jina", &keys(&["synthetic-new"])).unwrap();
    assert_eq!(
        home.json()["jina"],
        json!(["synthetic-dup", {"key":"synthetic-dup","exhausted":false,"note":["second"]}, "synthetic-new"])
    );
}

#[test]
fn reveal_returns_plaintext_and_read_masks_first_and_last_four() {
    let home = Home::new("reveal");
    home.write(r#"{"tavily":["abcd-secret-wxyz","tiny"]}"#);
    assert_eq!(fixture::read_for(&home.vars(), "tavily").unwrap(), "abcd-secret-wxyz\ntiny");
    let masked = fixture::masked_for(&home.vars(), "tavily").unwrap();
    assert_eq!(masked.value, "abcd********wxyz\n********");
    assert_eq!(masked.snapshot, fixture::snapshot("abcd-secret-wxyz\ntiny"));
    assert!(fixture::read_for(&home.vars(), "../tavily").is_err());
    // Nothing saved: an empty editor, not an error.
    assert_eq!(fixture::read_for(&home.vars(), "brave").unwrap(), "");
}

#[test]
fn delete_removes_only_the_entry_and_works_on_any_shape() {
    let home = Home::new("delete");
    home.write(r#"{"tavily":[["nested"]],"brave":"b"}"#);
    let row = fixture::delete_for(&home.vars(), "tavily").unwrap();
    assert_eq!(row.store.state, "absent");
    assert_eq!(home.json(), json!({"brave":"b"}));
    // Deleting an absent entry does not create or rewrite the file.
    let other = Home::new("delete-absent");
    fixture::delete_for(&other.vars(), "tavily").unwrap();
    assert!(!other.file().exists());
}

#[cfg(unix)]
#[test]
fn every_write_leaves_the_file_owner_only() {
    use std::os::unix::fs::PermissionsExt;
    let home = Home::new("mode");
    home.write(r#"{"brave":"b"}"#);
    std::fs::set_permissions(home.file(), std::fs::Permissions::from_mode(0o644)).unwrap();
    let mode = || std::fs::metadata(home.file()).unwrap().permissions().mode() & 0o777;
    fixture::save_for(&home.vars(), "tavily", "k1").unwrap();
    assert_eq!(mode(), 0o600);
    fixture::append_for(&home.vars(), "tavily", &keys(&["k2"])).unwrap();
    assert_eq!(mode(), 0o600);
    fixture::remove_row_for(&home.vars(), "tavily", 0, &fixture::snapshot("k1\nk2")).unwrap();
    assert_eq!(mode(), 0o600);
    // No temp file is left next to it.
    let names: Vec<_> = std::fs::read_dir(home.file().parent().unwrap()).unwrap().map(|e| e.unwrap().file_name()).collect();
    assert_eq!(names, vec![std::ffi::OsString::from("keys.json")]);
}

#[test]
fn a_corrupt_keys_file_is_reported_and_never_overwritten() {
    let home = Home::new("corrupt");
    let corrupt = format!("{{not json {SYNTHETIC_KEY}");
    home.write(&corrupt);
    assert!(fixture::save_for(&home.vars(), "tavily", "k").unwrap_err().contains("不是有效的 JSON"));
    assert!(fixture::append_for(&home.vars(), "tavily", &keys(&["k"])).is_err());
    assert!(fixture::remove_row_for(&home.vars(), "tavily", 0, &fixture::snapshot("k")).is_err());
    assert!(fixture::delete_for(&home.vars(), "tavily").is_err());
    assert!(fixture::read_for(&home.vars(), "tavily").is_err());
    let row = fixture::overview(&home.vars());
    assert_eq!(row.store.state, "unavailable");
    assert!(!format!("{row:?}").contains(SYNTHETIC_KEY));
    assert_eq!(std::fs::read_to_string(home.file()).unwrap(), corrupt);
}

#[test]
fn an_unaddressable_entry_shape_rejects_row_ops_without_losing_data() {
    let home = Home::new("hidden-shape");
    let text = r#"{"tavily":[["nested"],"k1"]}"#;
    home.write(text);
    assert_eq!(fixture::overview(&home.vars()).store.state, "unreadable");
    assert!(fixture::append_for(&home.vars(), "tavily", &keys(&["k2"])).is_err());
    assert!(fixture::remove_row_for(&home.vars(), "tavily", 0, &fixture::snapshot("k1")).is_err());
    assert_eq!(std::fs::read_to_string(home.file()).unwrap(), text);
}

#[test]
fn empty_entries_count_as_absent() {
    let home = Home::new("empty");
    home.write(r#"{"tavily":"","brave":[],"exa":null}"#);
    for source in ["tavily", "brave", "exa"] {
        let row = fixture::overview_for(&home.vars(), source).unwrap();
        assert_eq!(row.store.state, "absent", "{source}");
        assert_eq!(row.effective_source, "none", "{source}");
    }
    fixture::append_for(&home.vars(), "brave", &keys(&["b1"])).unwrap();
    assert_eq!(home.json()["brave"], json!("b1"));
}

#[test]
fn the_legacy_file_is_copied_once_and_never_modified() {
    let home = Home::new("legacy");
    let legacy = r#"{"tavily":"legacy-key","unknown":true}"#;
    std::fs::write(home.legacy(), legacy).unwrap();
    assert_eq!(fixture::read_for(&home.vars(), "tavily").unwrap(), "legacy-key");
    assert_eq!(std::fs::read_to_string(home.file()).unwrap(), legacy, "byte-for-byte copy");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(std::fs::metadata(home.file()).unwrap().permissions().mode() & 0o777, 0o600);
    }
    fixture::save_for(&home.vars(), "tavily", "new-key").unwrap();
    assert_eq!(home.json(), json!({"tavily":"new-key","unknown":true}));
    // The old file is untouched and is not read again once the new one exists.
    assert_eq!(std::fs::read_to_string(home.legacy()).unwrap(), legacy);
    std::fs::write(home.legacy(), r#"{"tavily":"changed-legacy"}"#).unwrap();
    assert_eq!(fixture::read_for(&home.vars(), "tavily").unwrap(), "new-key");
}

#[test]
fn invalid_keys_are_rejected_without_echoing_the_value() {
    let home = Home::new("invalid");
    for bad in ["", "   ", "line\u{7}break", &"x".repeat(1025)] {
        let error = fixture::save_for(&home.vars(), "tavily", bad).unwrap_err();
        assert!(!error.contains(&"x".repeat(20)));
    }
    assert!(!home.file().exists());
}

#[test]
fn overview_without_core_never_reads_the_environment() {
    let home = Home::new("local");
    let mut vars = home.vars();
    vars.insert("TAVILY_API_KEY".into(), "synthetic-env-key-0003".into());
    let row = fixture::overview(&vars);
    // Env precedence is Core's answer; locally only the file is known.
    assert_eq!(row.effective_source, "none");
    let object = serde_json::to_value(&row).unwrap();
    for absent in ["env_var", "file_key_count", "store_supported", "store_unsupported_reason", "env_overrides_store"] {
        assert!(!object.as_object().unwrap().contains_key(absent), "{absent}");
    }
    assert!(!format!("{row:?}").contains("synthetic-env-key-0003"));
}

#[test]
fn test_outcome_classifies_provider_errors_and_success() {
    let payload = |status: &str, error_type: &str| {
        json!({
            "provider_status": [{
                "source": "tavily",
                "status": status,
                "errors": if error_type.is_empty() { json!([]) }
                    else { json!([{"error": "x", "error_type": error_type}]) },
            }]
        })
    };
    assert_eq!(fixture::interpret(&payload("ok", "")).result, "success");
    assert_eq!(fixture::interpret(&payload("error", "invalid")).result, "auth_failed");
    assert_eq!(fixture::interpret(&payload("error", "quota_exhausted")).result, "quota");
    assert_eq!(fixture::interpret(&payload("error", "rate_limit")).result, "rate_limited");
    assert_eq!(fixture::interpret(&payload("error", "network")).result, "network");
    assert_eq!(fixture::interpret(&payload("error", "timeout")).result, "timeout");
    assert_eq!(fixture::interpret(&payload("error", "missing_key")).result, "missing_key");
    assert_eq!(fixture::interpret(&json!({})).result, "error");
}

#[test]
fn test_args_never_contain_key_material() {
    let args = fixture::test_args("q");
    assert!(args.iter().all(|a| !a.contains(SYNTHETIC_KEY)));
    assert!(args.windows(2).any(|w| w == ["--source", "tavily"]));
    assert!(!args.iter().any(|a| a.contains("key")));
    assert!(args.iter().any(|a| a.as_str() == "--no-fetch"));
}

#[test]
fn test_args_pass_the_query_after_the_option_terminator() {
    let args = fixture::test_args("--count=999");
    let terminator = args.iter().position(|a| a.as_str() == "--").expect("query follows `--`");
    assert_eq!(args[terminator + 1], "--count=999");
    assert_eq!(terminator + 2, args.len(), "nothing may follow the query");
}
