//! Stable IPC error contract: every command rejects with a serialized `{ code, message }`
//! object. `code` is a snake_case tag the frontend's Chinese mapping table keys off; `message`
//! is the localized reason shown to the user. Unknown strings (legacy worker errors) map to a
//! generic Chinese text so no English enum leaks to the UI.
use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
pub struct CommandError {
    pub code: String,
    pub message: String,
}

impl CommandError {
    pub fn new(code: &str, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }
}

impl From<CommandError> for String {
    /// Command handlers still return `Result<_, String>`; serialization happens here.
    fn from(error: CommandError) -> Self {
        serde_json::to_string(&error).unwrap_or_else(|_| {
            format!("{{\"code\":\"{}\",\"message\":\"{}\"}}", error.code, error.message)
        })
    }
}

/// Worker-join and backend-internal failures, grouped by domain. Pages never see the raw
/// English worker names.
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
pub fn backend(code: &str) -> CommandError {
    let message = match code {
        "cli_detect_failed" => "CLI 检测工作器失败",
        "search_start_failed" => "搜索启动工作器失败",
        "execution_poll_failed" => "执行状态读取工作器失败",
        "execution_cancel_failed" => "执行取消工作器失败",
        "skill_plan_failed" => "Skill 预览工作器失败",
        "skill_install_failed" => "Skill 安装工作器失败",
        "install_plan_failed" => "安装计划检查失败",
        "install_failed" => "安装工作器失败",
        "update_failed" => "更新工作器失败",
        "uninstall_failed" => "卸载工作器失败",
        "user_path_check_failed" => "PATH 检查失败",
        "user_path_change_failed" => "PATH 修改失败",
        "credential_status_failed" => "凭据状态读取失败",
        "credential_save_failed" => "凭据保存工作器失败",
        "credential_delete_failed" => "凭据删除工作器失败",
        "credential_test_failed" => "凭据测试工作器失败",
        "migration_plan_failed" => "迁移预览工作器失败",
        "migration_apply_failed" => "迁移执行工作器失败",
        "settings_view_failed" => "设置读取失败",
        "settings_save_failed" => "设置保存工作器失败",
        "skill_status_failed" => "Skill 状态检查工作器失败",
        "skill_update_failed" => "Skill 更新工作器失败",
        "skill_remove_plan_failed" => "Skill 移除预览工作器失败",
        "skill_remove_failed" => "Skill 移除工作器失败",
        "cookie_status_failed" => "Cookie 状态读取失败",
        "cookie_import_failed" => "Cookie 导入工作器失败",
        "cookie_delete_failed" => "Cookie 删除工作器失败",
        "credential_read_failed" => "凭据读取工作器失败",
        "credential_append_failed" => "凭据追加工作器失败",
        "credential_remove_failed" => "凭据移除工作器失败",
        "credential_application_failed" => "申请链接打开失败",
        "scrape_settings_save_failed" => "抓取设置保存工作器失败",
        "rerank_key_save_failed" => "重排 API 密钥保存工作器失败",
        "scrape_memory_view_failed" => "站点抓取记忆读取失败",
        "scrape_memory_pin_failed" => "站点抓取记忆固定失败",
        "scrape_memory_reset_failed" => "站点抓取记忆重置失败",
        _ => "桌面后端操作失败",
    };
    CommandError::new(code, message)
}


/// Keep an operation's own localized message but replace the bare `String` rejection with the
/// `{ code, message }` JSON contract. The frontend shows `message` because the code is generic.
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
pub fn finish<T>(result: Result<T, String>) -> Result<T, String> {
    result.map_err(|message| CommandError::new("operation_failed", message).into())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn payload(text: String) -> (String, String) {
        let value: serde_json::Value = serde_json::from_str(&text).expect("error is JSON");
        (
            value["code"].as_str().unwrap().to_string(),
            value["message"].as_str().unwrap().to_string(),
        )
    }

    #[test]
    fn command_errors_serialize_as_code_and_message() {
        let text: String = CommandError::new("settings_view_failed", "设置读取失败").into();
        assert_eq!(payload(text), ("settings_view_failed".into(), "设置读取失败".into()));
    }

    #[test]
    fn every_worker_code_has_a_chinese_message() {
        for code in [
            "cli_detect_failed", "search_start_failed", "execution_poll_failed",
            "execution_cancel_failed", "skill_plan_failed", "skill_install_failed",
            "install_plan_failed", "install_failed", "update_failed", "uninstall_failed",
            "user_path_check_failed", "user_path_change_failed", "credential_status_failed",
            "credential_save_failed", "credential_delete_failed", "credential_test_failed",
            "migration_plan_failed", "migration_apply_failed", "settings_view_failed",
            "settings_save_failed", "skill_status_failed", "skill_update_failed",
            "skill_remove_plan_failed", "skill_remove_failed", "cookie_status_failed",
            "cookie_import_failed", "cookie_delete_failed", "credential_read_failed",
            "credential_append_failed", "credential_remove_failed", "credential_application_failed",
            "scrape_settings_save_failed", "scrape_memory_view_failed", "scrape_memory_pin_failed",
            "scrape_memory_reset_failed", "rerank_key_save_failed",
        ] {
            let error = backend(code);
            assert_eq!(error.code, code);
            assert!(error.message.chars().any(|c| ('\u{4e00}'..='\u{9fff}').contains(&c)), "{code} must be Chinese");
        }
    }

    #[test]
    fn operation_errors_keep_their_localized_message() {
        let text = finish::<()>(Err("现有配置文件不是有效的 JSON 对象".into())).unwrap_err();
        let (code, message) = payload(text);
        assert_eq!(code, "operation_failed");
        assert_eq!(message, "现有配置文件不是有效的 JSON 对象");
    }
}
