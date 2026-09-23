//! The long-lived AB engine process and the stdio protocol it speaks.
//!
//! One child for the session. Requests are JSON lines on stdin; responses
//! and progress events are JSON lines on stdout, correlated by `id`. A reader
//! thread parses every line into a channel so every wait has a real timeout:
//! an engine that stops answering must look different from one that is slow.

use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::time::{Duration, Instant};

use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};

use crate::paths::Paths;

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

pub const PING_TIMEOUT: Duration = Duration::from_secs(15);
/// Long enough for a Ghidra pass on a 50 MB binary.
pub const REQUEST_TIMEOUT: Duration = Duration::from_secs(60 * 60);

#[derive(Serialize, Clone)]
struct Progress {
    id: u64,
    stage: String,
    status: String,
    detail: String,
    extra: Value,
}

pub struct Core {
    child: Child,
    stdin: ChildStdin,
    lines: Receiver<Value>,
    next_id: u64,
    pub executable: PathBuf,
    pub version: String,
}

impl Core {
    pub fn start(paths: &Paths, resource_dir: Option<PathBuf>) -> Result<Self, String> {
        let launch = Launch::resolve(resource_dir)?;

        #[cfg(windows)]
        if launch.args.is_empty() {
            crate::pe::check_runnable(&launch.program, "The AB engine")?;
        }

        let mut command = Command::new(&launch.program);
        command
            .args(&launch.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
            .env("AB_HOME", &paths.home)
            .env("AB_STATE", &paths.state)
            .env("AB_SAFE_MODE", if crate::paths::safe_mode_requested() { "1" } else { "0" });
        if let Some(dir) = &launch.working_dir {
            command.current_dir(dir);
        }
        if let Some(bin) = &launch.bin_dir {
            command.env("AB_BIN", bin);
        }
        #[cfg(windows)]
        command.creation_flags(CREATE_NO_WINDOW);

        let mut child = command
            .spawn()
            .map_err(|e| format!("Could not start the AB engine ({}): {e}", launch.program.display()))?;
        let stdin = child.stdin.take().ok_or("the engine gave no stdin")?;
        let stdout = child.stdout.take().ok_or("the engine gave no stdout")?;

        let (tx, lines) = mpsc::channel();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                if let Ok(value) = serde_json::from_str::<Value>(&line) {
                    if tx.send(value).is_err() {
                        break;
                    }
                }
            }
        });
        if let Some(errors) = child.stderr.take() {
            std::thread::spawn(move || {
                for line in BufReader::new(errors).lines().map_while(Result::ok) {
                    eprintln!("[engine] {line}");
                }
            });
        }

        let mut core = Core { child, stdin, lines, next_id: 1, executable: launch.program, version: String::new() };
        let reply = core
            .request(None, "ping", json!({}), PING_TIMEOUT)
            .map_err(|e| format!("The AB engine did not answer: {e}"))?;
        core.version = reply
            .pointer("/data/version")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        Ok(core)
    }

    /// Send one request; relay `progress` events as `job-progress` window events.
    pub fn request(&mut self, app: Option<&AppHandle>, method: &str, params: Value, timeout: Duration) -> Result<Value, String> {
        let id = self.next_id;
        self.next_id += 1;
        let line = json!({ "id": id, "method": method, "params": params });
        writeln!(self.stdin, "{line}").map_err(|e| format!("could not write to the engine: {e}"))?;
        self.stdin.flush().map_err(|e| format!("could not flush to the engine: {e}"))?;

        let deadline = Instant::now() + timeout;
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(format!("no response to {method} within {timeout:?}"));
            }
            match self.lines.recv_timeout(remaining) {
                Ok(value) => {
                    if value.get("id").and_then(Value::as_u64) != Some(id) {
                        continue;
                    }
                    if value.get("event").and_then(Value::as_str) == Some("progress") {
                        if let Some(handle) = app {
                            let mut extra = value.clone();
                            if let Some(obj) = extra.as_object_mut() {
                                for k in ["id", "event", "stage", "status", "detail"] {
                                    obj.remove(k);
                                }
                            }
                            let _ = handle.emit("job-progress", Progress {
                                id,
                                stage: string_at(&value, "stage"),
                                status: string_at(&value, "status"),
                                detail: string_at(&value, "detail"),
                                extra,
                            });
                        }
                        continue;
                    }
                    return Ok(value);
                }
                Err(RecvTimeoutError::Timeout) => return Err(format!("no response to {method} within {timeout:?}")),
                Err(RecvTimeoutError::Disconnected) => return Err("the AB engine stopped unexpectedly".to_string()),
            }
        }
    }

    pub fn shutdown(&mut self) {
        let _ = writeln!(self.stdin, "{}", json!({ "id": 0, "method": "shutdown" }));
        let _ = self.stdin.flush();
        std::thread::sleep(Duration::from_millis(120));
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for Core {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn string_at(value: &Value, key: &str) -> String {
    value.get(key).and_then(Value::as_str).unwrap_or_default().to_string()
}

struct Launch {
    program: PathBuf,
    args: Vec<String>,
    working_dir: Option<PathBuf>,
    bin_dir: Option<PathBuf>,
}

impl Launch {
    fn resolve(resource_dir: Option<PathBuf>) -> Result<Self, String> {
        let (found, tried) = packaged_engine(resource_dir.as_deref());
        if let Some(found) = found {
            let bin_dir = found.parent().and_then(|p| p.parent()).map(|p| p.join("bin"));
            return Ok(Launch { program: found, args: vec![], working_dir: None, bin_dir: bin_dir.filter(|p| p.is_dir()) });
        }
        let searched = tried.iter().map(|p| format!("  {}", p.display())).collect::<Vec<_>>().join("\n");

        // A release never reaches for a Python on the user's machine: the
        // run-from-source path is compiled only into debug builds.
        #[cfg(debug_assertions)]
        {
            if let Some(root) = repo_root() {
                if let Some(python) = interpreter(&root) {
                    return Ok(Launch {
                        program: python,
                        args: vec!["-m".into(), "ab_engine".into()],
                        working_dir: Some(root.join("engine")),
                        bin_dir: None,
                    });
                }
            }
        }

        Err(format!(
            "Could not find the AB engine.\n\nIt ships under resources/ab-engine, beside AB.exe. If you moved or extracted only part of the folder, extract it again and keep it together. Looked in:\n{searched}\n\nSet AB_ENGINE_EXE to the executable to override this search."
        ))
    }
}

fn engine_exe_name() -> &'static str {
    if cfg!(windows) { "ab-engine.exe" } else { "ab-engine" }
}

fn resource_roots(resource_dir: Option<&Path>) -> Vec<PathBuf> {
    let mut roots: Vec<PathBuf> = Vec::new();
    if let Some(dir) = resource_dir {
        roots.push(dir.to_path_buf());
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            roots.push(parent.to_path_buf());
            if let Some(grandparent) = parent.parent() {
                roots.push(grandparent.to_path_buf());
            }
        }
    }
    roots.dedup();
    roots
}

