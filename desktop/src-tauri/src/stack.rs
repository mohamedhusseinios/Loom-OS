use std::path::{Path, PathBuf};
use std::process::Child;
use std::time::Duration;

pub type Result<T> = std::result::Result<T, String>;

pub const DAEMON_URL: &str = "http://127.0.0.1:8472";
pub const DASHBOARD_URL: &str = "http://127.0.0.1:3000";
const HEALTH_POLL_ATTEMPTS: u32 = 160; // 160 * 250ms = 40s
const HEALTH_POLL_INTERVAL: Duration = Duration::from_millis(250);

#[derive(Debug, Clone)]
pub struct StackConfig {
    pub daemon_url: String,
    pub dashboard_url: String,
    pub install_root: PathBuf,
    pub packaged: bool,
}

#[derive(Default)]
pub struct StackManager {
    pub owned: bool,
    daemon: Option<Child>,
    dashboard: Option<Child>,
}

/// Split `http://host:port/path` into (host, port, path). Only plain http is supported.
pub fn parse_http_url(url: &str) -> Option<(String, u16, String)> {
    let rest = url.strip_prefix("http://")?;
    let (authority, path) = match rest.find('/') {
        Some(i) => (&rest[..i], &rest[i..]),
        None => (rest, "/"),
    };
    let (host, port) = match authority.rsplit_once(':') {
        Some((h, p)) => (h, p.parse::<u16>().ok()?),
        None => (authority, 80),
    };
    if host.is_empty() {
        return None;
    }
    Some((host.to_string(), port, path.to_string()))
}

/// Extract the status code from the first line of an HTTP response.
pub fn parse_status_line(response: &str) -> Option<u16> {
    let line = response.lines().next()?;
    let mut parts = line.split_whitespace();
    if !parts.next()?.starts_with("HTTP/") {
        return None;
    }
    parts.next()?.parse().ok()
}

pub fn is_success(status: u16) -> bool {
    (200..300).contains(&status)
}

async fn http_get_status(url: &str) -> Option<u16> {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let (host, port, path) = parse_http_url(url)?;
    let work = async {
        let mut stream = tokio::net::TcpStream::connect((host.as_str(), port)).await.ok()?;
        let req = format!("GET {path} HTTP/1.0\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n");
        stream.write_all(req.as_bytes()).await.ok()?;
        let mut buf = vec![0u8; 512];
        let n = stream.read(&mut buf).await.ok()?;
        parse_status_line(&String::from_utf8_lossy(&buf[..n]))
    };
    tokio::time::timeout(Duration::from_secs(2), work).await.ok().flatten()
}

/// True iff daemon `/api/health` is 200 and dashboard `/` is 2xx.
pub async fn probe_healthy(daemon_url: &str, dashboard_url: &str) -> bool {
    let daemon_ok = http_get_status(&format!("{}/api/health", daemon_url.trim_end_matches('/'))).await == Some(200);
    if !daemon_ok {
        return false;
    }
    http_get_status(&format!("{}/", dashboard_url.trim_end_matches('/'))).await.is_some_and(is_success)
}

/// Install root: `LOOM_DESKTOP_REPO` override, else repo checkout (`manifest_dir/../../..`) in dev, else the support `app` dir.
pub fn resolve_install_root(packaged: bool, env_override: Option<PathBuf>, manifest_dir: &Path, packaged_dir: &Path) -> PathBuf {
    if let Some(p) = env_override {
        return p;
    }
    if packaged {
        return packaged_dir.to_path_buf();
    }
    manifest_dir.join("..").join("..").join("..")
}

/// Packaged when built without debug assertions, or when `LOOM_DESKTOP_PACKAGED=1`.
pub fn is_packaged() -> bool {
    !cfg!(debug_assertions) || std::env::var("LOOM_DESKTOP_PACKAGED").is_ok_and(|v| v == "1")
}

