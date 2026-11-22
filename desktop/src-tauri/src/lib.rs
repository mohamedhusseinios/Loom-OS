mod path_bootstrap;
#[allow(dead_code)] // consumed by the stack spawner in the next task
mod support;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|_app| {
            let env_path = std::env::var("PATH").unwrap_or_default();
            let home = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")).map(std::path::PathBuf::from).unwrap_or_default();
            path_bootstrap::apply_path_to_process(&path_bootstrap::bootstrap_path(&env_path, &home));
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
