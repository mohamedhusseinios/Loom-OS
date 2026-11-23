use std::path::PathBuf;
use std::sync::Mutex;

use serde::Serialize;
use tauri::{AppHandle, Manager, State};
use tauri_plugin_opener::OpenerExt;

use crate::stack::{self, Result};
use crate::{StackState, CONTENT_LABEL};

pub const LOCALE: &str = "en";

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct StackStatus {
    pub daemon_ok: bool,
    pub dashboard_ok: bool,
    pub owned: bool,
    pub agent_url: String,
    pub dashboard_url: String,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct PathsDto {
    pub support_root: String,
    pub install_dir: String,
    pub logs_dir: String,
}

/// Last in-app dashboard page (non-agent path), so switching Agent -> Dashboard returns to it.
#[derive(Default)]
pub struct NavState(pub Mutex<Option<String>>);

fn encode_component(s: &str) -> String {
    let mut out = String::new();
    for b in s.bytes() {
        if b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.' | b'~') {
            out.push(b as char);
        } else {
            out.push_str(&format!("%{b:02X}"));
        }
    }
    out
}

/// `<base>/{locale}/agent-app[?project=..&task=..]`; empty values are omitted.
pub fn agent_app_url(base: &str, project: Option<&str>, task: Option<&str>) -> String {
    let mut url = format!("{}/{LOCALE}/agent-app", base.trim_end_matches('/'));
    let params: Vec<String> = [("project", project), ("task", task)].into_iter().filter_map(|(k, v)| v.filter(|v| !v.is_empty()).map(|v| format!("{k}={}", encode_component(v)))).collect();
    if !params.is_empty() {
        url.push('?');
        url.push_str(&params.join("&"));
    }
    url
}

pub fn dashboard_home_url(base: &str) -> String {
    format!("{}/{LOCALE}", base.trim_end_matches('/'))
}

/// True when `url` is the agent-app route (any query/fragment) under `base`.
pub fn is_agent_url(base: &str, url: &str) -> bool {
    let agent = format!("{}/{LOCALE}/agent-app", base.trim_end_matches('/'));
    url.strip_prefix(&agent).is_some_and(|rest| rest.is_empty() || rest.starts_with(['?', '#', '/']))
}

/// Pure tab decision: returns the URL to show and the dashboard page to remember (if leaving one).
/// Agent: keep the current URL when already on agent (preserves `?project=&task=`), else the bare agent URL.
/// Dashboard: keep the current URL when already on a dashboard page, else the remembered page, else `/en`.
pub fn tab_target(base: &str, tab: &str, current: Option<&str>, last_dashboard: Option<&str>) -> (String, Option<String>) {
    let on_base = |u: &&str| u.starts_with(base.trim_end_matches('/'));
    let current_dashboard = current.filter(on_base).filter(|u| !is_agent_url(base, u));
    let remembered = current_dashboard.map(str::to_string).or_else(|| last_dashboard.map(str::to_string));
    if tab == "agent" {
        let target = match current.filter(on_base) {
            Some(u) if is_agent_url(base, u) => u.to_string(),
            _ => agent_app_url(base, None, None),
        };
        return (target, remembered);
    }
    let target = current_dashboard.map(str::to_string).or(remembered.clone()).unwrap_or_else(|| dashboard_home_url(base));
    (target, remembered)
}

#[tauri::command]
pub async fn stack_status(state: State<'_, StackState>) -> std::result::Result<StackStatus, String> {
    let cfg = stack::default_config();
    let daemon_ok = stack::http_get_status(&format!("{}/api/health", cfg.daemon_url.trim_end_matches('/'))).await == Some(200);
    let dashboard_ok = stack::http_get_status(&format!("{}/", cfg.dashboard_url.trim_end_matches('/'))).await.is_some_and(stack::is_dashboard_ready);
    Ok(StackStatus { daemon_ok, dashboard_ok, owned: state.0.is_owned(), agent_url: agent_app_url(&cfg.dashboard_url, None, None), dashboard_url: dashboard_home_url(&cfg.dashboard_url) })
}

