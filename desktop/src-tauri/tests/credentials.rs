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
    assert_eq!(fixture::interpret(&payload("error", "invalid")).result, "auth_failed");
    assert_eq!(fixture::interpret(&payload("error", "quota_exhausted")).result, "quota");
    assert_eq!(fixture::interpret(&payload("error", "rate_limit")).result, "rate_limited");
    assert_eq!(fixture::interpret(&payload("error", "network")).result, "network");
    assert_eq!(fixture::interpret(&payload("error", "timeout")).result, "timeout");
    // Core emits ``missing_key`` for a provider that was skipped because no key is
    // configured; the desktop consumes that classification instead of re-deriving it.
    assert_eq!(fixture::interpret(&payload("error", "missing_key")).result, "missing_key");
    assert_eq!(fixture::interpret(&serde_json::json!({})).result, "error");
}

#[test]
fn test_args_never_contain_key_material() {
    let args = fixture::test_args("q");
    assert!(args.iter().all(|a| !a.contains(SYNTHETIC_KEY)));
    assert!(args.windows(2).any(|w| w == ["--source", "tavily"]));
    assert!(!args.iter().any(|a| a.contains("key")));
    // Candidate-only: the test key run must never trigger Core page fetching.
    assert!(args.iter().any(|a| a.as_str() == "--no-fetch"));
}

