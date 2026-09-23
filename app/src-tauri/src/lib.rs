//! AB desktop shell.
//!
//! The window is a thin orchestrator: it resolves where files live, starts
//! the engine and completes the ping handshake, forwards API calls, relays
//! progress events, and does the few things a browser cannot: pick files,
//! reveal a folder, open a project in an editor, read a bundle file for the
//! evidence viewer. It never loads a plugin.
//!
//! Startup order is fixed: WebView2 check → portable-mode check → create
//! folders → start the engine and ping it. A failure at the last step leaves
//! the window up with a diagnostics payload rather than a blank frame.

mod core;
mod paths;
mod pe;
mod webview2;
mod worker;

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Duration;

use serde::Serialize;
use serde_json::{json, Value};
use tauri::{Manager, State};
use tauri_plugin_opener as opener;

use crate::core::{Core, REQUEST_TIMEOUT};
use crate::paths::Paths;

const MIN_WIDTH: f64 = 920.0;
const MIN_HEIGHT: f64 = 620.0;
const TITLE_BAR_GRAB: f64 = 80.0;

struct AppState {
    paths: Paths,
    core: Mutex<Option<Core>>,
    startup_error: Mutex<Option<String>>,
    core_version: Mutex<String>,
}

#[derive(Serialize)]
struct Status {
    ok: bool,
    portable: bool,
    safe_mode: bool,
    home: String,
    state: String,
    logs: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    core_version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    core_executable: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

/// Call an engine method. Progress lines are emitted as `job-progress` events.
#[tauri::command]
async fn api(app: tauri::AppHandle, state: State<'_, AppState>, method: String, payload: Value) -> Result<Value, String> {
    let mut guard = state.core.lock().map_err(|_| "the engine connection is poisoned".to_string())?;
    let core = guard.as_mut().ok_or_else(|| {
        state.startup_error.lock().ok().and_then(|e| e.clone()).unwrap_or_else(|| "The AB engine is not running.".to_string())
    })?;
    match core.request(Some(&app), &method, payload, REQUEST_TIMEOUT) {
        Ok(value) => Ok(value),
        Err(message) => {
            *state.startup_error.lock().unwrap() = Some(message.clone());
            *guard = None;
            Err(message)
        }
    }
}

#[tauri::command]
fn backend_status(state: State<'_, AppState>) -> Status {
    let running = state.core.lock().map(|c| c.is_some()).unwrap_or(false);
    let error = state.startup_error.lock().ok().and_then(|e| e.clone());
    let version = state.core_version.lock().ok().map(|v| v.clone()).filter(|v| !v.is_empty());
    let executable = state.core.lock().ok().and_then(|c| c.as_ref().map(|core| core.executable.to_string_lossy().into_owned()));
    Status {
        ok: running,
        portable: state.paths.portable,
        safe_mode: paths::safe_mode_requested(),
        home: state.paths.home.to_string_lossy().into_owned(),
        state: state.paths.state.to_string_lossy().into_owned(),
        logs: state.paths.logs().to_string_lossy().into_owned(),
        core_version: version,
        core_executable: executable,
        error,
    }
}

#[tauri::command]
async fn restart_core(state: State<'_, AppState>) -> Result<Status, String> {
    {
        let mut guard = state.core.lock().map_err(|_| "poisoned".to_string())?;
        if let Some(mut existing) = guard.take() {
            existing.shutdown();
        }
    }
    let paths = state.paths.clone();
    let started = tauri::async_runtime::spawn_blocking(move || Core::start(&paths, None)).await.map_err(|e| e.to_string())?;
    match started {
        Ok(core) => {
            *state.core_version.lock().unwrap() = core.version.clone();
            *state.startup_error.lock().unwrap() = None;
            *state.core.lock().unwrap() = Some(core);
        }
        Err(message) => {
            *state.startup_error.lock().unwrap() = Some(message.clone());
            return Err(message);
        }
    }
    Ok(backend_status(state))
}

/// Reveal a file or folder in the system file manager.
#[tauri::command]
fn reveal(path: String) -> Result<(), String> {
    let target = PathBuf::from(&path);
    if !target.exists() {
        return Err(format!("{path} no longer exists."));
    }
    if target.is_file() {
        opener::reveal_item_in_dir(&target).map_err(|e| e.to_string())
    } else {
        opener::open_path(target.to_string_lossy().to_string(), None::<&str>).map_err(|e| e.to_string())
    }
}

/// Open an exported project in the user's editor (VS Code when present, else
/// the shell's handler for the folder). No interpreter, no shell syntax.
#[tauri::command]
fn open_in_editor(path: String) -> Result<(), String> {
    let target = PathBuf::from(&path);
    if !target.is_dir() {
        return Err(format!("{path} is not a folder."));
    }
    let code = if cfg!(windows) { "code.cmd" } else { "code" };
    let mut command = std::process::Command::new(code);
    command.arg(&target);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(worker::CREATE_NO_WINDOW);
    }
    if command.spawn().is_ok() {
        return Ok(());
    }
    opener::open_path(target.to_string_lossy().to_string(), None::<&str>).map_err(|e| e.to_string())
}