/// Stop owned children (no-op when attached), then ensure the stack is up again and reload the content webview.
#[tauri::command]
pub async fn restart_stack(app: AppHandle, state: State<'_, StackState>) -> Result<()> {
    let manager = state.0.clone();
    let cfg = stack::default_config();
    let stopper = manager.clone();
    tokio::task::spawn_blocking(move || stopper.stop_for_restart()).await.map_err(|e| format!("stop task: {e}"))?;
    manager.ensure_and_start(&cfg).await?;
    navigate_content(&app, &agent_app_url(&cfg.dashboard_url, None, None))
}

/// Only runs when invoked (menu / UI); never on launch.
#[tauri::command]
pub fn open_external_dashboard(app: AppHandle) -> Result<()> {
    open_dashboard_in_browser(&app)
}

pub fn open_dashboard_in_browser(app: &AppHandle) -> Result<()> {
    let url = dashboard_home_url(&stack::default_config().dashboard_url);
    app.opener().open_url(url, None::<&str>).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn get_paths() -> PathsDto {
    let home = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")).map(PathBuf::from).unwrap_or_default();
    let root = crate::support::support_root(&home, std::env::consts::OS);
    PathsDto { support_root: root.display().to_string(), install_dir: crate::support::install_dir(&root).display().to_string(), logs_dir: crate::support::logs_dir(&root).display().to_string() }
}

pub fn navigate_content(app: &AppHandle, url: &str) -> Result<()> {
    let webview = app.get_webview(CONTENT_LABEL).ok_or("content webview missing")?;
    webview.navigate(url.parse().map_err(|e| format!("bad url {url}: {e}"))?).map_err(|e| e.to_string())
}

fn html_escape(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;")
}

fn page_shell(title: &str, body: &str) -> String {
    format!("<!doctype html><meta charset=\"utf-8\"><title>{title}</title><body style=\"margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#0b0b0f;color:#e5e5ea;font:14px -apple-system,system-ui,sans-serif\"><div style=\"max-width:640px;padding:24px\">{body}</div></body>")
}

pub fn starting_html() -> String {
    page_shell("Starting Loom", "<h2 style=\"margin:0 0 8px\">Starting Loom\u{2026}</h2><p style=\"color:#8e8e93\">First launch can take a few minutes while dependencies install.</p>")
}

pub fn startup_error_html(error: &str, logs_dir: &str) -> String {
    page_shell(
        "Loom failed to start",
        &format!("<h2 style=\"margin:0 0 8px;color:#ff6b6b\">Loom failed to start</h2><pre style=\"white-space:pre-wrap;background:#16161d;padding:12px;border-radius:6px\">{}</pre><p>Logs: <code>{}</code></p><p style=\"color:#8e8e93\">Fix the problem, then use Restart or relaunch the app.</p>", html_escape(error), html_escape(logs_dir)),
    )
}

/// Percent-encode everything but unreserved characters so the HTML survives inside a `data:` URL.
pub fn html_data_url(html: &str) -> String {
    let mut out = String::from("data:text/html;charset=utf-8,");
    for b in html.bytes() {
        if b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.' | b'~') {
            out.push(b as char);
        } else {
            out.push_str(&format!("%{b:02X}"));
        }
    }
    out
}

/// Show a static HTML page in the content webview (data: URL; falls back to `document.write` on about:blank).
pub fn show_html(app: &AppHandle, html: &str) -> Result<()> {
    if navigate_content(app, &html_data_url(html)).is_ok() {
        return Ok(());
    }
    let webview = app.get_webview(CONTENT_LABEL).ok_or("content webview missing")?;
    let js = format!("document.open();document.write({});document.close();", serde_json::to_string(html).map_err(|e| e.to_string())?);
    webview.eval(js).map_err(|e| e.to_string())
}

/// Switch the single content webview between the Agent app and the Dashboard; returns the URL now shown.
#[tauri::command]
pub fn navigate_tab(app: AppHandle, nav: State<'_, NavState>, tab: String) -> Result<String> {
    let base = stack::DASHBOARD_URL;
    let webview = app.get_webview(CONTENT_LABEL).ok_or("content webview missing")?;
    let current = webview.url().ok().map(|u| u.to_string());
    let mut last = nav.0.lock().unwrap_or_else(|e| e.into_inner());
    let (target, remembered) = tab_target(base, &tab, current.as_deref(), last.as_deref());
    *last = remembered;
    drop(last);
    if current.as_deref() != Some(target.as_str()) {
        navigate_content(&app, &target)?;
    }
    Ok(target)
}

