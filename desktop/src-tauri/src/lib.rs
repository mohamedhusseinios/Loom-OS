mod commands;
mod path_bootstrap;
mod stack;
#[allow(dead_code)] // install/log helpers also used by later tasks
mod support;

use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::webview::WebviewBuilder;
use tauri::window::WindowBuilder;
use tauri::{LogicalPosition, LogicalSize, Manager, RunEvent, WebviewUrl, WindowEvent};

pub const CHROME_LABEL: &str = "chrome";
pub const CONTENT_LABEL: &str = "content";
const CHROME_HEIGHT: f64 = 48.0;
const MENU_OPEN_BROWSER: &str = "open_dashboard_in_browser";

pub struct StackState(pub stack::StackManager);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(StackState(stack::StackManager::new()))
        .manage(commands::NavState::default())
        .invoke_handler(tauri::generate_handler![commands::stack_status, commands::restart_stack, commands::open_external_dashboard, commands::get_paths, commands::navigate_tab, commands::content_url])
        .on_menu_event(|app, event| {
            if event.id().as_ref() == MENU_OPEN_BROWSER {
                if let Err(e) = commands::open_dashboard_in_browser(app) {
                    eprintln!("loom: open dashboard in browser failed: {e}");
                }
            }
        })
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

            if let Ok(res) = app.path().resource_dir() {
                stack::set_payload_dir(res.join("payload"));
            }

            let window = build_main_window(app.handle())?;
            let handle = app.handle().clone();
            let menu = Menu::default(&handle)?;
            let loom_menu = Submenu::with_items(&handle, "Loom", true, &[&MenuItem::with_id(&handle, MENU_OPEN_BROWSER, "Open Dashboard in Browser", true, None::<&str>)?, &PredefinedMenuItem::separator(&handle)?])?;
            menu.append(&loom_menu)?;
            app.set_menu(menu)?;

            // Show the window right away with a "Starting Loom..." page; swap in the dashboard once healthy, or an error page (with logs path) on failure.
            if let Err(e) = commands::show_html(&handle, &commands::starting_html()) {
                eprintln!("loom: starting page failed: {e}");
            }
            let _ = window.show();
            let manager = app.state::<StackState>().0.clone();
            tauri::async_runtime::spawn(async move {
                let cfg = stack::default_config();
                match manager.ensure_and_start(&cfg).await {
                    Ok(()) => {
                        if let Err(e) = commands::navigate_content(&handle, &commands::agent_app_url(&cfg.dashboard_url, None, None)) {
                            eprintln!("loom: initial navigate failed: {e}");
                        }
                    }
                    Err(e) => {
                        eprintln!("loom stack failed to start: {e}");
                        let logs = commands::get_paths().logs_dir;
                        if let Err(e2) = commands::show_html(&handle, &commands::startup_error_html(&e, &logs)) {
                            eprintln!("loom: error page failed: {e2}");
                        }
                    }
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

/// One window, two webviews: a local chrome strip (tabs) on top and a single content webview below (starts blank).
fn build_main_window(handle: &tauri::AppHandle) -> tauri::Result<tauri::Window> {
    let window = WindowBuilder::new(handle, "main").title("Loom Coding Agent").inner_size(1280.0, 800.0).visible(false).build()?;
    let size = window.inner_size()?.to_logical::<f64>(window.scale_factor()?);
    window.add_child(WebviewBuilder::new(CHROME_LABEL, WebviewUrl::App("index.html".into())), LogicalPosition::new(0.0, 0.0), LogicalSize::new(size.width, CHROME_HEIGHT))?;
    window.add_child(WebviewBuilder::new(CONTENT_LABEL, WebviewUrl::External("about:blank".parse().expect("static url"))), LogicalPosition::new(0.0, CHROME_HEIGHT), LogicalSize::new(size.width, (size.height - CHROME_HEIGHT).max(0.0)))?;
    let handle = handle.clone();
    window.on_window_event(move |event| {
        if let WindowEvent::Resized(physical) = event {
            let Some(win) = handle.get_window("main") else { return };
            let Ok(scale) = win.scale_factor() else { return };
            let size = physical.to_logical::<f64>(scale);
            if let Some(w) = handle.get_webview(CHROME_LABEL) {
                let _ = w.set_size(LogicalSize::new(size.width, CHROME_HEIGHT));
            }
            if let Some(w) = handle.get_webview(CONTENT_LABEL) {
                let _ = w.set_position(LogicalPosition::new(0.0, CHROME_HEIGHT));
                let _ = w.set_size(LogicalSize::new(size.width, (size.height - CHROME_HEIGHT).max(0.0)));
            }
        }
    });
    Ok(window)
}
