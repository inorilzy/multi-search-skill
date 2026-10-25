use multi_search_desktop::{cookie, RuntimeEnvironment};
use std::{collections::BTreeMap, path::PathBuf};
struct Sandbox(PathBuf);
impl Sandbox {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!("ms-cookie-{}-{}", std::process::id(), NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)));
        std::fs::create_dir_all(&path).unwrap(); Self(path)
    }
    fn env(&self) -> RuntimeEnvironment { RuntimeEnvironment { app_path: vec![], user_path: vec![], cwd: self.0.clone(), variables: BTreeMap::from([("USERPROFILE".into(), self.0.to_string_lossy().into_owned())]) } }
    fn db(&self) -> PathBuf { self.0.join(".multi-search/config.sqlite") }
    fn source(&self) -> PathBuf { self.0.join("cookies.json") }
    fn seed(&self) -> Vec<u8> {
        let raw = b"\xef\xbb\xbf{\"auth_token\":\"synthetic-auth-0123456789\",\"ct0\":\"synthetic-csrf-0123456789\",\"guest_id\":\"guest\"}".to_vec();
        std::fs::write(self.source(), &raw).unwrap(); raw
    }
}
impl Drop for Sandbox { fn drop(&mut self) { let _ = std::fs::remove_dir_all(&self.0); } }
#[test]
fn confirmation_precedes_io_and_legacy_status_is_read_only() {
    let s = Sandbox::new();
    let status = cookie::status(&s.env()).unwrap();
    assert_eq!(status.mode, "file"); assert!(!status.present);
    assert!(!s.db().exists());
    assert!(cookie::import(&s.env(), &s.source(), false).unwrap_err().contains("Confirm"));
    assert!(cookie::delete(&s.env(), false).unwrap_err().contains("Confirm"));
    assert!(!s.db().exists());
}
#[cfg(windows)]
#[test]
fn import_encrypts_without_touching_source_and_delete_never_falls_back() {
    let s = Sandbox::new(); let original = s.seed();
    let status = cookie::import(&s.env(), &s.source(), true).unwrap();
    assert!(status.present && status.supported); assert_eq!(status.mode, "managed");
    assert_eq!(std::fs::read(s.source()).unwrap(), original);
    let db = std::fs::read(s.db()).unwrap();
    assert!(!String::from_utf8_lossy(&db).contains("synthetic-auth-0123456789"));
    assert!(!String::from_utf8_lossy(&db).contains("synthetic-csrf-0123456789"));
    let serialized = serde_json::to_string(&cookie::status(&s.env()).unwrap()).unwrap();
    assert!(!serialized.contains("synthetic"));
    let gone = cookie::delete(&s.env(), true).unwrap();
    assert!(!gone.present); assert_eq!(gone.mode, "managed");
    assert_eq!(cookie::status(&s.env()).unwrap().mode, "managed");
    assert_eq!(std::fs::read(s.source()).unwrap(), original);
}
#[cfg(windows)]
#[test]
fn invalid_and_oversized_maps_never_echo_or_persist() {
    let s = Sandbox::new();
    for raw in ["broken-secret", "{}", "[]", r#"{"auth_token":5,"ct0":"secret"}"#, r#"{"auth_token":"secret","ct0":"secret","bad-name":"secret"}"#, r#"{"auth_token":"secret\n","ct0":"secret"}"#] {
        std::fs::write(s.source(), raw).unwrap();
        let error = cookie::import(&s.env(), &s.source(), true).unwrap_err();
        assert!(!error.contains("secret")); assert!(!s.db().exists());
        assert_eq!(std::fs::read_to_string(s.source()).unwrap(), raw);
    }
    std::fs::write(s.source(), vec![b'x'; 65_537]).unwrap();
    assert!(cookie::import(&s.env(), &s.source(), true).unwrap_err().contains("64 KiB"));
}
#[cfg(windows)]
#[test]
fn failed_import_rolls_back_row_and_mode_and_preserves_other_fields() {
    let s = Sandbox::new(); s.seed();
    cookie::import(&s.env(), &s.source(), true).unwrap();
    let c = rusqlite::Connection::open(s.db()).unwrap();
    c.execute("UPDATE settings SET data=?1", [r#"{"twitter_cookies_mode":"file","future":42,"twitter_cookies_path":"old-file"}"#]).unwrap();
    let before: Vec<u8> = c.query_row("SELECT encrypted_value FROM credentials", [], |r| r.get(0)).unwrap();
    c.execute_batch("CREATE TRIGGER block_settings BEFORE UPDATE ON settings BEGIN SELECT RAISE(ABORT,'synthetic'); END;").unwrap();
    assert!(cookie::import(&s.env(), &s.source(), true).is_err());
    let after: Vec<u8> = c.query_row("SELECT encrypted_value FROM credentials", [], |r| r.get(0)).unwrap();
    assert_eq!(before, after); assert_eq!(cookie::status(&s.env()).unwrap().mode, "file");
    c.execute_batch("DROP TRIGGER block_settings").unwrap();
    cookie::import(&s.env(), &s.source(), true).unwrap();
    let raw: String = c.query_row("SELECT data FROM settings", [], |r| r.get(0)).unwrap();
    let obj: serde_json::Value = serde_json::from_str(&raw).unwrap();
    assert_eq!(obj["future"],42); assert_eq!(obj["twitter_cookies_path"],"old-file");
    c.execute("UPDATE credentials SET encrypted_value=x'00'", []).unwrap();
    assert!(cookie::status(&s.env()).unwrap_err().contains("unreadable"));
    // Explicit delete can recover corrupted ciphertext, without reading the old file.
    assert_eq!(cookie::delete(&s.env(), true).unwrap().mode,"managed");
}
#[cfg(not(windows))]
#[test]
fn nonwindows_never_falls_back_to_plaintext() {
    let s = Sandbox::new(); s.seed();
    assert!(!cookie::status(&s.env()).unwrap().supported);
    assert!(cookie::import(&s.env(), &s.source(), true).unwrap_err().contains("Windows DPAPI"));
    assert!(cookie::delete(&s.env(), true).is_err()); assert!(!s.db().exists());
}

#[cfg(windows)]
#[test]
fn rust_python_cookie_ciphertext_protocol_roundtrip() {
    let s = Sandbox::new(); let raw = s.seed();
    cookie::import(&s.env(), &s.source(), true).unwrap();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..").canonicalize().unwrap();
    let script = r#"
import sys
from multi_search_mcp.src.support.credential_store import CredentialStore, SQLiteCredentialBackend
store=CredentialStore(SQLiteCredentialBackend(sys.argv[1]))
assert store.get('twitter_cookies')['auth_token']=='synthetic-auth-0123456789'
store.set('twitter_cookies',{'auth_token':'synthetic-python-auth','ct0':'synthetic-python-csrf'},saved_at=2.0)
"#;
    let out = std::process::Command::new("python").args(["-B","-c",script]).arg(s.db())
        .env("PYTHONPATH",&root).env("HOME",&s.0).env("USERPROFILE",&s.0).current_dir(&s.0).output().unwrap();
    assert!(out.status.success(),"{}",String::from_utf8_lossy(&out.stderr));
    assert!(cookie::status(&s.env()).unwrap().present);
    assert_eq!(std::fs::read(s.source()).unwrap(),raw);
    assert!(!String::from_utf8_lossy(&std::fs::read(s.db()).unwrap()).contains("synthetic-python-auth"));
}
