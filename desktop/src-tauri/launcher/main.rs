//! Relocatable CLI launcher shipped inside the installed bundle as `bin/multi-search`
//! (`bin/multi-search.exe` on Windows).
//!
//! It runs the bundled Python runtime next to its own location —
//! `../runtime/python.exe` on Windows, `../runtime/bin/python3.12` on macOS — so the
//! bundle never depends on a build-machine path, a shebang, or an external Python.
//! Arguments and standard streams pass through unchanged; the exit code is propagated.
use std::{
    env,
    path::PathBuf,
    process::{Command, ExitCode},
};

const ENTRY: &str = "import sys; from multi_search_mcp.cli import entrypoint; sys.argv[0] = 'multi-search'; entrypoint()";

#[cfg(windows)]
const PYTHON_REL: &[&str] = &["python.exe"];
#[cfg(not(windows))]
const PYTHON_REL: &[&str] = &["bin", "python3.12"];

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
    let python = PYTHON_REL
        .iter()
        .fold(bundle.join("runtime"), |path, part| path.join(part));
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
    // -B forbids bytecode writes: without it a `--version` probe litters the signed bundle with
    // `__pycache__` directories whose bytes no longer match the manifest. -I implies -E, so the
    // environment variable below is belt-and-braces for interpreters/call paths that ignore -B;
    // the flag is the one CPython honours here.
    let status = Command::new(&python)
        .arg("-B")
        .arg("-I")
        .arg("-c")
        .arg(ENTRY)
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .args(env::args_os().skip(1))
        .status();
    match status {
        Ok(status) => ExitCode::from(status.code().and_then(|code| u8::try_from(code).ok()).unwrap_or(1)),
        Err(_) => fail("无法启动内置 Python 运行时"),
    }
}