/// Current content URL (for the chrome's URL display / active tab).
#[tauri::command]
pub fn content_url(app: AppHandle) -> Option<String> {
    app.get_webview(CONTENT_LABEL).and_then(|w| w.url().ok()).map(|u| u.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    const BASE: &str = "http://127.0.0.1:3000";

    #[test]
    fn agent_url_bare() {
        assert_eq!(agent_app_url(BASE, None, None), "http://127.0.0.1:3000/en/agent-app");
        assert_eq!(agent_app_url("http://127.0.0.1:3000/", None, None), "http://127.0.0.1:3000/en/agent-app");
    }

    #[test]
    fn agent_url_query_passthrough_and_encoding() {
        assert_eq!(agent_app_url(BASE, Some("p1"), Some("t9")), "http://127.0.0.1:3000/en/agent-app?project=p1&task=t9");
        assert_eq!(agent_app_url(BASE, Some("my proj"), None), "http://127.0.0.1:3000/en/agent-app?project=my%20proj");
        assert_eq!(agent_app_url(BASE, Some(""), Some("t")), "http://127.0.0.1:3000/en/agent-app?task=t");
    }

    #[test]
    fn dashboard_home() {
        assert_eq!(dashboard_home_url(BASE), "http://127.0.0.1:3000/en");
    }

    #[test]
    fn agent_url_detection() {
        assert!(is_agent_url(BASE, "http://127.0.0.1:3000/en/agent-app"));
        assert!(is_agent_url(BASE, "http://127.0.0.1:3000/en/agent-app?project=a&task=b"));
        assert!(!is_agent_url(BASE, "http://127.0.0.1:3000/en/agent-application"));
        assert!(!is_agent_url(BASE, "http://127.0.0.1:3000/en/projects/1"));
    }

    #[test]
    fn agent_tab_preserves_query_when_already_on_agent() {
        let cur = "http://127.0.0.1:3000/en/agent-app?project=p&task=t";
        let (target, remembered) = tab_target(BASE, "agent", Some(cur), None);
        assert_eq!(target, cur);
        assert_eq!(remembered, None);
    }

    #[test]
    fn agent_tab_from_dashboard_remembers_page() {
        let cur = "http://127.0.0.1:3000/en/projects/7";
        let (target, remembered) = tab_target(BASE, "agent", Some(cur), None);
        assert_eq!(target, "http://127.0.0.1:3000/en/agent-app");
        assert_eq!(remembered.as_deref(), Some(cur));
    }

    #[test]
    fn dashboard_tab_restores_last_page_from_agent() {
        let cur = "http://127.0.0.1:3000/en/agent-app?project=p";
        let (target, remembered) = tab_target(BASE, "dashboard", Some(cur), Some("http://127.0.0.1:3000/en/projects/7"));
        assert_eq!(target, "http://127.0.0.1:3000/en/projects/7");
        assert_eq!(remembered.as_deref(), Some("http://127.0.0.1:3000/en/projects/7"));
    }

    #[test]
    fn dashboard_tab_defaults_home_and_stays_put() {
        assert_eq!(tab_target(BASE, "dashboard", Some("http://127.0.0.1:3000/en/agent-app"), None).0, "http://127.0.0.1:3000/en");
        assert_eq!(tab_target(BASE, "dashboard", Some("about:blank"), None).0, "http://127.0.0.1:3000/en");
        let here = "http://127.0.0.1:3000/en/graph";
        assert_eq!(tab_target(BASE, "dashboard", Some(here), None).0, here);
    }

    #[test]
    fn error_page_escapes_and_shows_logs_path() {
        let html = startup_error_html("boom <script>alert(1)</script> & more", "/x/logs");
        assert!(html.contains("boom &lt;script&gt;alert(1)&lt;/script&gt; &amp; more"));
        assert!(!html.contains("<script>"));
        assert!(html.contains("/x/logs"));
    }

    #[test]
    fn data_url_is_encoded_and_parses() {
        let url = html_data_url("<b>a b#c</b>");
        assert!(url.starts_with("data:text/html;charset=utf-8,"));
        assert!(!url[29..].contains(['<', ' ', '#']));
        assert!(url.parse::<tauri::Url>().is_ok());
        assert!(html_data_url(&startup_error_html("e", "/l")).parse::<tauri::Url>().is_ok());
    }
}