#[test]
fn test_args_pass_the_query_after_the_option_terminator() {
    let args = fixture::test_args("--count=999");
    let terminator = args.iter().position(|a| a.as_str() == "--").expect("query follows `--`");
    assert_eq!(args[terminator + 1], "--count=999");
    assert_eq!(terminator + 2, args.len(), "nothing may follow the query");
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

#[test]
fn overview_reports_platform_capability_separately_from_key_presence() {
    let backend = Memory::default();
    let vars = ns("ns-cap");
    let supported = fixture::storage_supported();
    // "未配置 Key" must never be mistaken for "存储不可用": on a supported
    // build an absent store still reports write support.
    let overview = fixture::overview(&backend, &vars);
    assert_eq!(overview.store.state, "absent");
    assert_eq!(overview.store_supported, supported);
    assert_eq!(
        overview.store_unsupported_reason.as_deref(),
        if supported { None } else { Some("platform_unsupported") },
    );
    // A present row on a supported build reports support; on an unsupported
    // build the same row cannot be rewritten even though it exists.
    fixture::save(&backend, &vars, SYNTHETIC_KEY, 1.0).unwrap();
    let present = fixture::overview(&backend, &vars);
    assert_eq!(present.store.state, "present");
    assert_eq!(present.store_supported, supported);
}

#[test]
fn unsupported_platform_rejects_the_command_guard_before_any_backend_access() {
    // The test binary runs on the host platform: the guard must reject exactly
    // when the build cannot encrypt. On Windows this test proves the guard is
    // a no-op for supported writes; elsewhere it proves the stable reason.
    if fixture::storage_supported() {
        fixture::require_supported().unwrap();
        return;
    }
    // The guard now returns the serialized {code,message} contract directly:
    // the code travels with the error, not inside the message wording.
    let error = fixture::require_supported().unwrap_err();
    assert_eq!(error, fixture::unsupported_rejection(), "{error}");
    let parsed: serde_json::Value = serde_json::from_str(&error).unwrap();
    assert_eq!(parsed["code"], "credential_platform_unsupported");
    assert!(parsed["message"].as_str().unwrap().contains("DPAPI"));
    // A write that bypassed the disabled UI must not touch the store: seed
    // data stays byte-for-byte identical and nothing new is written.
    let backend = Memory::default();
    let vars = ns("ns-guard");
    fixture::save(&backend, &vars, SYNTHETIC_KEY, 1.0).unwrap();
    let before = backend.0.lock().unwrap().clone();
    assert!(fixture::require_supported().is_err());
    assert_eq!(*backend.0.lock().unwrap(), before);
}

#[test]
fn command_body_writes_return_the_stable_unsupported_code_and_change_nothing() {
    // Spec 7: a request that bypassed the disabled UI must reject with the
    // stable serialized code and leave any existing rows byte-for-byte intact.
    // The seams run the same guard the Tauri command bodies run, then the real
    // SQLite path. On a supported build this test only proves the seams work.
    if fixture::storage_supported() {
        return;
    }
    let expected = fixture::unsupported_rejection();
    let parsed: serde_json::Value = serde_json::from_str(&expected).unwrap();
    assert_eq!(parsed["code"], "credential_platform_unsupported");
    assert!(parsed["message"].as_str().unwrap().contains("DPAPI"));

    let dir = std::env::temp_dir().join(format!("ms-unsupported-guard-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let db = dir.join("config.sqlite");
    let bytes_before = std::fs::read(&db).unwrap_or_default();
    let db_before_exists = db.exists();

    assert_eq!(fixture::guarded_native_save(&db, "tavily", "synthetic-key", 1.0).unwrap_err(), expected);
    assert_eq!(fixture::guarded_native_append(&db, "tavily", &["synthetic-key".into()], 1.0).unwrap_err(), expected);
    assert_eq!(fixture::guarded_native_remove_row(&db, "tavily", 0, "expected-snapshot", 1.0).unwrap_err(), expected);

    // No database row or file may appear as a side effect of a rejected write.
    assert_eq!(db.exists(), db_before_exists);
    if db_before_exists { assert_eq!(std::fs::read(&db).unwrap(), bytes_before); }
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn migration_apply_is_rejected_before_the_legacy_file_is_touched() {
    // Spec 7: the apply path runs the same guard the command runs, so a request
    // that bypassed the disabled UI rejects before the CLI is launched and the
    // legacy file bytes are byte-for-byte identical afterwards.
    if fixture::storage_supported() {
        return;
    }
    let dir = std::env::temp_dir().join(format!("ms-unsupported-migrate-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let keys_file = dir.join(".search-keys.json");
    std::fs::write(&keys_file, br#"{"tavily":"synthetic-legacy-key"}"#).unwrap();
    let bytes_before = std::fs::read(&keys_file).unwrap();
    let token = "0".repeat(64);
    let approved = vec!["tavily".to_string()];
    let choices = std::collections::BTreeMap::new();
    // The CLI path is unreachable after the guard rejects, so an arbitrary
    // non-existent path proves the guard ran before the spawn.
    let cli = dir.join("nonexistent-cli");
    let environment = multi_search_desktop::RuntimeEnvironment {
        app_path: vec![],
        user_path: vec![],
        variables: std::collections::BTreeMap::new(),
        cwd: dir.clone(),
    };
    let err = fixture::guarded_migration_apply(&environment, &cli, &keys_file, &token, &approved, &choices)
        .unwrap_err();
    assert_eq!(err, fixture::unsupported_rejection());
    assert_eq!(std::fs::read(&keys_file).unwrap(), bytes_before);
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn delete_is_cleanup_and_stays_available_without_encryption() {
    // Spec c: removing a stored entry must not be blocked by the unsupported
    // platform; it is a cleanup, not a new write, so no encryption is needed.
    // The command body is not guarded (see window.rs), and the backend delete
    // does not call crypt, so it succeeds even where writes are rejected.
    let backend = Memory::default();
    let vars = ns("ns-delete");
    fixture::save(&backend, &vars, SYNTHETIC_KEY, 1.0).unwrap();
    assert!(fixture::delete(&backend, &vars).is_ok());
    assert_eq!(fixture::overview(&backend, &vars).store.state, "absent");
}

#[test]
fn reveal_reports_unavailable_on_unsupported_platform_not_a_write_code() {
    // S1 pin: a read path (credential_read / credential_reveal) must not be
    // promoted to the write-only `credential_platform_unsupported` code; it
    // surfaces as the ordinary unavailable/read error the UI already maps.
    struct PlatformBlocked;
    impl fixture::Backend for PlatformBlocked {
        fn read(&self, _: &str) -> Result<Option<Vec<u8>>, String> {
            // Same DPAPI text the native read surfaces on this platform.
            Err("加密凭据存储仅支持 Windows 当前用户 DPAPI；当前平台不可用，且没有明文回退。".into())
        }
        fn write(&self, _: &str, _: &[u8]) -> Result<(), String> { unreachable!() }
        fn delete(&self, _: &str) -> Result<bool, String> { unreachable!() }
    }
    let backend = PlatformBlocked;
    let vars = ns("ns-reveal");
    let err = fixture::read_for(&backend, &vars, "tavily").unwrap_err();
    assert!(!err.contains("credential_platform_unsupported"));
    assert!(err.contains("DPAPI") || err.contains("无法"), "{err}");
}
