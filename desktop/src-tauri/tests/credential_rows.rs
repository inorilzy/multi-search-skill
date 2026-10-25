//! Per-row credential mutations on a real current-user DPAPI store, against
//! unique disposable SQLite files and synthetic credentials only.
#![cfg(windows)]
use multi_search_desktop::credential_fixture as fixture;
use std::path::PathBuf;

struct Sandbox(PathBuf);
impl Sandbox {
    fn new(tag: &str) -> Self {
        // `create_dir` fails if the path exists, so a stale directory is
        // never deleted — the tag + pid + counter + timestamp makes collisions
        // a bug to surface, not something to clean up silently.
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let p = std::env::temp_dir().join(format!(
            "ms-cred-rows-{tag}-{}-{}-{nanos}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        std::fs::create_dir(&p).unwrap();
        Self(p)
    }
    fn db(&self) -> PathBuf {
        self.0.join("config.sqlite")
    }
}
impl Drop for Sandbox {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn keys(list: &[&str]) -> Vec<String> {
    list.iter().map(|s| s.to_string()).collect()
}
fn read(path: &std::path::Path, provider: &str) -> Option<serde_json::Value> {
    fixture::native_read(path, provider).unwrap()
}

#[test]
fn append_to_existing_rows_preserves_every_entry_verbatim() {
    let s = Sandbox::new("append-existing");
    let original = serde_json::json!(["synthetic-row-0001", {"key":"synthetic-row-jina","exhausted":true,"note":{"team":"a"}}]);
    fixture::native_write(&s.db(), "jina", &original, 1.0).unwrap();
    fixture::native_append(&s.db(), "jina", &keys(&["synthetic-row-0002"]), 2.0).unwrap();
    let stored = read(&s.db(), "jina").unwrap();
    let arr = stored.as_array().unwrap();
    // Original entries are byte-identical; the appended key is a plain string row.
    assert_eq!(&arr[..2], original.as_array().unwrap().as_slice());
    assert_eq!(arr[2], serde_json::json!("synthetic-row-0002"));
    assert_eq!(arr.len(), 3);
}

#[test]
fn append_creates_store_when_absent_and_single_key_stays_scalar() {
    let s = Sandbox::new("append-absent");
    fixture::native_append(&s.db(), "tavily", &keys(&["synthetic-row-only"]), 1.0).unwrap();
    assert_eq!(read(&s.db(), "tavily"), Some(serde_json::json!("synthetic-row-only")));
}

#[test]
fn append_rejects_invalid_and_over_limit_without_writing() {
    let s = Sandbox::new("append-invalid");
    fixture::native_write(&s.db(), "tavily", &serde_json::json!("synthetic-row-orig"), 1.0).unwrap();
    for bad in [keys(&[""]), keys(&["   "]), keys(&["line\u{7}break"]), keys(&[&"x".repeat(1025)])] {
        assert!(fixture::native_append(&s.db(), "tavily", &bad, 2.0).is_err());
    }
    assert!(fixture::native_append(&s.db(), "tavily", &[], 2.0).is_err());
    let many: Vec<String> = (0..257).map(|i| format!("synthetic-bulk-{i}")).collect();
    assert!(fixture::native_append(&s.db(), "tavily", &many, 2.0).is_err());
    assert_eq!(read(&s.db(), "tavily"), Some(serde_json::json!("synthetic-row-orig")));
}

#[test]
fn remove_exact_duplicate_jina_row_drops_its_metadata() {
    let s = Sandbox::new("dup-jina");
    // Two rows share the visible key; removing index 0 must delete that exact
    // metadata row, not reconstruct it through merge_jina_metadata.
    let original = serde_json::json!([
        {"key":"synthetic-dup","exhausted":true,"note":{"owner":"first"}},
        "synthetic-dup",
        {"key":"synthetic-dup","exhausted":false,"note":["second"]}
    ]);
    fixture::native_write(&s.db(), "jina", &original, 1.0).unwrap();
    let expected = "synthetic-dup\nsynthetic-dup\nsynthetic-dup";
    fixture::native_remove_row(&s.db(), "jina", 0, expected, 2.0).unwrap();
    let stored = read(&s.db(), "jina").unwrap();
    assert_eq!(
        stored,
        serde_json::json!(["synthetic-dup", {"key":"synthetic-dup","exhausted":false,"note":["second"]}])
    );
    // Removing index 1 now hits the second plain-string occurrence.
    fixture::native_remove_row(&s.db(), "jina", 1, "synthetic-dup\nsynthetic-dup", 3.0).unwrap();
    assert_eq!(read(&s.db(), "jina"), Some(serde_json::json!("synthetic-dup")));
}

#[test]
fn remove_rejects_stale_snapshot_and_out_of_range_without_writing() {
    let s = Sandbox::new("stale");
    fixture::native_write(&s.db(), "tavily", &serde_json::json!(["k1","k2"]), 1.0).unwrap();
    assert!(fixture::native_remove_row(&s.db(), "tavily", 0, "k1\nCHANGED", 2.0).is_err());
    assert!(fixture::native_remove_row(&s.db(), "tavily", 5, "k1\nk2", 2.0).is_err());
    assert!(fixture::native_remove_row(&s.db(), "tavily", 0, "", 2.0).is_err());
    // A snapshot with the wrong row count also counts as stale.
    assert!(fixture::native_remove_row(&s.db(), "tavily", 0, "k1", 2.0).is_err());
    assert_eq!(read(&s.db(), "tavily"), Some(serde_json::json!(["k1","k2"])));
}

#[test]
fn remove_last_row_deletes_credentials_row() {
    let s = Sandbox::new("last-delete");
    fixture::native_write(&s.db(), "tavily", &serde_json::json!("synthetic-last"), 1.0).unwrap();
    fixture::native_remove_row(&s.db(), "tavily", 0, "synthetic-last", 2.0).unwrap();
    assert_eq!(read(&s.db(), "tavily"), None);
    let conn = rusqlite::Connection::open(s.db()).unwrap();
    let count: i64 = conn
        .query_row("SELECT count(*) FROM credentials WHERE provider='tavily'", [], |r| r.get(0))
        .unwrap();
    assert_eq!(count, 0);
}

#[test]
fn unreadable_store_rejects_row_mutation_and_is_untouched() {
    let s = Sandbox::new("unreadable");
    fixture::native_write(&s.db(), "tavily", &serde_json::json!("synthetic-key"), 1.0).unwrap();
    let conn = rusqlite::Connection::open(s.db()).unwrap();
    conn.execute("UPDATE credentials SET encrypted_value=?1 WHERE provider='tavily'", [b"not dpapi".as_slice()]).unwrap();
    drop(conn);
    assert!(fixture::native_append(&s.db(), "tavily", &keys(&["k"]), 2.0).is_err());
    assert!(fixture::native_remove_row(&s.db(), "tavily", 0, "synthetic-key", 2.0).is_err());
    // The corrupted blob is still the only content of the row (no rewrite).
    let conn = rusqlite::Connection::open(s.db()).unwrap();
    let blob: Vec<u8> = conn
        .query_row("SELECT encrypted_value FROM credentials WHERE provider='tavily'", [], |r| r.get(0))
        .unwrap();
    assert_eq!(blob, b"not dpapi".as_slice());
}

#[test]
fn hidden_entry_shape_rejects_row_ops_without_losing_data() {
    let s = Sandbox::new("hidden-shape");
    // A shape the editor cannot render must fail row ops rather than silently
    // drop the hidden entry.
    let weird = serde_json::json!([["nested"], "k1"]);
    let path = s.db();
    fixture::native_write_raw(&path, "tavily", &weird, 1.0).unwrap();
    assert!(fixture::native_append(&path, "tavily", &keys(&["k2"]), 2.0).is_err());
    assert!(fixture::native_remove_row(&path, "tavily", 0, "k1", 2.0).is_err());
    // The row is still stored untouched; the shape is unreadable to the
    // editor, which is exactly why row ops must refuse it.
    let conn = rusqlite::Connection::open(&path).unwrap();
    let blob: Vec<u8> = conn
        .query_row("SELECT encrypted_value FROM credentials WHERE provider='tavily'", [], |r| r.get(0))
        .unwrap();
    assert!(!blob.is_empty());
}

#[test]
fn failed_write_rolls_back_and_keeps_original_blob() {
    let s = Sandbox::new("row-rollback");
    let original = serde_json::json!(["k1", "k2"]);
    fixture::native_write(&s.db(), "tavily", &original, 1.0).unwrap();
    let conn = rusqlite::Connection::open(s.db()).unwrap();
    conn.execute_batch("CREATE TRIGGER deny_row BEFORE UPDATE ON credentials BEGIN SELECT RAISE(ABORT,'denied'); END;").unwrap();
    drop(conn);
    assert!(fixture::native_append(&s.db(), "tavily", &keys(&["k3"]), 2.0).is_err());
    assert!(fixture::native_remove_row(&s.db(), "tavily", 0, "k1\nk2", 2.0).is_err());
    assert_eq!(read(&s.db(), "tavily"), Some(original));
}

#[test]
fn concurrent_appends_each_keep_their_key() {
    let s = Sandbox::new("concurrent");
    fixture::native_write(&s.db(), "tavily", &serde_json::json!("base"), 1.0).unwrap();
    let path = s.db();
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let mut handles = Vec::new();
    for tag in ["a", "b"] {
        let path = path.clone();
        let barrier = barrier.clone();
        handles.push(std::thread::spawn(move || {
            barrier.wait();
            fixture::native_append(&path, "tavily", &keys(&[&format!("synthetic-conc-{tag}")]), 2.0)
        }));
    }
    for h in handles {
        h.join().unwrap().unwrap();
    }
    let stored = read(&path, "tavily").unwrap();
    let arr = stored.as_array().unwrap();
    assert!(arr.contains(&serde_json::json!("synthetic-conc-a")));
    assert!(arr.contains(&serde_json::json!("synthetic-conc-b")));
    assert_eq!(arr.len(), 3);
}
