//! state.sqlite 站点记忆只读/写入接口；全部使用临时目录和合成统计。
use multi_search_desktop::{scrape_memory, RuntimeEnvironment};
use std::{collections::BTreeMap, path::PathBuf};

struct Sandbox(PathBuf);
impl Sandbox {
    fn new(tag: &str) -> Self {
        let p = std::env::temp_dir().join(format!(
            "ms-scrape-memory-{tag}-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&p);
        std::fs::create_dir_all(&p).unwrap();
        Self(p)
    }
    fn db(&self) -> PathBuf {
        self.0.join("state.sqlite")
    }
    fn env(&self) -> RuntimeEnvironment {
        RuntimeEnvironment {
            app_path: vec![],
            user_path: vec![],
            variables: BTreeMap::from([
                ("USERPROFILE".into(), self.0.to_string_lossy().into_owned()),
                ("MULTI_SEARCH_STATE_DB".into(), self.db().to_string_lossy().into_owned()),
            ]),
            cwd: self.0.clone(),
        }
    }
    fn create(&self) {
        let c = rusqlite::Connection::open(self.db()).unwrap();
        c.execute_batch(
            "CREATE TABLE site_scraper_stats (
               site TEXT NOT NULL, scraper TEXT NOT NULL,
               success_count INTEGER NOT NULL DEFAULT 0, failure_count INTEGER NOT NULL DEFAULT 0,
               blocked_count INTEGER NOT NULL DEFAULT 0, timeout_count INTEGER NOT NULL DEFAULT 0,
               avg_content_length INTEGER, last_success_at TEXT, last_failure_at TEXT,
               last_error_type TEXT, last_error_message TEXT, cooldown_until TEXT,
               sample_url TEXT, manually_pinned INTEGER NOT NULL DEFAULT 0,
               manual_priority INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
               PRIMARY KEY (site, scraper));
             CREATE TABLE scrape_attempts (
               id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, site TEXT NOT NULL,
               scraper TEXT NOT NULL, success INTEGER NOT NULL, content_length INTEGER,
               error_type TEXT, error_message TEXT, elapsed_ms INTEGER, created_at TEXT NOT NULL);",
        )
        .unwrap();
    }
    fn insert(&self, site: &str, scraper: &str, successes: i64, failures: i64, cooldown: Option<&str>) {
        let c = rusqlite::Connection::open(self.db()).unwrap();
        c.execute(
            "INSERT INTO site_scraper_stats
             (site, scraper, success_count, failure_count, cooldown_until, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, '2026-10-22T10:00:00+08:00', '2026-10-22T10:00:00+08:00')",
            rusqlite::params![site, scraper, successes, failures, cooldown],
        )
        .unwrap();
    }
    fn count(&self, sql: &str) -> i64 {
        rusqlite::Connection::open(self.db())
            .unwrap()
            .query_row(sql, [], |row| row.get(0))
            .unwrap()
    }
}
impl Drop for Sandbox {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[test]
fn missing_state_database_reports_unavailable_and_writes_nothing() {
    let s = Sandbox::new("missing");
    let view = scrape_memory::view(&s.env(), None);
    assert!(!view.available);
    assert!(view.rows.is_empty());
    assert_eq!(view.reason, "尚无抓取状态数据");
    assert!(!s.db().exists());

    let pinned = scrape_memory::pin(&s.env(), "example.com", "jina").unwrap();
    assert!(!pinned.available);
    assert!(!s.db().exists(), "pin must not create state.sqlite");

    let reset = scrape_memory::reset(&s.env(), None).unwrap();
    assert!(!reset.available);
    assert!(!s.db().exists());
}

#[test]
fn missing_table_reports_unavailable_with_reason() {
    let s = Sandbox::new("no-table");
    rusqlite::Connection::open(s.db())
        .unwrap()
        .execute_batch("CREATE TABLE unrelated(value TEXT);")
        .unwrap();
    let view = scrape_memory::view(&s.env(), None);
    assert!(!view.available);
    assert!(view.reason.contains("尚无抓取状态数据"));
}

#[test]
fn reads_rows_sorted_by_site_pin_success_and_scraper() {
    let s = Sandbox::new("read");
    s.create();
    s.insert("a.example", "jina", 3, 1, None);
    s.insert("a.example", "exa", 9, 0, None);
    s.insert("a.example", "tavily", 0, 2, None);
    s.insert("b.example", "jina", 1, 0, None);
    let view = scrape_memory::view(&s.env(), None);
    assert!(view.available);
    assert!(view.reason.is_empty());
    assert_eq!(
        view.rows
            .iter()
            .map(|row| (row.site.as_str(), row.scraper.as_str()))
            .collect::<Vec<_>>(),
        [
            ("a.example", "exa"),
            ("a.example", "jina"),
            ("a.example", "tavily"),
            ("b.example", "jina"),
        ]
    );
    let filtered = scrape_memory::view(&s.env(), Some("b.example"));
    assert_eq!(filtered.rows.len(), 1);
    assert_eq!(filtered.rows[0].scraper, "jina");
    assert_eq!(filtered.rows[0].success_count, 1);
}

#[test]
fn pin_inserts_row_and_puts_backend_first() {
    let s = Sandbox::new("pin");
    s.create();
    s.insert("example.com", "exa", 10, 0, None);
    s.insert("example.com", "tavily", 5, 0, None);
    let view = scrape_memory::pin(&s.env(), "example.com", "firecrawl").unwrap();
    assert!(view.available);
    let first = &view.rows[0];
    assert_eq!(first.scraper, "firecrawl");
    assert!(first.manually_pinned);
    assert_eq!(first.manual_priority, Some(-1));

    let again = scrape_memory::pin(&s.env(), "example.com", "tavily").unwrap();
    let row = again
        .rows
        .iter()
        .find(|row| row.scraper == "tavily")
        .unwrap();
    assert!(row.manually_pinned);
    assert!(row.manual_priority.unwrap() < 0);
    assert_eq!(again.rows[0].scraper, "tavily");
    // 其他站点的行不受影响。
    assert!(scrape_memory::view(&s.env(), Some("other.com")).rows.is_empty());
}

#[test]
fn pin_rejects_unknown_scraper() {
    let s = Sandbox::new("pin-invalid");
    s.create();
    let error = scrape_memory::pin(&s.env(), "example.com", "bing").unwrap_err();
    assert!(error.contains("不支持的抓取后端：bing"));
    assert_eq!(s.count("SELECT count(*) FROM site_scraper_stats"), 0);
    let blank = scrape_memory::pin(&s.env(), "example.com", "  ").unwrap_err();
    assert!(blank.contains("不支持的抓取后端"));
}

#[test]
fn pin_is_atomic_and_rolls_back_the_insert_when_update_fails() {
    let s = Sandbox::new("pin-atomic");
    s.create();
    s.insert("example.com", "jina", 1, 0, None);
    let c = rusqlite::Connection::open(s.db()).unwrap();
    c.execute_batch(
        "CREATE TRIGGER deny_pin BEFORE UPDATE ON site_scraper_stats \
         BEGIN SELECT RAISE(ABORT, 'denied'); END;",
    )
    .unwrap();
    drop(c);

    let error = scrape_memory::pin(&s.env(), "example.com", "exa").unwrap_err();
    assert!(error.contains("无法写入"));
    // SELECT MIN 之后的新行 INSERT 必须随 UPDATE 一起回滚。
    assert_eq!(
        s.count("SELECT count(*) FROM site_scraper_stats WHERE scraper='exa'"),
        0
    );
    assert_eq!(
        s.count("SELECT count(*) FROM site_scraper_stats WHERE manually_pinned != 0"),
        0
    );
}

#[test]
fn concurrent_pins_get_distinct_priorities_without_lost_writes() {
    let s = Sandbox::new("pin-concurrent");
    s.create();
    let env = s.env();
    let mut handles = Vec::new();
    for scraper in ["jina", "exa", "tavily", "firecrawl"] {
        let env = env.clone();
        handles.push(std::thread::spawn(move || {
            scrape_memory::pin(&env, "example.com", scraper).map(|_| scraper)
        }));
    }
    for handle in handles {
        handle.join().unwrap().expect("concurrent pin should succeed");
    }
    let view = scrape_memory::view(&env, Some("example.com"));
    assert_eq!(view.rows.len(), 4);
    let mut priorities: Vec<i64> = view
        .rows
        .iter()
        .map(|row| row.manual_priority.expect("pinned rows carry a priority"))
        .collect();
    priorities.sort_unstable();
    priorities.dedup();
    assert_eq!(priorities.len(), 4, "priorities must be unique");
    assert!(view.rows.iter().all(|row| row.manually_pinned));
    // 每次 pin 都比已有最小值再小 1：-1、-2、-3、-4。
    assert_eq!(priorities, [-4, -3, -2, -1]);
}

#[test]
fn reset_clears_one_site_or_all_rows() {
    let s = Sandbox::new("reset");
    s.create();
    s.insert("a.example", "jina", 1, 0, None);
    s.insert("b.example", "exa", 1, 0, None);
    let c = rusqlite::Connection::open(s.db()).unwrap();
    for site in ["a.example", "b.example"] {
        c.execute(
            "INSERT INTO scrape_attempts(url, site, scraper, success, created_at) \
             VALUES ('https://x', ?1, 'jina', 1, '2026-10-22T10:00:00+08:00')",
            [site],
        )
        .unwrap();
    }
    drop(c);

    let after_site = scrape_memory::reset(&s.env(), Some("a.example")).unwrap();
    assert_eq!(after_site.rows.len(), 1);
    assert_eq!(after_site.rows[0].site, "b.example");
    assert_eq!(
        s.count("SELECT count(*) FROM scrape_attempts WHERE site='a.example'"),
        0
    );
    assert_eq!(s.count("SELECT count(*) FROM scrape_attempts"), 1);

    let after_all = scrape_memory::reset(&s.env(), None).unwrap();
    assert!(after_all.rows.is_empty());
    assert_eq!(s.count("SELECT count(*) FROM site_scraper_stats"), 0);
    assert_eq!(s.count("SELECT count(*) FROM scrape_attempts"), 0);
}

#[test]
fn cooldown_is_derived_from_iso_time_and_bad_time_is_not_cooldown() {
    let s = Sandbox::new("cooldown");
    s.create();
    s.insert("past.example", "jina", 0, 1, Some("2000-01-01T00:00:00+08:00"));
    s.insert("future.example", "jina", 0, 1, Some("2999-01-01T00:00:00Z"));
    s.insert("bad.example", "jina", 0, 1, Some("not-a-time"));
    s.insert("zone.example", "jina", 0, 1, Some("2999-01-01T00:00:00.123456+08:00"));
    let rows = scrape_memory::view(&s.env(), None).rows;
    let find = |site: &str| rows.iter().find(|row| row.site == site).unwrap();
    assert!(!find("past.example").in_cooldown);
    assert!(find("future.example").in_cooldown);
    assert!(!find("bad.example").in_cooldown);
    assert!(find("zone.example").in_cooldown);
}

#[test]
fn state_path_prefers_env_then_userprofile_then_home() {
    let s = Sandbox::new("path");
    let custom = s.0.join("custom/state.sqlite");
    let env = RuntimeEnvironment {
        app_path: vec![],
        user_path: vec![],
        variables: BTreeMap::from([(
            "MULTI_SEARCH_STATE_DB".into(),
            custom.to_string_lossy().into_owned(),
        )]),
        cwd: s.0.clone(),
    };
    assert_eq!(scrape_memory::state_path(&env).unwrap(), custom);
    let home = RuntimeEnvironment {
        app_path: vec![],
        user_path: vec![],
        variables: BTreeMap::from([
            ("USERPROFILE".into(), String::new()),
            ("HOME".into(), s.0.to_string_lossy().into_owned()),
        ]),
        cwd: s.0.clone(),
    };
    assert_eq!(
        scrape_memory::state_path(&home).unwrap(),
        s.0.join(".multi-search/state.sqlite")
    );
}
