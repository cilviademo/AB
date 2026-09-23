//! `spawn_worker` (EXECUTE 1.1): run one external process isolated.
//!
//! `spawn_worker(kind, args, timeout, env_allowlist, cwd_temp)` returns
//! `{pid, exit_code, stdout_path, stderr_path, timed_out, crash_dump}`.
//! Guarantees: a temporary working directory, a sanitized environment (only
//! the allow-list reaches the child), stdout/stderr captured to files under
//! the logs folder, a watchdog that kills the process tree on timeout, and on
//! Windows a Job Object with kill-on-close so orphaned threads die with the
//! worker. The Python engine has the same contract for the workers it drives
//! (`ab_engine.workers.run`); this one exists so the shell can start the
//! engine itself and any helper the UI needs without the engine.

use std::collections::HashMap;
use std::fs::File;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use serde::Serialize;

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;

pub const DEFAULT_ENV_ALLOWLIST: &[&str] = &[
    "PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATHEXT", "PROGRAMDATA",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "HOME", "LANG",
    "LC_ALL", "TZ", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "JAVA_HOME", "GHIDRA_INSTALL_DIR",
    "VST3_SDK_DIR", "LD_LIBRARY_PATH", "DISPLAY", "XDG_RUNTIME_DIR",
];

#[derive(Serialize, Clone, Debug)]
pub struct WorkerResult {
    pub kind: String,
    pub pid: Option<u32>,
    pub exit_code: Option<i32>,
    pub stdout_path: Option<String>,
    pub stderr_path: Option<String>,
    pub timed_out: bool,
    pub crash_dump: Option<String>,
    pub elapsed_ms: u64,
    pub error_code: Option<String>,
}

pub fn sanitized_env(allow: &[&str], extra: &HashMap<String, String>) -> HashMap<String, String> {
    let allowed: Vec<String> = allow.iter().map(|s| s.to_ascii_uppercase()).collect();
    let mut env: HashMap<String, String> = std::env::vars()
        .filter(|(k, _)| allowed.contains(&k.to_ascii_uppercase()))
        .collect();
    for (k, v) in extra {
        env.insert(k.clone(), v.clone());
    }
    env
}

fn kill_tree(pid: u32) {
    #[cfg(windows)]
    {
        let _ = Command::new("taskkill")
            .args(["/F", "/T", "/PID", &pid.to_string()])
            .creation_flags(CREATE_NO_WINDOW)
            .status();
    }
    #[cfg(not(windows))]
    {
        let _ = Command::new("kill").args(["-9", &format!("-{pid}")]).status();
        let _ = Command::new("kill").args(["-9", &pid.to_string()]).status();
    }
}

/// WER local dumps for a crashed worker (SPEC §16).
fn find_crash_dump(pid: u32, since: std::time::SystemTime) -> Option<String> {
    let local = std::env::var_os("LOCALAPPDATA")?;
    let dumps = PathBuf::from(local).join("CrashDumps");
    let entries = std::fs::read_dir(dumps).ok()?;
    let needle = format!(".{pid}.");
    for entry in entries.flatten() {
        let path = entry.path();
        let name = path.file_name()?.to_string_lossy().to_string();
        if name.ends_with(".dmp") && name.contains(&needle) {
            if let Ok(meta) = entry.metadata() {
                if meta.modified().map(|m| m >= since).unwrap_or(false) {
                    return Some(path.to_string_lossy().to_string());
                }
            }
        }
    }
    None
}

