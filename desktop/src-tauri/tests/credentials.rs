//! Tavily credential store behaviour, against an in-memory backend (never the real store).
//! Blob format is pinned to the Python CredentialStore by the shared fixture below.
use multi_search_desktop::credential_fixture as fixture;
use std::{collections::BTreeMap, sync::Mutex};

const SYNTHETIC_KEY: &str = "synthetic-tavily-key-0001";

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

fn ns(name: &str) -> BTreeMap<String, String> {
    BTreeMap::from([("MULTI_SEARCH_CREDENTIAL_NAMESPACE".into(), name.into())])
}

#[test]
fn save_writes_namespaced_versioned_blob_and_trims_key() {
    let backend = Memory::default();
    let vars = ns("ns-test");
    fixture::save(
        &backend,
        &vars,
        &format!("  {SYNTHETIC_KEY}  "),
        1700000000.0,
    )
    .unwrap();
    let stored = backend.0.lock().unwrap();
    assert_eq!(stored.keys().collect::<Vec<_>>(), vec!["tavily"]);
    let blob: serde_json::Value = serde_json::from_slice(&stored["tavily"]).unwrap();
    assert_eq!(blob["v"], 1);
    assert_eq!(blob["key"], SYNTHETIC_KEY);
    assert_eq!(blob["saved_at"], 1700000000.0);
    assert_eq!(blob.as_object().unwrap().len(), 3);
}

#[test]
fn overview_reports_source_without_value_and_env_overrides_store() {
    let backend = Memory::default();
    let mut vars = ns("ns-test");
    fixture::save(&backend, &vars, SYNTHETIC_KEY, 1.0).unwrap();
    let store_only = fixture::overview(&backend, &vars);
    assert_eq!(store_only.effective_source, "sqlite");
    assert!(!serde_json::to_value(&store_only).unwrap().as_object().unwrap().contains_key("env_var"));
    assert!(!format!("{store_only:?}").contains(SYNTHETIC_KEY));

    vars.insert("TAVILY_API_KEY".into(), "synthetic-env-key-0003".into());
    let overridden = fixture::overview(&backend, &vars);
    assert_eq!(overridden.effective_source, "sqlite");
    assert_eq!(overridden, store_only);
    assert!(!format!("{overridden:?}").contains("synthetic-env-key-0003"));
}

#[test]
fn delete_then_absent_and_unreadable_entry_is_reported_not_echoed() {
    let backend = Memory::default();
    let vars = ns("ns-test");
    fixture::save(&backend, &vars, SYNTHETIC_KEY, 1.0).unwrap();
    assert_eq!(
        fixture::delete(&backend, &vars).unwrap().store.state,
        "absent"
    );

    backend.0.lock().unwrap().insert(
        "tavily".into(),
        format!("{{not json {SYNTHETIC_KEY}").into_bytes(),
    );
    let row = fixture::overview(&backend, &vars);
    assert_eq!(row.store.state, "unreadable");
    assert!(!format!("{row:?}").contains(SYNTHETIC_KEY));
}

#[test]
fn invalid_keys_rejected_without_echoing_value() {
    let backend = Memory::default();
    let vars = ns("ns-test");
    for bad in ["", "   ", "line\u{7}break", &"x".repeat(1025)] {
        let error = fixture::save(&backend, &vars, bad, 1.0).unwrap_err();
        assert!(!error.contains(SYNTHETIC_KEY));
        assert!(!error.contains(&"x".repeat(20)));
    }
    assert!(backend.0.lock().unwrap().is_empty());
}

#[test]
fn store_failure_is_explicit_and_never_falls_back() {
    struct Denied;
    impl fixture::Backend for Denied {
        fn read(&self, _: &str) -> Result<Option<Vec<u8>>, String> {
            Err("credential store access denied".into())
        }
        fn write(&self, _: &str, _: &[u8]) -> Result<(), String> {
            Err("credential store access denied".into())
        }
        fn delete(&self, _: &str) -> Result<bool, String> {
            Err("credential store access denied".into())
        }
    }
    let row = fixture::overview(&Denied, &ns("ns-test"));
    assert_eq!(row.store.state, "unavailable");
    assert_eq!(row.effective_source, "unavailable");
    assert!(fixture::save(&Denied, &ns("ns-test"), SYNTHETIC_KEY, 1.0).is_err());
}

