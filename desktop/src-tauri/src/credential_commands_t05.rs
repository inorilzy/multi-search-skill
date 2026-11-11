use super::*;

#[test]
fn credential_probe_is_stateless() {
    assert!(test_args("probe", &resolve_test_source("tavily").unwrap()).contains(&"--no-state".into()));
}

#[test]
fn twitter_configuration_comes_from_core_booleans_without_cookie_contents() {
    for name in ["twitter", "twitter_cookies"] {
        let payload = serde_json::json!({"configured_keys": {name: true}});
        let sources = core_key_sources(&payload);
        assert_eq!(sources.get("twitter").unwrap().effective_source, "configured");
    }
    let sources = core_key_sources(&serde_json::json!({"configured_keys": {"twitter": false}}));
    assert_eq!(sources.get("twitter").unwrap().effective_source, "none");
}

#[cfg(unix)]
struct Fixture {
    home: PathBuf,
    cli: PathBuf,
    environment: crate::RuntimeEnvironment,
}

#[cfg(unix)]
impl Fixture {
    fn new() -> Self {
        use std::os::unix::fs::PermissionsExt;
        let home = crate::secure_temp::create_dir(&std::env::temp_dir(), "ms-t05-").unwrap();
        let cli = home.join("fixture-cli");
        std::fs::write(&cli, r#"#!/usr/bin/env python3
import json, os, pathlib, sys
home = pathlib.Path.home()
if sys.argv[1] == 'doctor':
    (home / 'doctor-state').write_text('synthetic state')
    print(json.dumps({'config_storage': {'backend': 'keys-file', 'schema_version': 1}}))
else:
    pool = []
    path = home / '.multi-search' / 'keys.json'
    if path.exists():
        value = json.loads(path.read_text()).get('tavily', [])
        pool = value if isinstance(value, list) else [value]
    if os.environ.get('TAVILY_API_KEY'):
        pool = [os.environ['TAVILY_API_KEY']]
    report = {
        'stateless': '--no-state' in sys.argv,
        'isolated_home': str(home) != os.environ['FIXTURE_ORIGINAL_HOME'],
        'key_count': len(pool),
        'selected_bad': pool == ['synthetic-bad'],
        'unrelated_key': 'EXA_API_KEY' in os.environ,
        'config_selector': os.environ.get('MULTI_SEARCH_CONFIG') == str(pathlib.Path(os.environ['FIXTURE_ORIGINAL_HOME']) / 'config.json'),
    }
    pathlib.Path(os.environ['FIXTURE_REPORT']).write_text(json.dumps(report))
    # Model Core's fallback: a good key anywhere in the pool would mask a bad key.
    ok = 'synthetic-good' in pool
    print(json.dumps({'provider_status': [{'source': 'tavily', 'status': 'ok' if ok else 'error', 'errors': [] if ok else [{'error_type': 'invalid'}]}]}))
"#).unwrap();
        std::fs::set_permissions(&cli, std::fs::Permissions::from_mode(0o700)).unwrap();
        let variables = BTreeMap::from([
            ("PATH".into(), std::env::var("PATH").unwrap()),
            ("HOME".into(), home.to_string_lossy().into_owned()),
            ("USERPROFILE".into(), home.to_string_lossy().into_owned()),
            ("EXA_API_KEY".into(), "synthetic-unrelated".into()),
            ("MULTI_SEARCH_CONFIG".into(), home.join("config.json").to_string_lossy().into_owned()),
            ("FIXTURE_ORIGINAL_HOME".into(), home.to_string_lossy().into_owned()),
            ("FIXTURE_REPORT".into(), home.join("report.json").to_string_lossy().into_owned()),
        ]);
        save(&variables, &resolve_source("tavily").unwrap(), "synthetic-good\nsynthetic-bad").unwrap();
        let environment = crate::RuntimeEnvironment { app_path: vec![], user_path: vec![], variables, cwd: home.clone() };
        Self { home, cli, environment }
    }
}

#[cfg(unix)]
impl Drop for Fixture {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.home).unwrap();
    }
}

#[cfg(unix)]
#[test]
fn selecting_a_saved_bad_key_overrides_a_good_environment_key() {
    let mut fixture = Fixture::new();
    fixture.environment.variables.insert("TAVILY_API_KEY".into(), "synthetic-good".into());
    let entry = resolve_test_source("tavily").unwrap();
    let snapshot = reveal(&fixture.environment.variables, &entry).unwrap().snapshot;
    let manager = CredentialManager { environment: &fixture.environment };
    let outcome = manager.test_key(fixture.cli.clone(), &entry, "probe", Some(1), Some(&snapshot)).unwrap();
    assert_eq!(outcome.result, "auth_failed");
    let outcome = manager.test_key(fixture.cli.clone(), &entry, "probe", Some(0), Some(&snapshot)).unwrap();
    assert_eq!(outcome.result, "success");
}

#[cfg(unix)]
#[test]
fn stale_or_missing_selection_is_rejected_before_a_child_can_start() {
    let fixture = Fixture::new();
    let entry = resolve_test_source("tavily").unwrap();
    let manager = CredentialManager { environment: &fixture.environment };
    assert!(manager.test_key(fixture.cli.clone(), &entry, "probe", Some(1), Some("stale")).is_err());
    assert!(manager.test_key(fixture.cli.clone(), &entry, "probe", Some(1), None).is_err());
    let snapshot = reveal(&fixture.environment.variables, &entry).unwrap().snapshot;
    assert!(manager.test_key(fixture.cli.clone(), &entry, "probe", Some(99), Some(&snapshot)).is_err());
    assert!(manager.test_key(fixture.cli.clone(), &entry, "probe", None, Some(&snapshot)).is_err());
    assert!(!fixture.home.join("report.json").exists());
}

#[test]
fn cookie_overview_does_not_enable_api_key_mutations() {
    assert_eq!(resolve_overview_source("twitter").unwrap().provider, "twitter");
    assert!(resolve_source("twitter").is_err());
}

#[cfg(unix)]
#[test]
fn a_bad_key_cannot_fall_back_to_the_good_key_in_the_saved_pool() {
    let fixture = Fixture::new();
    let keys_path = crate::keys_file::path(&fixture.environment.variables).unwrap();
    let before = std::fs::read(&keys_path).unwrap();
    let outcome = CredentialManager { environment: &fixture.environment }
        .test_source(fixture.cli.clone(), &resolve_test_source("tavily").unwrap(), "probe").unwrap();
    assert_eq!(outcome.result, "auth_failed");
    let report: Value = serde_json::from_slice(&std::fs::read(fixture.home.join("report.json")).unwrap()).unwrap();
    assert_eq!(report, serde_json::json!({
        "stateless": true, "isolated_home": true, "key_count": 1, "selected_bad": true,
        "unrelated_key": false, "config_selector": false,
    }));
    assert_eq!(std::fs::read(keys_path).unwrap(), before);
    assert!(!fixture.home.join("doctor-state").exists(), "even the handshake writes only inside the isolated home");
    assert!(!fixture.home.join(".multi-search/state.sqlite").exists());
}
