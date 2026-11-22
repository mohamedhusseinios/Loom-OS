use std::fs;
use std::path::{Path, PathBuf};

#[cfg(unix)]
const SEP: char = ':';
#[cfg(not(unix))]
const SEP: char = ';';

/// Numeric sort key for directory names like `v22.10.1`.
fn version_key(name: &str) -> Vec<u64> {
    name.trim_start_matches('v').split('.').map(|p| p.parse().unwrap_or(0)).collect()
}

/// Bin dir of the highest-versioned child of `parent`, i.e. `parent/<latest>/<suffix>`.
fn latest_version_bin(parent: &Path, suffix: &str) -> Option<PathBuf> {
    let mut versions: Vec<(Vec<u64>, PathBuf)> = fs::read_dir(parent)
        .ok()?
        .flatten()
        .filter_map(|e| {
            let bin = e.path().join(suffix);
            bin.is_dir().then(|| (version_key(&e.file_name().to_string_lossy()), bin))
        })
        .collect();
    versions.sort();
    versions.pop().map(|(_, bin)| bin)
}

fn candidate_dirs(home: &Path) -> Vec<PathBuf> {
    let mut dirs: Vec<PathBuf> = ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin"].iter().map(PathBuf::from).collect();
    for ver in ["24", "22", "20"] {
        dirs.push(PathBuf::from(format!("/opt/homebrew/opt/node@{ver}/bin")));
        dirs.push(PathBuf::from(format!("/usr/local/opt/node@{ver}/bin")));
    }
    dirs.push(home.join(".hermes/node/bin"));
    dirs.push(home.join(".local/bin"));
    dirs.push(home.join(".bun/bin"));
    dirs.extend(latest_version_bin(&home.join(".nvm/versions/node"), "bin"));
    dirs.extend(latest_version_bin(&home.join(".fnm/node-versions"), "installation/bin"));
    dirs
}

/// Merge: existing candidate dirs first (in order), then `env_path`, then `shell_path`; deduplicated.
fn build_path(env_path: &str, home: &Path, shell_path: Option<&str>) -> String {
    let mut out: Vec<String> = Vec::new();
    let mut push = |entry: &str| {
        if !entry.is_empty() && !out.iter().any(|e| e == entry) {
            out.push(entry.to_string());
        }
    };
    for dir in candidate_dirs(home).into_iter().filter(|d| d.is_dir()) {
        push(&dir.to_string_lossy());
    }
    env_path.split(SEP).for_each(&mut push);
    if let Some(sp) = shell_path {
        sp.split(SEP).for_each(&mut push);
    }
    out.join(&SEP.to_string())
}

/// PATH reported by a login shell (`zsh -lc`, falling back to bash), with a timeout.
#[cfg(unix)]
fn login_shell_path() -> Option<String> {
    use std::io::Read;
    use std::process::{Command, Stdio};
    use std::time::{Duration, Instant};

    for shell in ["/bin/zsh", "/bin/bash"] {
        if !Path::new(shell).exists() {
            continue;
        }
        let Ok(mut child) = Command::new(shell).args(["-lc", "printf %s \"$PATH\""]).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null()).spawn() else {
            continue;
        };
        let deadline = Instant::now() + Duration::from_secs(5);
        let status = loop {
            match child.try_wait() {
                Ok(Some(s)) => break Some(s),
                Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(25)),
                _ => {
                    let _ = child.kill();
                    let _ = child.wait();
                    break None;
                }
            }
        };
        if status.is_some_and(|s| s.success()) {
            let mut buf = String::new();
            if child.stdout.take()?.read_to_string(&mut buf).is_ok() && !buf.trim().is_empty() {
                return Some(buf.trim().to_string());
            }
        }
    }
    None
}

#[cfg(not(unix))]
fn login_shell_path() -> Option<String> {
    None
}

/// Build a GUI-friendly PATH: toolchain dirs prepended, login-shell PATH appended.
pub fn bootstrap_path(env_path: &str, home: &Path) -> String {
    build_path(env_path, home, login_shell_path().as_deref())
}

