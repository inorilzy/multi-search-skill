fn main() {
    #[cfg(feature = "native-window")]
    tauri_build::build();
}