pub fn default_config() -> StackConfig {
    let packaged = is_packaged();
    let home = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")).map(PathBuf::from).unwrap_or_default();
    let packaged_dir = crate::support::install_dir(&crate::support::support_root(&home, std::env::consts::OS));
    let env_override = std::env::var_os("LOOM_DESKTOP_REPO").map(PathBuf::from);
    StackConfig {
        daemon_url: DAEMON_URL.to_string(),
        dashboard_url: DASHBOARD_URL.to_string(),
        install_root: resolve_install_root(packaged, env_override, Path::new(env!("CARGO_MANIFEST_DIR")), &packaged_dir),
        packaged,
    }
}

fn venv_bin(root: &Path) -> PathBuf {
    root.join(".venv").join(if cfg!(windows) { "Scripts" } else { "bin" })
}

fn exe(name: &str) -> String {
    if cfg!(windows) { format!("{name}.exe") } else { name.to_string() }
}

fn log_file(name: &str) -> Result<std::fs::File> {
    let home = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")).map(PathBuf::from).unwrap_or_default();
    let dir = crate::support::logs_dir(&crate::support::support_root(&home, std::env::consts::OS));
    std::fs::create_dir_all(&dir).map_err(|e| format!("create logs dir: {e}"))?;
    std::fs::OpenOptions::new().create(true).append(true).open(dir.join(name)).map_err(|e| format!("open log {name}: {e}"))
}

fn npm() -> &'static str {
    if cfg!(windows) { "npm.cmd" } else { "npm" }
}

fn run_step(label: &str, cmd: &mut std::process::Command) -> Result<()> {
    let status = cmd.status().map_err(|e| format!("{label}: {e}"))?;
    if status.success() { Ok(()) } else { Err(format!("{label} failed ({status})")) }
}

fn path_with_venv(root: &Path) -> std::ffi::OsString {
    let mut paths = vec![venv_bin(root)];
    if let Some(p) = std::env::var_os("PATH") {
        paths.extend(std::env::split_paths(&p));
    }
    std::env::join_paths(paths).unwrap_or_default()
}

/// Blocking: create venv, install daemon deps, install dashboard deps, build dashboard when packaged.
fn ensure_deps(cfg: &StackConfig) -> Result<()> {
    let root = &cfg.install_root;
    let dashboard = root.join("dashboard");
    if !venv_bin(root).join(exe("python")).exists() {
        let py = if cfg!(windows) { "python" } else { "python3" };
        run_step("create venv", std::process::Command::new(py).args(["-m", "venv"]).arg(root.join(".venv")).current_dir(root))?;
    }
    let marker = root.join(".venv").join(".loom-desktop-installed");
    if !venv_bin(root).join(exe("loom")).exists() || !marker.exists() {
        run_step(
            "pip install",
            std::process::Command::new(venv_bin(root).join(exe("python"))).args(["-m", "pip", "install", "-e", ".[llm]", "--quiet"]).current_dir(root),
        )?;
        let _ = std::fs::write(&marker, b"ok");
    }
    if !dashboard.join("node_modules").exists() {
        run_step("npm install", std::process::Command::new(npm()).args(["install", "--silent"]).current_dir(&dashboard).env("PATH", path_with_venv(root)))?;
    }
    if cfg.packaged && !dashboard.join(".next").join("BUILD_ID").exists() {
        run_step("next build", std::process::Command::new(npm()).args(["run", "build"]).current_dir(&dashboard).env("PATH", path_with_venv(root)))?;
    }
    Ok(())
}

fn spawn_logged(label: &str, cmd: &mut std::process::Command, log: &str) -> Result<Child> {
    let out = log_file(log)?;
    let err = out.try_clone().map_err(|e| format!("clone log: {e}"))?;
    cmd.stdout(out).stderr(err).stdin(std::process::Stdio::null());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
    }
    cmd.spawn().map_err(|e| format!("spawn {label}: {e}"))
}

