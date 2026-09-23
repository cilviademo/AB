//! Where AB reads and writes on this machine.
//!
//! Two roots, decided here and handed to the engine through the environment so
//! there is exactly one place that knows the policy (mirrors Prosody):
//!
//! * home  — `Documents\AB` (or `%USERPROFILE%\AB` when Documents is inside a
//!   sync client's folder): the user's recovery projects and exports
//! * state — `%LOCALAPPDATA%\AB`: jobs.db, objects/, knowledge/, tools/, logs/
//!
//! Portable mode collapses both into `Data\` beside the executable.

use std::path::{Path, PathBuf};

pub const APP_DIR: &str = "AB";
pub const PORTABLE_FLAG: &str = "portable.flag";

#[derive(Debug, Clone)]
pub struct Paths {
    pub home: PathBuf,
    pub state: PathBuf,
    pub portable: bool,
}

impl Paths {
    pub fn resolve() -> Self {
        if let Some(dir) = portable_data_dir() {
            return Paths { home: dir.clone(), state: dir, portable: true };
        }
        Paths { home: user_root(&documents_dir()), state: state_dir().join(APP_DIR), portable: false }
    }

    pub fn logs(&self) -> PathBuf {
        self.state.join("logs")
    }

    pub fn ensure(&self) -> std::io::Result<()> {
        for dir in [self.home.join("Projects"), self.home.join("Exports"), self.state.join("tmp"), self.logs()] {
            std::fs::create_dir_all(dir)?;
        }
        Ok(())
    }
}

pub fn portable_data_dir() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;
    if dir.join(PORTABLE_FLAG).is_file() {
        return Some(dir.join("Data"));
    }
    None
}

fn documents_dir() -> PathBuf {
    #[cfg(windows)]
    {
        if let Ok(profile) = std::env::var("USERPROFILE") {
            return PathBuf::from(profile).join("Documents");
        }
    }
    home().join("Documents")
}

fn state_dir() -> PathBuf {
    #[cfg(windows)]
    {
        if let Ok(local) = std::env::var("LOCALAPPDATA") {
            return PathBuf::from(local);
        }
        return home().join("AppData").join("Local");
    }
    #[cfg(target_os = "macos")]
    {
        return home().join("Library").join("Application Support");
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        if let Ok(xdg) = std::env::var("XDG_DATA_HOME") {
            return PathBuf::from(xdg);
        }
        home().join(".local").join("share")
    }
}

fn home() -> PathBuf {
    #[cfg(windows)]
    {
        if let Ok(profile) = std::env::var("USERPROFILE") {
            return PathBuf::from(profile);
        }
    }
    std::env::var("HOME").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("."))
}

/// `--safe`, a `safemode.flag` beside the executable: inspect only, never write
/// or spawn a worker. The whole process tree agrees via the environment.
pub fn safe_mode_requested() -> bool {
    if std::env::args().any(|a| a == "--safe" || a == "/safe") {
        return true;
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            if dir.join("safemode.flag").exists() {
                return true;
            }
        }
    }
    false
}

/// `<documents>/AB`, unless Documents is inside a sync client's folder: bundles
/// are large and sync clients lock files they upload. The engine applies the
/// same rule (`workspace.default_home`); the two must agree.
pub fn user_root(documents: &Path) -> PathBuf {
    let sync_roots: Vec<PathBuf> = ["OneDrive", "OneDriveConsumer", "OneDriveCommercial"]
        .iter()
        .filter_map(|var| std::env::var_os(var).map(PathBuf::from))
        .collect();
    if is_cloud_synced(documents, &sync_roots) {
        return home().join(APP_DIR);
    }
    documents.join(APP_DIR)
}

pub fn is_cloud_synced(path: &Path, sync_roots: &[PathBuf]) -> bool {
    let lower = path.to_string_lossy().to_lowercase();
    if sync_roots.iter().any(|root| {
        let r = root.to_string_lossy().to_lowercase();
        !r.is_empty() && lower.starts_with(&r)
    }) {
        return true;
    }
    lower.split(['\\', '/']).any(|part| part.starts_with("onedrive") || part == "dropbox")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redirected_documents_is_recognised() {
        let roots = vec![PathBuf::from("C:\\Users\\m\\OneDrive")];
        assert!(is_cloud_synced(Path::new("C:\\Users\\m\\OneDrive\\Documents"), &roots));
        assert!(!is_cloud_synced(Path::new("C:\\Users\\m\\Documents"), &roots));
        assert!(is_cloud_synced(Path::new("/Users/x/Dropbox/Documents"), &[]));
    }
}
