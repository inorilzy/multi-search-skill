//! 站点抓取记忆（state.sqlite）的只读视图与两种写操作。
//!
//! state.sqlite 由 Python CLI 创建和维护，桌面只读取统计、写入 pin/reset。
//! 表不存在或文件缺失都按“尚无抓取状态数据”返回，而不是报错。
use crate::settings::SCRAPE_BACKENDS;
use crate::RuntimeEnvironment;
use rusqlite::{Connection, OpenFlags};
use serde::Serialize;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

/// 仅用于桌面测试隔离的 state.sqlite 覆盖入口；Python 侧不读取该变量。
const STATE_DB_ENV: &str = "MULTI_SEARCH_STATE_DB";

#[derive(Clone, Debug, Serialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct ScrapeMemoryRow {
    pub site: String,
    pub scraper: String,
    pub success_count: i64,
    pub failure_count: i64,
    pub blocked_count: i64,
    pub timeout_count: i64,
    pub avg_content_length: Option<i64>,
    pub last_success_at: Option<String>,
    pub last_failure_at: Option<String>,
    pub last_error_type: Option<String>,
    pub last_error_message: Option<String>,
    pub cooldown_until: Option<String>,
    pub sample_url: Option<String>,
    pub manually_pinned: bool,
    pub manual_priority: Option<i64>,
    /// 由 cooldown_until 与当前时间比较得出；解析失败时为 false。
    pub in_cooldown: bool,
}

#[derive(Clone, Debug, Serialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct ScrapeMemoryView {
    /// state.sqlite 是否可读（存在且含记忆表）。
    pub available: bool,
    pub path: Option<String>,
    /// 不可读时的中文说明，可读时为空串。
    pub reason: String,
    pub rows: Vec<ScrapeMemoryRow>,
}

fn home_path(environment: &RuntimeEnvironment) -> Option<PathBuf> {
    environment
        .variables
        .get("USERPROFILE")
        .filter(|value| !value.is_empty())
        .or_else(|| {
            environment
                .variables
                .get("HOME")
                .filter(|value| !value.is_empty())
        })
        .map(|home| PathBuf::from(home).join(".multi-search/state.sqlite"))
}

/// 测试可用 `MULTI_SEARCH_STATE_DB` 覆盖；其余情况与 Python 的默认位置一致。
pub fn state_path(environment: &RuntimeEnvironment) -> Option<PathBuf> {
    if let Some(value) = environment
        .variables
        .get(STATE_DB_ENV)
        .filter(|value| !value.is_empty())
    {
        return Some(PathBuf::from(value));
    }
    home_path(environment)
}

fn validate_site(site: &str) -> Result<(), String> {
    // Exact categories emitted by Python site_memory.site_key; never arbitrary paths.
    if matches!(site, "github.com/repo" | "github.com/issues" | "github.com/pull" | "github.com/discussions") { return Ok(()); }
    if site.to_ascii_lowercase() != site || site.len() > 253 || site.is_empty() || site.split('.').any(|label| label.is_empty() || label.len() > 63 || label.starts_with('-') || label.ends_with('-') || !label.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-')) {
        return Err("站点必须为有效主机名，不含 URL、路径或端口".into());
    }
    Ok(())
}

fn now_epoch() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs() as i64)
        .unwrap_or(0)
}

fn table_present(connection: &Connection) -> Result<bool, String> {
    connection
        .query_row(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='site_scraper_stats'",
            [],
            |row| row.get::<_, i64>(0),
        )
        .map(|count| count > 0)
        .map_err(|_| "抓取状态数据库无法读取".to_string())
}

fn unavailable(path: Option<PathBuf>, reason: &str) -> ScrapeMemoryView {
    ScrapeMemoryView {
        available: false,
        path: path.map(|path| path.to_string_lossy().into_owned()),
        reason: reason.into(),
        rows: Vec::new(),
    }
}

fn missing(path: Option<PathBuf>) -> ScrapeMemoryView {
    unavailable(path, "尚无抓取状态数据")
}

