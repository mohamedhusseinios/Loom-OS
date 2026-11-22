mod path_bootstrap;
mod stack;
#[allow(dead_code)] // install/log helpers also used by later tasks
mod support;

use tauri::{Manager, RunEvent};

pub struct StackState(pub stack::StackManager);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(StackState(stack::StackManager::new()))
        .setup(|app| {
            let env_path = std::env::var("PATH").unwrap_or_default();
            let home = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")).map(std::path::PathBuf::from).unwrap_or_default();
            path_bootstrap::apply_path_to_process(&path_bootstrap::bootstrap_path(&env_path, &home));

            // `tauri dev` is stopped with SIGINT/SIGTERM, which bypasses RunEvent::Exit; run the same sync shutdown there.
            let on_signal = app.state::<StackState>().0.clone();
            if let Err(e) = ctrlc::set_handler(move || {
                on_signal.shutdown();
                std::process::exit(130);
            }) {
                eprintln!("loom: could not install signal handler: {e}");
            }

            // Window starts hidden; show it once the stack is healthy (or failed, so the user is never stuck).
            let handle = app.handle().clone();
            let manager = app.state::<StackState>().0.clone();
            tauri::async_runtime::spawn(async move {
                let cfg = stack::default_config();
                if let Err(e) = manager.ensure_and_start(&cfg).await {
                    eprintln!("loom stack failed to start: {e}");
                }
                if let Some(w) = handle.get_webview_window("main") {
                    let _ = w.show();
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            // Sync mutex, never held across an await: always able to kill children, even mid-startup.
            handle.state::<StackState>().0.shutdown();
        }
    });
}
