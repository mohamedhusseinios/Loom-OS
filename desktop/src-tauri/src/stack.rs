use std::path::{Path, PathBuf};
use std::process::Child;
use std::sync::{Arc, Mutex, MutexGuard};
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
    /// Bundled app resources `payload/` dir (set at startup in packaged builds); copied into `install_root` on first run / upgrade.
    pub payload_dir: Option<PathBuf>,
}

static PAYLOAD_DIR: std::sync::OnceLock<PathBuf> = std::sync::OnceLock::new();

/// Record the bundled payload location (from Tauri `resource_dir()/payload`) for `default_config`.
pub fn set_payload_dir(dir: PathBuf) {
    let _ = PAYLOAD_DIR.set(dir);
}

/// Child handles live behind a *sync* mutex that is never held across an `.await`, so
/// `shutdown` (GUI exit / SIGINT) can always run, even while `ensure_and_start` is in flight.
#[derive(Default)]
pub(crate) struct Inner {
    pub(crate) owned: bool,
    shutting_down: bool,
    pub(crate) daemon: Option<Child>,
    pub(crate) dashboard: Option<Child>,
}

#[derive(Clone, Default)]
pub struct StackManager {
    inner: Arc<Mutex<Inner>>,
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

/// Dashboard readiness: Next + next-intl answers `/` with a 307 redirect to `/en`, so 2xx or 3xx both mean "up".
pub fn is_dashboard_ready(status: u16) -> bool {
    (200..400).contains(&status)
}

pub(crate) async fn http_get_status(url: &str) -> Option<u16> {
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

/// True iff daemon `/api/health` is 200 and dashboard `/` is 2xx or 3xx.
pub async fn probe_healthy(daemon_url: &str, dashboard_url: &str) -> bool {
    let daemon_ok = http_get_status(&format!("{}/api/health", daemon_url.trim_end_matches('/'))).await == Some(200);
    if !daemon_ok {
        return false;
    }
    http_get_status(&format!("{}/", dashboard_url.trim_end_matches('/'))).await.is_some_and(is_dashboard_ready)
}

/// Install root: `LOOM_DESKTOP_REPO` override, else repo checkout (`manifest_dir/../..`, since manifest_dir is `<repo>/desktop/src-tauri`) in dev, else the support `app` dir.
pub fn resolve_install_root(packaged: bool, env_override: Option<PathBuf>, manifest_dir: &Path, packaged_dir: &Path) -> PathBuf {
    if let Some(p) = env_override {
        return p;
    }
    if packaged {
        return packaged_dir.to_path_buf();
    }
    manifest_dir.join("..").join("..")
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
        payload_dir: PAYLOAD_DIR.get().cloned(),
    }
}

const PAYLOAD_MARKER: &str = ".loom-payload-version";

fn copy_dir_overlay(src: &Path, dst: &Path) -> Result<()> {
    std::fs::create_dir_all(dst).map_err(|e| format!("create {}: {e}", dst.display()))?;
    for entry in std::fs::read_dir(src).map_err(|e| format!("read {}: {e}", src.display()))? {
        let entry = entry.map_err(|e| format!("read entry: {e}"))?;
        let (from, to) = (entry.path(), dst.join(entry.file_name()));
        if entry.file_type().map_err(|e| format!("file type: {e}"))?.is_dir() {
            copy_dir_overlay(&from, &to)?;
        } else {
            std::fs::copy(&from, &to).map_err(|e| format!("copy {}: {e}", from.display()))?;
        }
    }
    Ok(())
}

/// Copy the bundled payload into `install_root` when missing or when its version marker differs. Existing `.venv` / `node_modules` are kept; on upgrade the dashboard build and pip marker are invalidated. Returns whether a copy happened.
pub fn install_payload(payload: &Path, install_root: &Path, version: &str) -> Result<bool> {
    if !payload.join("run.sh").is_file() {
        return Err(format!("bundled payload missing at {}", payload.display()));
    }
    let marker = install_root.join(PAYLOAD_MARKER);
    let installed = install_root.join("run.sh").is_file() && install_root.join("coding_agent").is_dir();
    if installed && std::fs::read_to_string(&marker).is_ok_and(|v| v.trim() == version) {
        return Ok(false);
    }
    copy_dir_overlay(payload, install_root)?;
    let _ = std::fs::remove_dir_all(install_root.join("dashboard").join(".next"));
    let _ = std::fs::remove_file(install_root.join(".venv").join(".loom-desktop-installed"));
    std::fs::write(&marker, version).map_err(|e| format!("write payload marker: {e}"))?;
    Ok(true)
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
    if cfg.packaged {
        if let Some(payload) = &cfg.payload_dir {
            install_payload(payload, root, env!("CARGO_PKG_VERSION"))?;
        }
    }
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
fn group_alive(pgid: i32) -> bool {
    unsafe { libc::kill(-pgid, 0) == 0 }
}

#[cfg(unix)]
fn kill_tree(child: &mut Child) {
    let pgid = child.id() as i32;
    // Child leads its own process group (process_group(0)), so signalling -pgid reaches the whole tree.
    unsafe {
        libc::kill(-pgid, libc::SIGTERM);
    }
    let mut leader_gone = false;
    for _ in 0..20 {
        if matches!(child.try_wait(), Ok(Some(_))) {
            leader_gone = true;
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    if !leader_gone {
        unsafe {
            libc::kill(-pgid, libc::SIGKILL);
        }
        let _ = child.wait();
    }
    // The leader may exit while descendants ignore/outlive SIGTERM: give them a short grace, then SIGKILL the group.
    for _ in 0..10 {
        if !group_alive(pgid) {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    unsafe {
        libc::kill(-pgid, libc::SIGKILL);
    }
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

    fn lock(&self) -> MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub fn is_owned(&self) -> bool {
        self.lock().owned
    }

    pub async fn ensure_and_start(&self, cfg: &StackConfig) -> Result<()> {
        if probe_healthy(&cfg.daemon_url, &cfg.dashboard_url).await {
            self.lock().owned = false;
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
            // Handle is stored (and `owned` set) under the sync lock the instant the child exists; no await in between.
            let mut g = self.lock();
            if g.shutting_down {
                return Err("shutdown in progress".to_string());
            }
            g.daemon = Some(spawn_logged("daemon", &mut cmd, "daemon.log")?);
            g.owned = true;
        }
        let dashboard_up = http_get_status(&format!("{}/", cfg.dashboard_url.trim_end_matches('/'))).await.is_some_and(is_dashboard_ready);
        if !dashboard_up {
            let script = if cfg.packaged { "start" } else { "dev" };
            let mut cmd = std::process::Command::new(npm());
            cmd.args(["run", script, "--", "-p", &dashboard_port.to_string()]).current_dir(root.join("dashboard")).env("PATH", &path);
            let mut g = self.lock();
            if g.shutting_down {
                return Err("shutdown in progress".to_string());
            }
            g.dashboard = Some(spawn_logged("dashboard", &mut cmd, "dashboard.log")?);
            g.owned = true;
        }

        for _ in 0..HEALTH_POLL_ATTEMPTS {
            if probe_healthy(&cfg.daemon_url, &cfg.dashboard_url).await {
                return Ok(());
            }
            {
                let mut g = self.lock();
                if g.shutting_down {
                    return Err("shutdown in progress".to_string());
                }
                if let Some(c) = g.daemon.as_mut() {
                    if let Ok(Some(status)) = c.try_wait() {
                        return Err(format!("daemon exited early ({status}); see daemon.log"));
                    }
                }
                if let Some(c) = g.dashboard.as_mut() {
                    if let Ok(Some(status)) = c.try_wait() {
                        return Err(format!("dashboard exited early ({status}); see dashboard.log"));
                    }
                }
            }
            tokio::time::sleep(HEALTH_POLL_INTERVAL).await;
        }
        Err("stack did not become healthy within 40s".to_string())
    }

    /// Kill owned process trees; no-op when attached to an externally managed stack.
    /// Safe to call from any thread at any time (GUI exit, SIGINT handler), including mid-`ensure_and_start`.
    pub fn shutdown(&self) {
        self.stop(true);
    }

    /// Stop owned children like `shutdown`, but leave the manager reusable (does not latch `shutting_down`).
    pub fn stop_for_restart(&self) {
        self.stop(false);
    }

    fn stop(&self, latch: bool) {
        let children = {
            let mut g = self.lock();
            if latch {
                g.shutting_down = true; // stop any in-flight ensure from spawning more
            }
            if !g.owned {
                return;
            }
            g.owned = false;
            [g.dashboard.take(), g.daemon.take()]
        };
        // Kill outside the lock so ensure_and_start is never blocked behind the SIGTERM grace period.
        for mut child in children.into_iter().flatten() {
            kill_tree(&mut child);
        }
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
    async fn probe_true_when_dashboard_redirects() {
        // Next + next-intl answers `/` with 307 -> `/en`.
        let daemon = serve(vec![("/api/health", "200 OK")]).await;
        let dash = serve(vec![("/", "307 Temporary Redirect")]).await;
        assert!(probe_healthy(&daemon, &dash).await);
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

    #[cfg(unix)]
    #[test]
    fn shutdown_noop_when_not_owned() {
        let child = std::process::Command::new("sleep").arg("60").spawn().unwrap();
        let pid = child.id() as i32;
        let m = StackManager::new();
        {
            let mut g = m.lock();
            g.owned = false;
            g.daemon = Some(child);
        }
        m.shutdown();
        assert!(!m.is_owned());
        assert!(m.lock().daemon.is_some(), "attached stack: child handle must be untouched");
        assert_eq!(unsafe { libc::kill(pid, 0) }, 0, "non-owned child must still be alive");
        let mut c = m.lock().daemon.take().unwrap();
        let _ = c.kill();
        let _ = c.wait();
    }

    #[cfg(unix)]
    #[test]
    fn shutdown_kills_owned_process_tree() {
        use std::os::unix::process::CommandExt;
        let mut cmd = std::process::Command::new("sh");
        cmd.args(["-c", "sleep 60 & wait"]).process_group(0);
        let child = cmd.spawn().unwrap();
        let pid = child.id() as i32;
        let m = StackManager::new();
        {
            let mut g = m.lock();
            g.owned = true;
            g.daemon = Some(child);
        }
        m.shutdown();
        assert!(!m.is_owned());
        std::thread::sleep(Duration::from_millis(200));
        assert_eq!(unsafe { libc::kill(-pid, 0) }, -1, "process group should be gone");
    }

    #[cfg(unix)]
    #[test]
    fn shutdown_sigkills_group_when_leader_exits_but_descendant_survives() {
        use std::os::unix::process::CommandExt;
        // Leader exits on SIGTERM-independent path; the background sleep ignores SIGTERM and outlives it.
        let mut cmd = std::process::Command::new("sh");
        cmd.args(["-c", "trap '' TERM; sleep 60 & exit 0"]).process_group(0);
        let child = cmd.spawn().unwrap();
        let pid = child.id() as i32;
        std::thread::sleep(Duration::from_millis(300));
        let m = StackManager::new();
        {
            let mut g = m.lock();
            g.owned = true;
            g.dashboard = Some(child);
        }
        m.shutdown();
        std::thread::sleep(Duration::from_millis(200));
        assert_eq!(unsafe { libc::kill(-pid, 0) }, -1, "surviving descendant must be SIGKILLed");
    }

    #[test]
    fn shutdown_during_ensure_still_sees_children() {
        // Children registered by ensure_and_start are reachable from shutdown without any async lock.
        let m = StackManager::new();
        let m2 = m.clone();
        let t = std::thread::spawn(move || {
            let mut g = m2.lock();
            g.owned = true;
        });
        t.join().unwrap();
        m.shutdown();
        assert!(!m.is_owned());
        assert!(m.lock().shutting_down);
    }

    #[test]
    fn parse_url_and_status() {
        assert_eq!(parse_http_url("http://127.0.0.1:8472/api/health"), Some(("127.0.0.1".into(), 8472, "/api/health".into())));
        assert_eq!(parse_http_url("http://localhost"), Some(("localhost".into(), 80, "/".into())));
        assert_eq!(parse_http_url("https://x"), None);
        assert_eq!(parse_status_line("HTTP/1.1 204 No Content\r\n"), Some(204));
        assert_eq!(parse_status_line("garbage"), None);
        assert!(is_dashboard_ready(307) && is_dashboard_ready(200) && !is_dashboard_ready(404) && !is_dashboard_ready(503));
    }

    #[test]
    fn install_root_resolution() {
        let manifest = Path::new("/repo/desktop/src-tauri");
        let app = Path::new("/support/app");
        assert_eq!(resolve_install_root(false, Some("/custom".into()), manifest, app), PathBuf::from("/custom"));
        assert_eq!(resolve_install_root(true, Some("/custom".into()), manifest, app), PathBuf::from("/custom"));
        assert_eq!(resolve_install_root(true, None, manifest, app), PathBuf::from("/support/app"));
        assert_eq!(resolve_install_root(false, None, manifest, app), PathBuf::from("/repo/desktop/src-tauri/../.."));
    }

    #[test]
    fn install_root_is_repo_checkout_with_real_manifest_dir() {
        let root = resolve_install_root(false, None, Path::new(env!("CARGO_MANIFEST_DIR")), Path::new("/unused"));
        assert!(root.join("pyproject.toml").is_file(), "pyproject.toml missing under {}", root.display());
        assert!(root.join("dashboard").is_dir(), "dashboard/ missing under {}", root.display());
    }

    #[test]
    fn install_root_resolves_to_repo_in_temp_layout() {
        let tmp = tempfile::tempdir().unwrap();
        let manifest = tmp.path().join("desktop").join("src-tauri");
        std::fs::create_dir_all(&manifest).unwrap();
        std::fs::write(tmp.path().join("pyproject.toml"), "").unwrap();
        std::fs::create_dir_all(tmp.path().join("dashboard")).unwrap();
        let root = resolve_install_root(false, None, &manifest, Path::new("/unused"));
        assert_eq!(root.canonicalize().unwrap(), tmp.path().canonicalize().unwrap());
    }

    #[test]
    fn install_payload_copies_then_skips_then_upgrades() {
        let tmp = tempfile::tempdir().unwrap();
        let (payload, root) = (tmp.path().join("payload"), tmp.path().join("app"));
        std::fs::create_dir_all(payload.join("coding_agent")).unwrap();
        std::fs::write(payload.join("run.sh"), "#!/bin/sh").unwrap();
        std::fs::write(payload.join("coding_agent").join("a.py"), "1").unwrap();
        assert!(install_payload(&payload, &root, "1").unwrap());
        assert!(root.join("coding_agent").join("a.py").is_file());
        assert!(!install_payload(&payload, &root, "1").unwrap(), "same version: no re-copy");
        std::fs::create_dir_all(root.join("dashboard").join("node_modules")).unwrap();
        std::fs::create_dir_all(root.join("dashboard").join(".next")).unwrap();
        assert!(install_payload(&payload, &root, "2").unwrap());
        assert!(root.join("dashboard").join("node_modules").is_dir(), "deps preserved across upgrade");
        assert!(!root.join("dashboard").join(".next").exists(), "stale build cleared on upgrade");
    }

    #[test]
    fn install_payload_errors_without_bundle() {
        let tmp = tempfile::tempdir().unwrap();
        assert!(install_payload(&tmp.path().join("nope"), &tmp.path().join("app"), "1").is_err());
    }
}