#[allow(clippy::too_many_arguments)]
pub fn spawn_worker(
    kind: &str,
    program: &Path,
    args: &[String],
    timeout: Duration,
    env_allowlist: &[&str],
    env_extra: &HashMap<String, String>,
    cwd_temp: Option<&Path>,
    logs: &Path,
) -> WorkerResult {
    let started = Instant::now();
    let since = std::time::SystemTime::now();
    let stamp = format!("{}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0));
    let _ = std::fs::create_dir_all(logs);
    let stdout_path = logs.join(format!("{kind}-{stamp}.stdout"));
    let stderr_path = logs.join(format!("{kind}-{stamp}.stderr"));

    let (out, err) = match (File::create(&stdout_path), File::create(&stderr_path)) {
        (Ok(o), Ok(e)) => (o, e),
        _ => {
            return WorkerResult { kind: kind.into(), pid: None, exit_code: None, stdout_path: None, stderr_path: None,
                timed_out: false, crash_dump: None, elapsed_ms: 0, error_code: Some("WORKER_FAILED".into()) }
        }
    };

    let temp_dir = cwd_temp.map(Path::to_path_buf).unwrap_or_else(|| {
        let d = std::env::temp_dir().join(format!("ab-{kind}-{}", std::process::id()));
        let _ = std::fs::create_dir_all(&d);
        d
    });

    let mut command = Command::new(program);
    command
        .args(args)
        .env_clear()
        .envs(sanitized_env(env_allowlist, env_extra))
        .current_dir(&temp_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::from(out))
        .stderr(Stdio::from(err));
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW | 0x0000_0200);

    let mut child = match command.spawn() {
        Ok(c) => c,
        Err(e) => {
            let _ = std::fs::write(&stderr_path, e.to_string());
            return WorkerResult { kind: kind.into(), pid: None, exit_code: None,
                stdout_path: Some(stdout_path.to_string_lossy().into()), stderr_path: Some(stderr_path.to_string_lossy().into()),
                timed_out: false, crash_dump: None, elapsed_ms: started.elapsed().as_millis() as u64,
                error_code: Some("WORKER_NOT_FOUND".into()) };
        }
    };
    let pid = child.id();
    #[cfg(windows)]
    let _job = job::assign(pid);

    let mut timed_out = false;
    let exit_code = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status.code(),
            Ok(None) => {
                if started.elapsed() >= timeout {
                    timed_out = true;
                    kill_tree(pid);
                    let _ = child.kill();
                    let _ = child.wait();
                    break None;
                }
                std::thread::sleep(Duration::from_millis(25));
            }
            Err(_) => break None,
        }
    };

    if cwd_temp.is_none() {
        let _ = std::fs::remove_dir_all(&temp_dir);
    }

    let crashed = !timed_out && exit_code.map(|c| c < 0 || (c as u32 & 0xC000_0000) == 0xC000_0000).unwrap_or(!timed_out);
    let error_code = if timed_out {
        Some(if kind == "vst3host" { "HOST_TIMEOUT".to_string() } else { "WORKER_FAILED".to_string() })
    } else if crashed {
        Some(match kind { "vst3host" => "PLUGIN_CRASH", "ghidra" => "GHIDRA_FAILED", _ => "WORKER_FAILED" }.to_string())
    } else {
        None
    };
    let crash_dump = if crashed { find_crash_dump(pid, since) } else { None };

    WorkerResult {
        kind: kind.into(),
        pid: Some(pid),
        exit_code,
        stdout_path: Some(stdout_path.to_string_lossy().into()),
        stderr_path: Some(stderr_path.to_string_lossy().into()),
        timed_out,
        crash_dump,
        elapsed_ms: started.elapsed().as_millis() as u64,
        error_code,
    }
}

/// Windows Job Object with kill-on-close: the child tree dies with this handle.
#[cfg(windows)]
mod job {
    use std::ffi::c_void;

    #[repr(C)]
    struct BasicLimit { per_process: i64, per_job: i64, flags: u32, min_ws: usize, max_ws: usize, active: u32, affinity: usize, prio: u32, sched: u32 }
    #[repr(C)]
    struct IoCounters { a: u64, b: u64, c: u64, d: u64, e: u64, f: u64 }
    #[repr(C)]
    struct ExtendedLimit { basic: BasicLimit, io: IoCounters, pm: usize, jm: usize, ppm: usize, pjm: usize }

    #[link(name = "kernel32")]
    extern "system" {
        fn CreateJobObjectW(attrs: *const c_void, name: *const u16) -> *mut c_void;
        fn SetInformationJobObject(job: *mut c_void, class: i32, info: *const c_void, len: u32) -> i32;
        fn OpenProcess(access: u32, inherit: i32, pid: u32) -> *mut c_void;
        fn AssignProcessToJobObject(job: *mut c_void, process: *mut c_void) -> i32;
        fn CloseHandle(handle: *mut c_void) -> i32;
    }

    pub struct Job(*mut c_void);
    impl Drop for Job {
        fn drop(&mut self) {
            unsafe { CloseHandle(self.0); }
        }
    }

    pub fn assign(pid: u32) -> Option<Job> {
        unsafe {
            let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if job.is_null() {
                return None;
            }
            let mut info: ExtendedLimit = std::mem::zeroed();
            info.basic.flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            SetInformationJobObject(job, 9, &info as *const _ as *const c_void, std::mem::size_of::<ExtendedLimit>() as u32);
            let process = OpenProcess(0x001F_0FFF, 0, pid);
            if !process.is_null() {
                AssignProcessToJobObject(job, process);
                CloseHandle(process);
            }
            Some(Job(job))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn env_is_sanitized() {
        std::env::set_var("AB_TEST_SECRET_TOKEN", "x");
        let env = sanitized_env(DEFAULT_ENV_ALLOWLIST, &HashMap::new());
        assert!(!env.contains_key("AB_TEST_SECRET_TOKEN"));
    }
}