fn packaged_engine(resource_dir: Option<&Path>) -> (Option<PathBuf>, Vec<PathBuf>) {
    let mut tried: Vec<PathBuf> = Vec::new();
    let exe_name = engine_exe_name();
    if let Ok(explicit) = std::env::var("AB_ENGINE_EXE") {
        let candidate = PathBuf::from(explicit);
        tried.push(candidate.clone());
        if candidate.is_file() {
            return (Some(candidate), tried);
        }
    }
    let relatives = ["resources/ab-engine", "ab-engine", "resources/ab-engine/ab-engine", "resources"];
    for root in resource_roots(resource_dir) {
        for relative in relatives {
            let candidate = root.join(relative).join(exe_name);
            tried.push(candidate.clone());
            if candidate.is_file() {
                return (Some(candidate), tried);
            }
        }
        if let Some(found) = search_for(&root, exe_name, 3) {
            return (Some(found), tried);
        }
    }
    (None, tried)
}

fn search_for(root: &Path, name: &str, depth: usize) -> Option<PathBuf> {
    if depth == 0 {
        return None;
    }
    let entries = std::fs::read_dir(root).ok()?;
    let mut directories: Vec<PathBuf> = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        match entry.file_type() {
            Ok(kind) if kind.is_file() => {
                if path.file_name().and_then(|n| n.to_str()) == Some(name) {
                    return Some(path);
                }
            }
            Ok(kind) if kind.is_dir() => directories.push(path),
            _ => {}
        }
    }
    for directory in directories {
        if let Some(found) = search_for(&directory, name, depth - 1) {
            return Some(found);
        }
    }
    None
}

/// Walk upwards for the checkout that holds `engine/ab_engine/__main__.py`.
#[cfg(debug_assertions)]
fn repo_root() -> Option<PathBuf> {
    for start in [std::env::current_exe().ok(), std::env::current_dir().ok()].into_iter().flatten() {
        let mut current = Some(start.as_path());
        while let Some(dir) = current {
            if dir.join("engine/ab_engine/__main__.py").is_file() && dir.join("engine/pyproject.toml").is_file() {
                return Some(dir.to_path_buf());
            }
            current = dir.parent();
        }
    }
    None
}

#[cfg(debug_assertions)]
fn interpreter(root: &Path) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(explicit) = std::env::var("AB_PYTHON") {
        candidates.push(PathBuf::from(explicit));
    }
    candidates.push(root.join("engine/.venv/Scripts/python.exe"));
    candidates.push(root.join("engine/.venv/bin/python"));
    candidates.push(PathBuf::from("python"));
    candidates.push(PathBuf::from("python3"));
    for candidate in candidates {
        let mut probe = Command::new(&candidate);
        probe.arg("-c").arg("import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)");
        #[cfg(windows)]
        probe.creation_flags(CREATE_NO_WINDOW);
        if let Ok(status) = probe.status() {
            if status.success() {
                return Some(candidate);
            }
        }
    }
    None
}
