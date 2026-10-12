//! Relocatable CLI launcher shipped inside the installed bundle as `bin/multi-search.exe`.
//!
//! It runs the bundled Python runtime at `../runtime/python.exe` relative to its own location,
//! so the bundle never depends on a build-machine path, a shebang, or an external Python.
//! Arguments and standard streams pass through unchanged; the exit code is propagated.
use std::{
    env,
    path::PathBuf,
    process::{Command, ExitCode},
};

const ENTRY: &str = "import sys; from multi_search_mcp.cli import entrypoint; sys.argv[0] = 'multi-search'; entrypoint()";

fn fail(reason: &str) -> ExitCode {
    eprintln!("multi-search: {reason}");
    ExitCode::from(70)
}

fn bundled_python() -> Result<PathBuf, &'static str> {
    let exe = env::current_exe().map_err(|_| "无法确定启动器位置")?;
    let bundle = exe
        .parent()
        .and_then(|bin| bin.parent())
        .ok_or("启动器不在安装包结构内")?;
    let python = bundle.join("runtime").join("python.exe");
    if python.is_file() {
        Ok(python)
    } else {
        Err("安装包缺少内置 Python 运行时")
    }
}

fn main() -> ExitCode {
    let python = match bundled_python() {
        Ok(python) => python,
        Err(reason) => return fail(reason),
    };
    // -I ignores PYTHON* variables and the user site directory, keeping the bundle self-contained.
    let status = Command::new(&python)
        .arg("-I")
        .arg("-c")
        .arg(ENTRY)
        .args(env::args_os().skip(1))
        .status();
    match status {
        Ok(status) => ExitCode::from(status.code().and_then(|code| u8::try_from(code).ok()).unwrap_or(1)),
        Err(_) => fail("无法启动内置 Python 运行时"),
    }
}