fn read_only(path: &Path) -> Result<Connection, String> {
    let connection = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .map_err(|_| "抓取状态数据库无法读取".to_string())?;
    connection
        .busy_timeout(std::time::Duration::from_secs(5))
        .map_err(|_| "抓取状态数据库不可用".to_string())?;
    let version: i64 = connection.pragma_query_value(None, "user_version", |r| r.get(0))
        .map_err(|_| "抓取状态数据库无法读取".to_string())?;
    if !matches!(version, 1 | 2) { return Err("不支持的抓取状态数据库版本".into()); }
    Ok(connection)
}

fn read_write(path: &Path) -> Result<Connection, String> {
    // 不创建文件：调用方已确认 state.sqlite 存在。
    let connection = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|_| "抓取状态数据库无法写入".to_string())?;
    connection
        .busy_timeout(std::time::Duration::from_secs(5))
        .map_err(|_| "抓取状态数据库不可用".to_string())?;
    let version: i64 = connection.pragma_query_value(None, "user_version", |r| r.get(0))
        .map_err(|_| "抓取状态数据库无法读取".to_string())?;
    if !matches!(version, 1 | 2) { return Err("不支持的抓取状态数据库版本".into()); }
    Ok(connection)
}

// chrono 不在依赖列表里；冷却判断只需要解析这一个格式，标准库即可完成。
// 支持的输入：YYYY-MM-DDTHH:MM:SS[.ffffff][+HH:MM|-HH:MM|Z]。
fn parse_epoch(text: &str) -> Option<i64> {
    let text = text.trim();
    let bytes = text.as_bytes();
    if bytes.len() < 19 {
        return None;
    }
    let number = |range: std::ops::Range<usize>| -> Option<i64> {
        let slice = text.get(range)?;
        if slice.bytes().all(|byte| byte.is_ascii_digit()) {
            slice.parse().ok()
        } else {
            None
        }
    };
    let year = number(0..4)?;
    if bytes[4] != b'-' || bytes[7] != b'-' {
        return None;
    }
    let month = number(5..7)?;
    let day = number(8..10)?;
    if !matches!(bytes[10], b'T' | b't' | b' ') || bytes[13] != b':' || bytes[16] != b':' {
        return None;
    }
    let hour = number(11..13)?;
    let minute = number(14..16)?;
    let second = number(17..19)?;
    if !(1..=12).contains(&month)
        || !(1..=31).contains(&day)
        || hour > 23
        || minute > 59
        || second > 60
    {
        return None;
    }
    let mut rest = &text[19..];
    if let Some(stripped) = rest.strip_prefix('.') {
        let digits = stripped
            .bytes()
            .take_while(|byte| byte.is_ascii_digit())
            .count();
        if digits == 0 {
            return None;
        }
        rest = &stripped[digits..];
    }
    let offset_seconds = if rest.is_empty() || rest == "Z" || rest == "z" {
        0
    } else {
        let sign = match rest.as_bytes().first() {
            Some(b'+') => 1,
            Some(b'-') => -1,
            _ => return None,
        };
        let offset = &rest[1..];
        if offset.len() != 5 || offset.as_bytes()[2] != b':' {
            return None;
        }
        let offset_hour: i64 = offset[0..2].parse().ok()?;
        let offset_minute: i64 = offset[3..5].parse().ok()?;
        if offset_hour > 23 || offset_minute > 59 {
            return None;
        }
        sign * (offset_hour * 3600 + offset_minute * 60)
    };
    let days = days_from_civil(year, month, day);
    Some(days * 86_400 + hour * 3600 + minute * 60 + second - offset_seconds)
}

/// Howard Hinnant 的 civil_from_days 反函数：1970-01-01 起的天数。
fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = if year >= 0 { year } else { year - 399 } / 400;
    let yoe = year - era * 400;
    let adjusted_month = if month > 2 { month - 3 } else { month + 9 };
    let doy = (153 * adjusted_month + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

/// epoch 秒 → `YYYY-MM-DDTHH:MM:SSZ`，用于 pin 时写 created_at/updated_at。
fn format_utc(epoch: i64) -> String {
    let days = epoch.div_euclid(86_400);
    let seconds = epoch.rem_euclid(86_400);
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let mut year = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    if month <= 2 {
        year += 1;
    }
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        seconds / 3600,
        (seconds % 3600) / 60,
        seconds % 60
    )
}

