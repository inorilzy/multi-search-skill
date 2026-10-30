//! Cookie import in file mode against a disposable HOME and settings database only.
use multi_search_desktop::{cookie, RuntimeEnvironment};
use std::{collections::BTreeMap, path::PathBuf};
struct Sandbox(PathBuf);
impl Sandbox {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!("ms-cookie-{}-{}", std::process::id(), NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).unwrap();
        Self(path)
    }
    fn env(&self) -> RuntimeEnvironment {
        RuntimeEnvironment { app_path: vec![], user_path: vec![], cwd: self.0.clone(), variables: BTreeMap::from([("HOME".into(), self.0.to_string_lossy().into_owned())]) }
    }
    fn db(&self) -> PathBuf { self.0.join(".multi-search/config.sqlite") }
    fn managed(&self) -> PathBuf { self.0.join(".multi-search/twitter-cookies.json") }
    fn source(&self) -> PathBuf { self.0.join("cookies.json") }
    fn seed(&self) -> Vec<u8> {
        let raw = b"\xef\xbb\xbf{\"auth_token\":\"synthetic-auth-0123456789\",\"ct0\":\"synthetic-csrf-0123456789\",\"guest_id\":\"guest\"}".to_vec();
        std::fs::write(self.source(), &raw).unwrap();
        raw
    }
    fn settings(&self) -> serde_json::Value {
        let c = rusqlite::Connection::open(self.db()).unwrap();
        let raw: String = c.query_row("SELECT data FROM settings WHERE id=1", [], |r| r.get(0)).unwrap();
        serde_json::from_str(&raw).unwrap()
    }
    fn set_settings(&self, body: &str) {
        // Create the schema and the record through the desktop, then replace the record.
        multi_search_desktop::settings_fixture::save(&self.env(), &multi_search_desktop::settings_fixture::SettingsInput {
            route: "default".into(), timeout: None, disabled_sources: vec![], routes: None,
            twitter_cookies_path: None, scrape_backends: None, ranking: None,
        }).unwrap();
        let c = rusqlite::Connection::open(self.db()).unwrap();
        c.execute("UPDATE settings SET data=?1 WHERE id=1", [body]).unwrap();
    }
}
impl Drop for Sandbox { fn drop(&mut self) { let _ = std::fs::remove_dir_all(&self.0); } }

#[test]
fn confirmation_precedes_io_and_status_is_read_only() {
    let s = Sandbox::new();
    let status = cookie::status(&s.env()).unwrap();
    assert_eq!(status.mode, "file");
    assert!(!status.present);
    assert_eq!(status.path.as_deref(), s.managed().to_str());
    assert_eq!(status.configured_path, None);
    assert!(!s.db().exists());
    assert!(cookie::import(&s.env(), &s.source(), false).unwrap_err().contains("Confirm"));
    assert!(cookie::delete(&s.env(), false).unwrap_err().contains("Confirm"));
    assert!(!s.db().exists());
    assert!(!s.managed().exists());
}

#[test]
fn import_copies_the_file_and_points_the_setting_at_it() {
    let s = Sandbox::new();
    let original = s.seed();
    s.set_settings(r#"{"type":"default","future":42,"twitter_cookies_mode":"managed"}"#);
    let status = cookie::import(&s.env(), &s.source(), true).unwrap();
    assert!(status.present);
    assert_eq!(status.mode, "file");
    let managed = s.managed().to_string_lossy().into_owned();
    assert_eq!(status.configured_path.as_deref(), Some(managed.as_str()));
    // The copy is the validated map (BOM dropped) and the source is untouched.
    let copy: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(s.managed()).unwrap()).unwrap();
    assert_eq!(copy["auth_token"], "synthetic-auth-0123456789");
    assert_eq!(copy["guest_id"], "guest");
    assert_eq!(std::fs::read(s.source()).unwrap(), original);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(std::fs::metadata(s.managed()).unwrap().permissions().mode() & 0o777, 0o600);
    }
    // Only twitter_cookies_path changed; unknown fields and the legacy mode key are left alone.
    let settings = s.settings();
    assert_eq!(settings["twitter_cookies_path"], managed.as_str());
    assert_eq!(settings["future"], 42);
    assert_eq!(settings["twitter_cookies_mode"], "managed");
    assert_eq!(multi_search_desktop::settings_fixture::view(&s.env()).twitter_cookies_path.as_deref(), Some(managed.as_str()));
    // Status never carries cookie values.
    let serialized = serde_json::to_string(&cookie::status(&s.env()).unwrap()).unwrap();
    assert!(!serialized.contains("synthetic-auth"));
    // Re-import replaces the copy.
    std::fs::write(s.source(), r#"{"auth_token":"synthetic-auth-2","ct0":"synthetic-csrf-2"}"#).unwrap();
    cookie::import(&s.env(), &s.source(), true).unwrap();
    assert!(std::fs::read_to_string(s.managed()).unwrap().contains("synthetic-auth-2"));
}

#[test]
fn delete_removes_the_copy_and_clears_only_a_matching_setting() {
    let s = Sandbox::new();
    let original = s.seed();
    cookie::import(&s.env(), &s.source(), true).unwrap();
    let gone = cookie::delete(&s.env(), true).unwrap();
    assert!(!gone.present);
    assert_eq!(gone.configured_path, None);
    assert!(!s.managed().exists());
    assert!(s.settings().get("twitter_cookies_path").is_none());
    assert_eq!(std::fs::read(s.source()).unwrap(), original, "the source file is never deleted");
    // A setting that points elsewhere is the user's explicit file: delete leaves it.
    s.set_settings(r#"{"type":"default","twitter_cookies_path":"/elsewhere/cookies.json"}"#);
    let kept = cookie::delete(&s.env(), true).unwrap();
    assert_eq!(kept.configured_path.as_deref(), Some("/elsewhere/cookies.json"));
    assert_eq!(s.settings()["twitter_cookies_path"], "/elsewhere/cookies.json");
}

#[test]
fn invalid_and_oversized_maps_never_echo_or_persist() {
    let s = Sandbox::new();
    for raw in ["broken-secret", "{}", "[]", r#"{"auth_token":5,"ct0":"secret"}"#, r#"{"auth_token":"secret","ct0":"secret","bad-name":"secret"}"#, r#"{"auth_token":"secret\n","ct0":"secret"}"#, r#"{"ct0":"secret"}"#] {
        std::fs::write(s.source(), raw).unwrap();
        let error = cookie::import(&s.env(), &s.source(), true).unwrap_err();
        assert!(!error.contains("secret"), "{error}");
        assert!(!s.db().exists());
        assert!(!s.managed().exists());
        assert_eq!(std::fs::read_to_string(s.source()).unwrap(), raw);
    }
    std::fs::write(s.source(), vec![b'x'; 65_537]).unwrap();
    assert!(cookie::import(&s.env(), &s.source(), true).unwrap_err().contains("64 KiB"));
    assert!(cookie::import(&s.env(), std::path::Path::new("relative.json"), true).is_err());
    assert!(cookie::import(&s.env(), &s.0, true).is_err(), "a directory is not a cookie file");
}

#[cfg(unix)]
#[test]
fn a_symlinked_source_is_refused() {
    let s = Sandbox::new();
    s.seed();
    let link = s.0.join("link.json");
    std::os::unix::fs::symlink(s.source(), &link).unwrap();
    assert!(cookie::import(&s.env(), &link, true).is_err());
    assert!(!s.managed().exists());
}