#[cfg(unix)]
fn kill_tree(child: &mut Child) {
    let pgid = child.id() as i32;
    // Child leads its own process group (process_group(0)), so signalling -pgid reaches the whole tree.
    unsafe {
        libc::kill(-pgid, libc::SIGTERM);
    }
    for _ in 0..20 {
        if matches!(child.try_wait(), Ok(Some(_))) {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    unsafe {
        libc::kill(-pgid, libc::SIGKILL);
    }
    let _ = child.wait();
}

#[cfg(windows)]
fn kill_tree(child: &mut Child) {
    let _ = std::process::Command::new("taskkill").args(["/T", "/F", "/PID", &child.id().to_string()]).status();
    let _ = child.wait();
}

impl StackManager {
    pub fn new() -> Self {
        Self::default()
    }

    pub async fn ensure_and_start(&mut self, cfg: &StackConfig) -> Result<()> {
        if probe_healthy(&cfg.daemon_url, &cfg.dashboard_url).await {
            self.owned = false;
            return Ok(());
        }
        let cfg_owned = cfg.clone();
        tokio::task::spawn_blocking(move || ensure_deps(&cfg_owned)).await.map_err(|e| format!("ensure deps task: {e}"))??;

        let root = &cfg.install_root;
        let path = path_with_venv(root);
        let (daemon_host, daemon_port) = parse_http_url(&cfg.daemon_url).map(|(h, p, _)| (h, p)).ok_or("bad daemon_url")?;
        let (_, dashboard_port, _) = parse_http_url(&cfg.dashboard_url).ok_or("bad dashboard_url")?;

        // Only spawn what is not already answering (e.g. daemon up but dashboard down).
        let daemon_up = http_get_status(&format!("{}/api/health", cfg.daemon_url.trim_end_matches('/'))).await == Some(200);
        if !daemon_up {
            let mut cmd = std::process::Command::new(venv_bin(root).join(exe("loom")));
            cmd.args(["start", "--host", &daemon_host, "--port", &daemon_port.to_string()]).current_dir(root).env("PATH", &path).env("VIRTUAL_ENV", root.join(".venv"));
            self.daemon = Some(spawn_logged("daemon", &mut cmd, "daemon.log")?);
        }
        let dashboard_up = http_get_status(&format!("{}/", cfg.dashboard_url.trim_end_matches('/'))).await.is_some_and(is_success);
        if !dashboard_up {
            let script = if cfg.packaged { "start" } else { "dev" };
            let mut cmd = std::process::Command::new(npm());
            cmd.args(["run", script, "--", "-p", &dashboard_port.to_string()]).current_dir(root.join("dashboard")).env("PATH", &path);
            self.dashboard = Some(spawn_logged("dashboard", &mut cmd, "dashboard.log")?);
        }
        self.owned = true;

        for _ in 0..HEALTH_POLL_ATTEMPTS {
            if probe_healthy(&cfg.daemon_url, &cfg.dashboard_url).await {
                return Ok(());
            }
            if let Some(c) = self.daemon.as_mut() {
                if let Ok(Some(status)) = c.try_wait() {
                    return Err(format!("daemon exited early ({status}); see daemon.log"));
                }
            }
            if let Some(c) = self.dashboard.as_mut() {
                if let Ok(Some(status)) = c.try_wait() {
                    return Err(format!("dashboard exited early ({status}); see dashboard.log"));
                }
            }
            tokio::time::sleep(HEALTH_POLL_INTERVAL).await;
        }
        Err("stack did not become healthy within 40s".to_string())
    }

    /// Kill owned process trees; no-op when attached to an externally managed stack.
    pub fn shutdown(&mut self) {
        if !self.owned {
            return;
        }
        for mut child in [self.dashboard.take(), self.daemon.take()].into_iter().flatten() {
            kill_tree(&mut child);
        }
        self.owned = false;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;

    /// Serve `responses` (matched by request path prefix) on an ephemeral port; returns base URL.
    async fn serve(routes: Vec<(&'static str, &'static str)>) -> String {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        tokio::spawn(async move {
            loop {
                let Ok((mut s, _)) = listener.accept().await else { return };
                let routes = routes.clone();
                tokio::spawn(async move {
                    let mut buf = vec![0u8; 1024];
                    let n = s.read(&mut buf).await.unwrap_or(0);
                    let req = String::from_utf8_lossy(&buf[..n]).to_string();
                    let path = req.split_whitespace().nth(1).unwrap_or("/").to_string();
                    let status = routes.iter().find(|(p, _)| *p == path).map(|(_, st)| *st).unwrap_or("404 Not Found");
                    let _ = s.write_all(format!("HTTP/1.1 {status}\r\nContent-Length: 0\r\n\r\n").as_bytes()).await;
                });
            }
        });
        format!("http://127.0.0.1:{port}")
    }

    #[tokio::test]
    async fn probe_true_when_both_healthy() {
        let daemon = serve(vec![("/api/health", "200 OK")]).await;
        let dash = serve(vec![("/", "200 OK")]).await;
        assert!(probe_healthy(&daemon, &dash).await);
    }

    #[tokio::test]
    async fn probe_false_when_daemon_unhealthy() {
        let daemon = serve(vec![("/api/health", "500 Internal Server Error")]).await;
        let dash = serve(vec![("/", "200 OK")]).await;
        assert!(!probe_healthy(&daemon, &dash).await);
    }

    #[tokio::test]
    async fn probe_false_when_dashboard_not_2xx() {
        let daemon = serve(vec![("/api/health", "200 OK")]).await;
        let dash = serve(vec![("/", "503 Service Unavailable")]).await;
        assert!(!probe_healthy(&daemon, &dash).await);
    }

    #[tokio::test]
    async fn probe_false_when_nothing_listening() {
        let l = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let dead = format!("http://127.0.0.1:{}", l.local_addr().unwrap().port());
        drop(l);
        assert!(!probe_healthy(&dead, &dead).await);
    }

    #[test]
    fn shutdown_noop_when_not_owned() {
        let mut m = StackManager::new();
        m.owned = false;
        m.shutdown();
        assert!(!m.owned);
        assert!(m.daemon.is_none() && m.dashboard.is_none());
    }

    #[cfg(unix)]
    #[test]
    fn shutdown_kills_owned_process_tree() {
        use std::os::unix::process::CommandExt;
        let mut cmd = std::process::Command::new("sh");
        cmd.args(["-c", "sleep 60 & wait"]).process_group(0);
        let child = cmd.spawn().unwrap();
        let pid = child.id() as i32;
        let mut m = StackManager::new();
        m.owned = true;
        m.daemon = Some(child);
        m.shutdown();
        assert!(!m.owned);
        std::thread::sleep(Duration::from_millis(200));
        assert_eq!(unsafe { libc::kill(-pid, 0) }, -1, "process group should be gone");
    }

    #[test]
    fn parse_url_and_status() {
        assert_eq!(parse_http_url("http://127.0.0.1:8472/api/health"), Some(("127.0.0.1".into(), 8472, "/api/health".into())));
        assert_eq!(parse_http_url("http://localhost"), Some(("localhost".into(), 80, "/".into())));
        assert_eq!(parse_http_url("https://x"), None);
        assert_eq!(parse_status_line("HTTP/1.1 204 No Content\r\n"), Some(204));
        assert_eq!(parse_status_line("garbage"), None);
        assert!(is_success(200) && !is_success(404));
    }

    #[test]
    fn install_root_resolution() {
        let manifest = Path::new("/repo/desktop/src-tauri");
        let app = Path::new("/support/app");
        assert_eq!(resolve_install_root(false, Some("/custom".into()), manifest, app), PathBuf::from("/custom"));
        assert_eq!(resolve_install_root(true, Some("/custom".into()), manifest, app), PathBuf::from("/custom"));
        assert_eq!(resolve_install_root(true, None, manifest, app), PathBuf::from("/support/app"));
        assert_eq!(resolve_install_root(false, None, manifest, app), PathBuf::from("/repo/desktop/src-tauri/../../.."));
    }
}