#[test]
fn test_outcome_classifies_provider_errors_and_success() {
    let payload = |status: &str, error_type: &str| {
        serde_json::json!({
            "provider_status": [{
                "source": "tavily",
                "status": status,
                "errors": if error_type.is_empty() { serde_json::json!([]) }
                    else { serde_json::json!([{"error": "x", "error_type": error_type}]) },
            }]
        })
    };
    assert_eq!(fixture::interpret(&payload("ok", "")).result, "success");
    assert_eq!(
        fixture::interpret(&payload("error", "invalid")).result,
        "auth_failed"
    );
    assert_eq!(
        fixture::interpret(&payload("error", "quota_exhausted")).result,
        "quota"
    );
    assert_eq!(
        fixture::interpret(&payload("error", "rate_limit")).result,
        "rate_limited"
    );
    assert_eq!(
        fixture::interpret(&payload("error", "network")).result,
        "network"
    );
    assert_eq!(
        fixture::interpret(&payload("error", "timeout")).result,
        "timeout"
    );
    assert_eq!(fixture::interpret(&serde_json::json!({})).result, "error");
}

#[test]
fn test_args_never_contain_key_material() {
    let args = fixture::test_args("q");
    assert!(args.iter().all(|a| !a.contains(SYNTHETIC_KEY)));
    assert!(args.windows(2).any(|w| w == ["--source", "tavily"]));
    assert!(!args.iter().any(|a| a.contains("key")));
}

#[test]
fn multi_key_readback_is_one_per_line_and_overview_stays_non_secret() {
    let backend = Memory::default();
    let vars = ns("ignored");
    fixture::save(&backend, &vars, "first-key\nsecond-key", 1.0).unwrap();
    assert_eq!(
        fixture::read_for(&backend, &vars, "tavily").unwrap(),
        "first-key\nsecond-key"
    );
    assert!(fixture::read_for(&backend, &vars, "../tavily").is_err());
    let stored: serde_json::Value =
        serde_json::from_slice(&backend.0.lock().unwrap()["tavily"]).unwrap();
    assert_eq!(
        stored["key"],
        serde_json::json!(["first-key", "second-key"])
    );
    assert!(!format!("{:?}", fixture::overview(&backend, &vars)).contains("first-key"));
}

#[test]
fn rust_reads_blob_written_by_python_store() {
    // Byte-for-byte output of multi_search_mcp CredentialStore.set("tavily", ..., saved_at=1700000001.5).
    let python_blob = br#"{"v":1,"key":"synthetic-roundtrip-key-0009","saved_at":1700000001.5}"#;
    let backend = Memory::default();
    backend
        .0
        .lock()
        .unwrap()
        .insert("tavily".into(), python_blob.to_vec());
    let row = fixture::overview(&backend, &ns("ns-roundtrip"));
    assert_eq!(row.store.state, "present");
    assert_eq!(row.store.saved_at, Some(1700000001.5));
    assert!(!format!("{row:?}").contains("synthetic-roundtrip-key-0009"));
}

#[test]
fn rust_written_blob_has_contract_bytes() {
    // Exact bytes Rust writes; tests/test_credential_store.py decodes this same literal.
    let backend = Memory::default();
    fixture::save(
        &backend,
        &ns("ns-roundtrip"),
        "  synthetic-roundtrip-key-0009  ",
        1700000001.5,
    )
    .unwrap();
    let stored = backend.0.lock().unwrap()["tavily"].clone();
    assert_eq!(
        String::from_utf8(stored).unwrap(),
        r#"{"key":"synthetic-roundtrip-key-0009","saved_at":1700000001.5,"v":1}"#
    );
}