fn row_from(row: &rusqlite::Row<'_>, now: i64) -> rusqlite::Result<ScrapeMemoryRow> {
    let cooldown_until: Option<String> = row.get("cooldown_until")?;
    let in_cooldown = cooldown_until
        .as_deref()
        .and_then(parse_epoch)
        .is_some_and(|until| until > now);
    Ok(ScrapeMemoryRow {
        site: row.get("site")?,
        scraper: row.get("scraper")?,
        success_count: row.get("success_count")?,
        failure_count: row.get("failure_count")?,
        blocked_count: row.get("blocked_count")?,
        timeout_count: row.get("timeout_count")?,
        avg_content_length: row.get("avg_content_length")?,
        last_success_at: row.get("last_success_at")?,
        last_failure_at: row.get("last_failure_at")?,
        last_error_type: row.get("last_error_type")?,
        last_error_message: row.get("last_error_message")?,
        cooldown_until,
        sample_url: row.get("sample_url")?,
        manually_pinned: row.get::<_, i64>("manually_pinned")? != 0,
        manual_priority: row.get("manual_priority")?,
        in_cooldown,
    })
}

fn read_rows(
    connection: &Connection,
    site: Option<&str>,
    now: i64,
) -> Result<Vec<ScrapeMemoryRow>, String> {
    let sql = if site.is_some() {
        "SELECT site, scraper, success_count, failure_count, blocked_count, timeout_count, avg_content_length, last_success_at, last_failure_at, last_error_type, last_error_message, cooldown_until, sample_url, manually_pinned, manual_priority FROM site_scraper_stats WHERE site = ?1 \
         ORDER BY site, manually_pinned DESC, success_count DESC, scraper"
    } else {
        "SELECT site, scraper, success_count, failure_count, blocked_count, timeout_count, avg_content_length, last_success_at, last_failure_at, last_error_type, last_error_message, cooldown_until, sample_url, manually_pinned, manual_priority FROM site_scraper_stats \
         ORDER BY site, manually_pinned DESC, success_count DESC, scraper"
    };
    let mut statement = connection
        .prepare(sql)
        .map_err(|_| "抓取状态数据库无法读取".to_string())?;
    let rows = match site {
        Some(site) => statement
            .query_map([site], |row| row_from(row, now))
            .map_err(|_| "抓取状态数据库无法读取".to_string())?
            .collect::<Result<Vec<_>, _>>(),
        None => statement
            .query_map([], |row| row_from(row, now))
            .map_err(|_| "抓取状态数据库无法读取".to_string())?
            .collect::<Result<Vec<_>, _>>(),
    };
    rows.map_err(|_| "抓取状态数据库无法读取".to_string())
}

/// 读取站点记忆；`site` 为 Some 时精确匹配。
pub fn view(environment: &RuntimeEnvironment, site: Option<&str>) -> ScrapeMemoryView {
    if let Some(site) = site {
        if let Err(reason) = validate_site(site) { return unavailable(None, &reason); }
    }
    let path = match state_path(environment) {
        Some(path) => path,
        None => return missing(None),
    };
    if !path.is_file() {
        return missing(Some(path));
    }
    let connection = match read_only(&path) {
        Ok(connection) => connection,
        Err(reason) => return unavailable(Some(path), &reason),
    };
    match table_present(&connection) {
        Ok(true) => {}
        Ok(false) => {
            return unavailable(
                Some(path),
                "尚无抓取状态数据：state.sqlite 里还没有抓取记忆表",
            )
        }
        Err(reason) => return unavailable(Some(path), &reason),
    }
    match read_rows(&connection, site, now_epoch()) {
        Ok(rows) => ScrapeMemoryView {
            available: true,
            path: Some(path.to_string_lossy().into_owned()),
            reason: String::new(),
            rows,
        },
        Err(reason) => unavailable(Some(path), &reason),
    }
}