/// Set the process-wide `PATH`.
pub fn apply_path_to_process(path: &str) {
    // SAFETY: called once at startup before any worker threads read the environment.
    unsafe { std::env::set_var("PATH", path) };
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mkdir(p: &Path) {
        fs::create_dir_all(p).unwrap();
    }

    fn entries(path: &str) -> Vec<String> {
        path.split(':').map(String::from).collect()
    }

    fn pos(list: &[String], needle: &Path) -> usize {
        let needle = needle.to_string_lossy().to_string();
        list.iter().position(|e| *e == needle).unwrap_or_else(|| panic!("{needle} missing from {list:?}"))
    }

    #[test]
    fn prepends_home_dirs_in_order_and_picks_latest_nvm_fnm() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        let hermes = home.join(".hermes/node/bin");
        let local = home.join(".local/bin");
        let bun = home.join(".bun/bin");
        let nvm_old = home.join(".nvm/versions/node/v18.20.0/bin");
        let nvm_new = home.join(".nvm/versions/node/v22.10.1/bin");
        let nvm_mid = home.join(".nvm/versions/node/v20.9.0/bin");
        let fnm_old = home.join(".fnm/node-versions/v18.0.0/installation/bin");
        let fnm_new = home.join(".fnm/node-versions/v20.11.0/installation/bin");
        for d in [&hermes, &local, &bun, &nvm_old, &nvm_new, &nvm_mid, &fnm_old, &fnm_new] {
            mkdir(d);
        }

        let out = entries(&build_path("", home, None));
        assert!(pos(&out, &hermes) < pos(&out, &local));
        assert!(pos(&out, &local) < pos(&out, &bun));
        assert!(pos(&out, &bun) < pos(&out, &nvm_new));
        assert!(pos(&out, &nvm_new) < pos(&out, &fnm_new));
        assert!(!out.contains(&nvm_old.to_string_lossy().to_string()));
        assert!(!out.contains(&nvm_mid.to_string_lossy().to_string()));
        assert!(!out.contains(&fnm_old.to_string_lossy().to_string()));
        assert!(!out.iter().any(|e| e.is_empty()));
    }

    #[test]
    fn skips_missing_dirs() {
        let tmp = tempfile::tempdir().unwrap();
        let out = build_path("/usr/bin", tmp.path(), None);
        assert!(!out.contains(".bun"));
        assert!(!out.contains(".nvm"));
        assert!(out.ends_with("/usr/bin"));
    }

    #[test]
    fn appends_login_shell_path_without_dropping_or_duplicating() {
        let tmp = tempfile::tempdir().unwrap();
        let out = entries(&build_path("/usr/bin:/bin", tmp.path(), Some("/bin:/custom/bin:/usr/bin")));
        // system toolchain dirs may be prepended depending on host; the tail is deterministic
        assert_eq!(out[out.len() - 3..], ["/usr/bin", "/bin", "/custom/bin"]);
        assert_eq!(out.iter().filter(|e| *e == "/usr/bin").count(), 1);
    }

    #[test]
    fn existing_entries_not_duplicated_when_prefix_dir_present() {
        let tmp = tempfile::tempdir().unwrap();
        let local = tmp.path().join(".local/bin");
        mkdir(&local);
        let env = format!("/usr/bin:{}", local.display());
        let out = entries(&build_path(&env, tmp.path(), None));
        assert_eq!(out.iter().filter(|e| **e == local.to_string_lossy()).count(), 1);
        assert!(pos(&out, &local) < pos(&out, Path::new("/usr/bin")));
    }

    #[test]
    fn bootstrap_path_keeps_original_entries() {
        let tmp = tempfile::tempdir().unwrap();
        let out = bootstrap_path("/some/original/bin", tmp.path());
        assert!(entries(&out).contains(&"/some/original/bin".to_string()));
    }
}
