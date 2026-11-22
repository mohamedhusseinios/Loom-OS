use std::path::{Path, PathBuf};

const APP_DIR: &str = "LoomCodingAgent";

/// Root of LoomCodingAgent support data for the given OS ("macos", "linux", "windows").
pub fn support_root(home: &Path, os: &str) -> PathBuf {
    match os {
        "macos" => home.join("Library").join("Application Support").join(APP_DIR),
        "windows" => {
            let appdata = std::env::var_os("APPDATA").map(PathBuf::from).unwrap_or_else(|| home.join("AppData").join("Roaming"));
            appdata.join(APP_DIR)
        }
        _ => home.join(".local").join("share").join(APP_DIR),
    }
}

pub fn logs_dir(root: &Path) -> PathBuf {
    root.join("logs")
}

pub fn install_dir(root: &Path) -> PathBuf {
    root.join("app")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn support_root_mac() {
        let root = support_root(Path::new("/Users/me"), "macos");
        assert_eq!(root, PathBuf::from("/Users/me/Library/Application Support/LoomCodingAgent"));
    }

    #[test]
    fn support_root_linux() {
        let root = support_root(Path::new("/home/me"), "linux");
        assert_eq!(root, PathBuf::from("/home/me/.local/share/LoomCodingAgent"));
    }

    #[test]
    fn logs_and_install_dirs() {
        let root = PathBuf::from("/tmp/root");
        assert_eq!(logs_dir(&root), PathBuf::from("/tmp/root/logs"));
        assert_eq!(install_dir(&root), PathBuf::from("/tmp/root/app"));
    }
}
