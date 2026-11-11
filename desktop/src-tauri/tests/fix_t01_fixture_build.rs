use std::{fs, path::Path, process::Command};

fn copy_tree(source: &Path, destination: &Path) {
    fs::create_dir_all(destination).unwrap();
    for entry in fs::read_dir(source).unwrap() {
        let entry = entry.unwrap();
        let target = destination.join(entry.file_name());
        if entry.file_type().unwrap().is_dir() {
            copy_tree(&entry.path(), &target);
        } else {
            fs::copy(entry.path(), target).unwrap();
        }
    }
}

#[test]
fn diagnostics_builds_its_fixture_with_an_external_cargo_target_directory() {
    let source = Path::new(env!("CARGO_MANIFEST_DIR"));
    let root = std::env::temp_dir().join(format!("fix-t01-fixture-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    let checkout = root.join("checkout/desktop/src-tauri");
    fs::create_dir_all(&checkout).unwrap();
    copy_tree(&source.join("../../skills"), &root.join("checkout/skills"));
    fs::copy(
        source.join("../source-catalog.json"),
        checkout.join("../source-catalog.json"),
    )
    .unwrap();
    for name in ["Cargo.toml", "Cargo.lock", "build.rs"] {
        fs::copy(source.join(name), checkout.join(name)).unwrap();
    }
    for name in ["src", "tests"] {
        copy_tree(&source.join(name), &checkout.join(name));
    }
    // A clean worktree using a shared Cargo cache has no local target directory.
    assert!(!checkout.join("target").exists());
    let output = Command::new(env!("CARGO"))
        .args(["test", "--offline", "--locked", "--manifest-path"])
        .arg(checkout.join("Cargo.toml"))
        .args([
            "--no-default-features",
            "--features",
            "test-fixtures",
            "--test",
            "diagnostics",
            "detected_cli_has_actual_path_and_version_but_does_not_imply_user_discovery",
            "--",
            "--exact",
        ])
        .env("CARGO_TARGET_DIR", root.join("build"))
        .output()
        .unwrap();
    let fixture_directory_created = checkout.join("target").is_dir();
    fs::remove_dir_all(&root).unwrap();
    assert!(
        output.status.success(),
        "stdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
    assert!(fixture_directory_created);
}
