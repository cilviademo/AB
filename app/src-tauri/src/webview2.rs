//! Is the Microsoft Edge WebView2 runtime installed? Without it the window
//! renders nothing at all, so the check runs before anything else.

pub const DOWNLOAD_URL: &str = "https://go.microsoft.com/fwlink/p/?LinkId=2124703";

#[cfg(windows)]
pub fn is_installed() -> bool {
    use winreg::enums::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE, KEY_READ, KEY_WOW64_32KEY};
    use winreg::RegKey;

    const CLIENTS: &str = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";
    let machine = RegKey::predef(HKEY_LOCAL_MACHINE).open_subkey_with_flags(CLIENTS, KEY_READ | KEY_WOW64_32KEY);
    let user = RegKey::predef(HKEY_CURRENT_USER).open_subkey(CLIENTS);
    for key in [machine, user].into_iter().flatten() {
        if let Ok(version) = key.get_value::<String, _>("pv") {
            if !version.is_empty() && version != "0.0.0.0" {
                return true;
            }
        }
    }
    false
}

#[cfg(not(windows))]
pub fn is_installed() -> bool {
    true
}

#[cfg(windows)]
pub fn warn_and_exit() -> ! {
    use std::os::windows::process::CommandExt;
    use std::process::Command;

    let message = format!(
        "AB needs the Microsoft Edge WebView2 runtime, which is not installed on this computer.\n\nInstall it from:\n{DOWNLOAD_URL}\n\nThen start AB again."
    );
    let script = format!(
        "javascript:var s=new ActiveXObject('WScript.Shell');s.Popup(\"{}\",0,\"AB\",0x30);close()",
        message.replace('"', "'").replace('\n', "\\n")
    );
    let _ = Command::new("mshta").arg(script).creation_flags(0x0800_0000).status();
    std::process::exit(1);
}

#[cfg(not(windows))]
pub fn warn_and_exit() -> ! {
    eprintln!("A system webview is required.");
    std::process::exit(1);
}
