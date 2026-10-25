//! Shared Python/Rust config database protocol. No legacy source is read here.
//!
//! The desktop owns the schema: it creates, migrates, and validates
//! `config.sqlite`. The Python CLI only validates `PRAGMA user_version` and
//! refuses to create or migrate tables, so a single implementation defines the
//! on-disk contract.
//!
//! Migrations are incremental: `MIGRATIONS[i]` upgrades a database from schema
//! version `i` to `i + 1` inside a single `IMMEDIATE` transaction.
//! `SCHEMA_VERSION` equals the migration list length, so appending a migration
//! automatically bumps the expected version.
use rusqlite::Connection;
use std::{collections::BTreeMap, path::PathBuf};
pub(crate) const DB_ENV: &str = "MULTI_SEARCH_CONFIG_DB";

/// Current schema version. Version 1 is the initial credentials/settings
/// layout; `MIGRATIONS[i]` upgrades user_version `i` to `i + 1`.
pub(crate) const SCHEMA_VERSION: i64 = MIGRATIONS.len() as i64;

/// Ordered schema upgrades. `MIGRATIONS[i]` migrates user_version `i` to
/// `i + 1`. Never reorder or edit a published migration: append a new one.
pub(crate) const MIGRATIONS: &[&str] = &[
    // v0 -> v1: create the initial tables.
    "CREATE TABLE credentials(provider TEXT PRIMARY KEY, encrypted_value BLOB NOT NULL, saved_at REAL NOT NULL); \
     CREATE TABLE settings(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);",
];
pub(crate) fn path(variables: &BTreeMap<String, String>) -> Option<PathBuf> {
    if let Some(value) = variables.get(DB_ENV).filter(|v| !v.is_empty()) {
        return Some(PathBuf::from(value));
    }
    variables
        .get("USERPROFILE")
        .filter(|v| !v.is_empty())
        .or_else(|| variables.get("HOME").filter(|v| !v.is_empty()))
        .map(|home| PathBuf::from(home).join(".multi-search/config.sqlite"))
}
fn version(c: &Connection) -> Result<i64, String> {
    c.pragma_query_value(None, "user_version", |r| r.get(0))
        .map_err(|_| "配置数据库无法读取".into())
}
fn validate(c: &Connection) -> Result<(), String> {
    for (table, expected) in [("credentials",vec![("provider","TEXT",0,1),("encrypted_value","BLOB",1,0),("saved_at","REAL",1,0)]),("settings",vec![("id","INTEGER",0,1),("data","TEXT",1,0)])] {
        let mut stmt=c.prepare(&format!("PRAGMA table_info({table})")).map_err(|_|"配置数据库结构无效".to_string())?;
        let fields=stmt.query_map([],|r|Ok((r.get::<_,String>(1)?,r.get::<_,String>(2)?,r.get::<_,i64>(3)?,r.get::<_,i64>(5)?))).map_err(|_|"配置数据库结构无效".to_string())?.collect::<Result<Vec<_>,_>>().map_err(|_|"配置数据库结构无效".to_string())?;
        if fields.len()!=expected.len()||fields.iter().zip(expected).any(|(a,b)|a.0!=b.0||!a.1.eq_ignore_ascii_case(b.1)||a.2!=b.2||a.3!=b.3){return Err("配置数据库结构无效".into());}
    }
    Ok(())
}
/// Upgrade an unversioned database through every migration in order.
/// Rejects a preexisting nonempty database with no schema version so existing
/// user data is never silently repurposed.
fn initialize(c: &mut Connection) -> Result<(), String> {
    let tx = c
        .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .map_err(|_| "配置数据库事务失败".to_string())?;
    // Another process may have initialized while this one waited.
    match version(&tx)? {
        0 => {
            let tables: i64 = tx
                .query_row(
                    "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
                    [],
                    |r| r.get(0),
                )
                .map_err(|_| "配置数据库结构无效".to_string())?;
            if tables != 0 {
                return Err("非空未版本化数据库不能用作配置数据库".into());
            }
            for (index, statement) in MIGRATIONS.iter().enumerate() {
                tx.execute_batch(statement)
                    .map_err(|_| "配置数据库结构无效".to_string())?;
                tx.pragma_update(None, "user_version", (index + 1) as i64)
                    .map_err(|_| "配置数据库结构无效".to_string())?;
            }
        }
        v if v == SCHEMA_VERSION => validate(&tx)?,
        _ => return Err("不支持的配置数据库版本".into()),
    }
    tx.commit()
        .map_err(|_| "配置数据库初始化失败".to_string())
}
/// Upgrade a versioned but outdated database through the remaining migrations.
fn migrate(c: &mut Connection, from: i64) -> Result<(), String> {
    let tx = c
        .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .map_err(|_| "配置数据库事务失败".to_string())?;
    // Another process may have migrated while this one waited.
    let current = version(&tx)?;
    if current == SCHEMA_VERSION {
        validate(&tx)?;
        return tx
            .commit()
            .map_err(|_| "配置数据库初始化失败".to_string());
    }
    if current < from || current >= SCHEMA_VERSION {
        return Err("不支持的配置数据库版本".into());
    }
    for index in (current as usize)..MIGRATIONS.len() {
        tx.execute_batch(MIGRATIONS[index])
            .map_err(|_| "配置数据库结构无效".to_string())?;
        tx.pragma_update(None, "user_version", (index + 1) as i64)
            .map_err(|_| "配置数据库结构无效".to_string())?;
    }
    validate(&tx)?;
    tx.commit()
        .map_err(|_| "配置数据库初始化失败".to_string())
}
pub(crate) fn open(path: &std::path::Path) -> Result<Connection, String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|_| "无法创建配置数据库目录".to_string())?;
    }
    let mut c = Connection::open(path).map_err(|_| "无法打开配置数据库".to_string())?;
    c.busy_timeout(std::time::Duration::from_secs(5))
        .map_err(|_| "配置数据库不可用".to_string())?;
    let current = version(&c)?;
    match current {
        0 => initialize(&mut c)?,
        v if v == SCHEMA_VERSION => validate(&c)?,
        // Older versioned databases are upgraded incrementally; newer ones are
        // rejected so a future desktop release's schema is never downgraded.
        v if v < SCHEMA_VERSION => migrate(&mut c, v)?,
        _ => return Err("不支持的配置数据库版本".into()),
    }
    Ok(c)
}