/// Read a file inside the user's AB home for the evidence viewer. Refuses
/// anything outside `home` or `state` so the webview never becomes a file reader.
#[tauri::command]
fn read_bundle_file(state: State<'_, AppState>, path: String, max_bytes: Option<u64>) -> Result<Vec<u8>, String> {
    let target = PathBuf::from(&path);
    let canonical = target.canonicalize().map_err(|e| format!("{path}: {e}"))?;
    let allowed = [&state.paths.home, &state.paths.state]
        .iter()
        .filter_map(|p| p.canonicalize().ok())
        .any(|root| canonical.starts_with(&root));
    if !allowed {
        return Err(format!("{path} is outside the AB folders."));
    }
    let size = std::fs::metadata(&canonical).map_err(|e| e.to_string())?.len();
    let limit = max_bytes.unwrap_or(64 * 1024 * 1024);
    if size > limit {
        return Err(format!("This file is {size} bytes; the viewer reads at most {limit}."));
    }
    std::fs::read(&canonical).map_err(|e| e.to_string())
}

/// `spawn_worker` exposed to the UI for non-plugin helpers only (EXECUTE 1.1).
/// The engine drives every plugin-touching worker itself; the webview may not
/// name arbitrary programs — only kinds the shell knows how to locate.
#[tauri::command]
fn spawn_worker(state: State<'_, AppState>, kind: String, args: Vec<String>, timeout_secs: Option<u64>) -> Result<worker::WorkerResult, String> {
    let program = match kind.as_str() {
        "node" => which("node").ok_or("node is not available")?,
        "code" => which(if cfg!(windows) { "code.cmd" } else { "code" }).ok_or("VS Code is not available")?,
        other => return Err(format!("the shell does not spawn workers of kind {other}; ask the engine")),
    };
    let timeout = Duration::from_secs(timeout_secs.unwrap_or(600));
    Ok(worker::spawn_worker(&kind, &program, &args, timeout, worker::DEFAULT_ENV_ALLOWLIST, &HashMap::new(), None, &state.paths.logs()))
}

fn which(name: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path) {
        let candidate = dir.join(name);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

fn restore_window(window: &tauri::WebviewWindow, saved: &Value) {
    use tauri::{LogicalPosition, LogicalSize};
    let Some(geometry) = saved.get("window") else { return };
    let number = |key: &str| geometry.get(key).and_then(Value::as_f64);
    let (Some(width), Some(height)) = (number("width"), number("height")) else { return };
    let monitors = window.available_monitors().unwrap_or_default();
    let smallest = monitors
        .iter()
        .map(|m| { let s = m.scale_factor(); (m.size().width as f64 / s, m.size().height as f64 / s) })
        .fold((f64::MAX, f64::MAX), |acc, wh| (acc.0.min(wh.0), acc.1.min(wh.1)));
    let (max_w, max_h) = if smallest.0 == f64::MAX { (f64::MAX, f64::MAX) } else { smallest };
    let width = width.clamp(MIN_WIDTH, max_w);
    let height = height.clamp(MIN_HEIGHT, max_h);
    let _ = window.set_size(LogicalSize::new(width, height));
    let (Some(x), Some(y)) = (number("x"), number("y")) else { return };
    let visible = monitors.iter().any(|m| {
        let s = m.scale_factor();
        let (mx, my) = (m.position().x as f64 / s, m.position().y as f64 / s);
        let (mw, mh) = (m.size().width as f64 / s, m.size().height as f64 / s);
        let overlap_w = (x + width).min(mx + mw) - x.max(mx);
        let overlap_h = (y + height).min(my + mh) - y.max(my);
        overlap_w >= TITLE_BAR_GRAB && overlap_h >= TITLE_BAR_GRAB
    });
    if visible {
        let _ = window.set_position(LogicalPosition::new(x, y));
    } else {
        let _ = window.center();
    }
}

#[tauri::command]
async fn save_window(state: State<'_, AppState>, width: f64, height: f64, x: i32, y: i32) -> Result<(), String> {
    let mut guard = state.core.lock().map_err(|_| "poisoned".to_string())?;
    if let Some(core) = guard.as_mut() {
        let params = json!({ "settings": { "window": { "width": width, "height": height, "x": x, "y": y } } });
        let _ = core.request(None, "settings.set", params, Duration::from_secs(10));
    }
    Ok(())
}

pub fn run() {
    if !webview2::is_installed() {
        webview2::warn_and_exit();
    }
    let paths = Paths::resolve();
    if let Err(e) = paths.ensure() {
        eprintln!("could not create application folders: {e}");
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(move |app| {
            let resource_dir = app.path().resource_dir().ok();
            let (mut core, version, error) = match Core::start(&paths, resource_dir) {
                Ok(core) => { let v = core.version.clone(); (Some(core), v, None) }
                Err(message) => (None, String::new(), Some(message)),
            };
            if let (Some(core), Some(window)) = (core.as_mut(), app.get_webview_window("main")) {
                if let Ok(settings) = core.request(None, "settings.get", json!({}), Duration::from_secs(5)) {
                    restore_window(&window, settings.get("data").unwrap_or(&settings));
                }
            }
            app.manage(AppState {
                paths: paths.clone(),
                core: Mutex::new(core),
                startup_error: Mutex::new(error),
                core_version: Mutex::new(version),
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            api, backend_status, restart_core, reveal, open_in_editor, read_bundle_file, spawn_worker, save_window
        ])
        .run(tauri::generate_context!())
        .expect("error while running AB");
}

#[allow(dead_code)]
fn _unused(_: &Path) {}
