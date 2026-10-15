//! Shared Python/Rust config database protocol. No legacy source is read here.
use rusqlite::Connection;
use std::{collections::BTreeMap, path::PathBuf};
pub(crate) const DB_ENV: &str = "MULTI_SEARCH_CONFIG_DB";
pub(crate) fn path(variables: &BTreeMap<String,String>) -> Option<PathBuf> {
    if let Some(value)=variables.get(DB_ENV).filter(|v|!v.is_empty()){return Some(PathBuf::from(value));}
    variables.get("USERPROFILE").filter(|v|!v.is_empty()).or_else(||variables.get("HOME").filter(|v|!v.is_empty()))
        .map(|home|PathBuf::from(home).join(".multi-search/config.sqlite"))
}
fn version(c:&Connection)->Result<i64,String>{c.pragma_query_value(None,"user_version",|r|r.get(0)).map_err(|_|"配置数据库无法读取".into())}
fn validate(c:&Connection)->Result<(),String>{
    for (table,expected) in [("credentials",vec![("provider","TEXT",0,1),("encrypted_value","BLOB",1,0),("saved_at","REAL",1,0)]),("settings",vec![("id","INTEGER",0,1),("data","TEXT",1,0)])] {
        let mut stmt=c.prepare(&format!("PRAGMA table_info({table})")).map_err(|_|"配置数据库结构无效".to_string())?;
        let fields=stmt.query_map([],|r|Ok((r.get::<_,String>(1)?,r.get::<_,String>(2)?,r.get::<_,i64>(3)?,r.get::<_,i64>(5)?))).map_err(|_|"配置数据库结构无效".to_string())?.collect::<Result<Vec<_>,_>>().map_err(|_|"配置数据库结构无效".to_string())?;
        if fields.len()!=expected.len()||fields.iter().zip(expected).any(|(a,b)|a.0!=b.0||!a.1.eq_ignore_ascii_case(b.1)||a.2!=b.2||a.3!=b.3){return Err("配置数据库结构无效".into());}
    }
    Ok(())
}
pub(crate) fn open(path:&std::path::Path)->Result<Connection,String>{
    if let Some(parent)=path.parent(){std::fs::create_dir_all(parent).map_err(|_|"无法创建配置数据库目录".to_string())?;}
    let mut c=Connection::open(path).map_err(|_|"无法打开配置数据库".to_string())?;
    c.busy_timeout(std::time::Duration::from_secs(5)).map_err(|_|"配置数据库不可用".to_string())?;
    match version(&c)? {
        1=>validate(&c)?,
        0=>{
            let tx=c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(|_|"配置数据库事务失败".to_string())?;
            match version(&tx)? {
                0=>{
                    let tables:i64=tx.query_row("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",[],|r|r.get(0)).map_err(|_|"配置数据库结构无效".to_string())?;
                    if tables!=0{return Err("非空未版本化数据库不能用作配置数据库".into());}
                    tx.execute_batch("CREATE TABLE credentials(provider TEXT PRIMARY KEY, encrypted_value BLOB NOT NULL, saved_at REAL NOT NULL); CREATE TABLE settings(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL); PRAGMA user_version=1;").map_err(|_|"配置数据库结构无效".to_string())?;
                },
                1=>validate(&tx)?,
                _=>return Err("不支持的配置数据库版本".into()),
            }
            tx.commit().map_err(|_|"配置数据库初始化失败".to_string())?;
        },
        _=>return Err("不支持的配置数据库版本".into()),
    }
    Ok(c)
}