/// 将某站点的某后端固定为最前；state.sqlite 不存在时只返回不可用视图。
pub fn pin(
    environment: &RuntimeEnvironment,
    site: &str,
    scraper: &str,
) -> Result<ScrapeMemoryView, String> {
    validate_site(site)?;
    let scraper = scraper.trim();
    if !SCRAPE_BACKENDS.contains(&scraper) {
        return Err(format!("不支持的抓取后端：{scraper}"));
    }
    let path = state_path(environment).ok_or("无法定位抓取状态数据库")?;
    if !path.is_file() {
        return Ok(missing(Some(path)));
    }
    let mut connection = read_write(&path)?;
    if !table_present(&connection)? {
        return Ok(unavailable(
            Some(path),
            "尚无抓取状态数据：state.sqlite 里还没有抓取记忆表",
        ));
    }
    let now = now_epoch();
    let stamp = format_utc(now);
    // MIN + INSERT + UPDATE 必须原子：IMMEDIATE 事务立刻拿写锁，
    // 避免两个 pin 同时算出相同 priority 或只写了一半。
    let transaction = connection
        .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .map_err(|_| "抓取状态数据库无法写入".to_string())?;
    let minimum: Option<i64> = transaction
        .query_row(
            "SELECT MIN(manual_priority) FROM site_scraper_stats WHERE site = ?1",
            [site],
            |row| row.get(0),
        )
        .map_err(|_| "抓取状态数据库无法读取".to_string())?;
    let priority = minimum.unwrap_or(0) - 1;
    transaction
        .execute(
            "INSERT OR IGNORE INTO site_scraper_stats (site, scraper, created_at, updated_at) \
             VALUES (?1, ?2, ?3, ?3)",
            rusqlite::params![site, scraper, stamp],
        )
        .map_err(|_| "抓取状态数据库无法写入".to_string())?;
    transaction
        .execute(
            "UPDATE site_scraper_stats SET manually_pinned = 1, manual_priority = ?1, updated_at = ?2 \
             WHERE site = ?3 AND scraper = ?4",
            rusqlite::params![priority, stamp, site, scraper],
        )
        .map_err(|_| "抓取状态数据库无法写入".to_string())?;
    transaction
        .commit()
        .map_err(|_| "抓取状态数据库无法写入".to_string())?;
    drop(connection);
    Ok(view(environment, None))
}

/// 删除指定站点记忆；缺少站点时拒绝写入，不提供全库清空入口。
pub fn reset(environment: &RuntimeEnvironment, site: Option<&str>) -> Result<ScrapeMemoryView, String> {
    let site = site.filter(|site| !site.trim().is_empty()).ok_or("必须指定要清除的站点")?;
    validate_site(site)?;
    let path = state_path(environment).ok_or("无法定位抓取状态数据库")?;
    if !path.is_file() {
        return Ok(missing(Some(path)));
    }
    let connection = read_write(&path)?;
    if !table_present(&connection)? {
        return Ok(unavailable(
            Some(path),
            "尚无抓取状态数据：state.sqlite 里还没有抓取记忆表",
        ));
    }
    let attempts_present: bool = connection
        .query_row(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='scrape_attempts'",
            [],
            |row| row.get::<_, i64>(0),
        )
        .map(|count| count > 0)
        .map_err(|_| "抓取状态数据库无法读取".to_string())?;
    let transaction = connection
        .unchecked_transaction()
        .map_err(|_| "抓取状态数据库无法写入".to_string())?;
    transaction
        .execute("DELETE FROM site_scraper_stats WHERE site = ?1", [site])
        .map_err(|_| "抓取状态数据库无法写入".to_string())?;
    if attempts_present {
        transaction
            .execute("DELETE FROM scrape_attempts WHERE site = ?1", [site])
            .map_err(|_| "抓取状态数据库无法写入".to_string())?;
    }
    transaction
        .commit()
        .map_err(|_| "抓取状态数据库无法写入".to_string())?;
    drop(connection);
    // 返回整体视图：删除某个站点后仍能看到其余记忆，页面直接整体回填。
    Ok(view(environment, None))
}
