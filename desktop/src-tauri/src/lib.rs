mod path_bootstrap;
mod stack;
#[allow(dead_code)] // install/log helpers also used by later tasks
mod support;

use std::sync::Arc;
use tauri::{Manager, RunEvent};
use tokio::sync::Mutex;

pub struct StackState(pub Arc<Mutex<stack::StackManager>>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(StackState(Arc::new(Mutex::new(stack::StackManager::new()))))
        .setup(|app| {
            let env_path = std::env::var("PATH").unwrap_or_default();
            let home = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")).map(std::path::PathBuf::from).unwrap_or_default();
            path_bootstrap::apply_path_to_process(&path_bootstrap::bootstrap_path(&env_path, &home));

            // Window starts hidden; show it once the stack is healthy (or failed, so the user is never stuck).
            let handle = app.handle().clone();
            let manager = app.state::<StackState>().0.clone();
            tauri::async_runtime::spawn(async move {
                let cfg = stack::default_config();
                if let Err(e) = manager.lock().await.ensure_and_start(&cfg).await {
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
            // try_lock: if startup is still in flight we cannot block quit on it.
            if let Ok(mut m) = handle.state::<StackState>().0.try_lock() {
                m.shutdown();
            }
        }
    });
}
