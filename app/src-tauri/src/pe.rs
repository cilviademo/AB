//! Reading the machine type out of a Windows PE header.
//!
//! Every binary the shell spawns (the packaged engine, `vst3host.exe`) is
//! checked first: a Linux build staged into the Windows resource folder fails
//! at spawn time with "%1 is not a valid Win32 application", which names
//! neither the file nor the cause. Two header fields say exactly what is wrong.
//! Plugins are never checked here because the shell never loads plugins.

#![cfg_attr(not(windows), allow(dead_code))]

use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;

const MACHINE_AMD64: u16 = 0x8664;
const MACHINE_ARM64: u16 = 0xAA64;
const MACHINE_I386: u16 = 0x014C;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Machine {
    X64,
    Arm64,
    X86,
    Other(u16),
}

impl Machine {
    pub fn label(self) -> String {
        match self {
            Machine::X64 => "64-bit (x64)".to_string(),
            Machine::Arm64 => "64-bit (ARM64)".to_string(),
            Machine::X86 => "32-bit (x86)".to_string(),
            Machine::Other(v) => format!("unrecognised machine type 0x{v:04X}"),
        }
    }

    pub fn runnable_here(self) -> bool {
        matches!(self, Machine::X64 | Machine::Arm64)
    }
}

pub fn machine_type(path: &Path) -> Result<Machine, String> {
    let mut file = File::open(path).map_err(|e| format!("could not read {}: {e}", path.display()))?;
    let mut dos = [0u8; 2];
    file.read_exact(&mut dos).map_err(|_| "file is too short to be a program".to_string())?;
    if &dos != b"MZ" {
        return Err(describe_foreign(&dos, path));
    }
    file.seek(SeekFrom::Start(0x3C)).map_err(|e| e.to_string())?;
    let mut offset_bytes = [0u8; 4];
    file.read_exact(&mut offset_bytes).map_err(|_| "no PE header offset".to_string())?;
    let offset = u32::from_le_bytes(offset_bytes) as u64;
    file.seek(SeekFrom::Start(offset)).map_err(|e| e.to_string())?;
    let mut signature = [0u8; 4];
    file.read_exact(&mut signature).map_err(|_| "no PE signature".to_string())?;
    if &signature != b"PE\0\0" {
        return Err("not a Windows program (no PE signature)".to_string());
    }
    let mut machine = [0u8; 2];
    file.read_exact(&mut machine).map_err(|_| "truncated PE header".to_string())?;
    Ok(match u16::from_le_bytes(machine) {
        MACHINE_AMD64 => Machine::X64,
        MACHINE_ARM64 => Machine::Arm64,
        MACHINE_I386 => Machine::X86,
        other => Machine::Other(other),
    })
}

fn describe_foreign(magic: &[u8; 2], path: &Path) -> String {
    let name = path.file_name().unwrap_or_default().to_string_lossy();
    if magic == b"\x7fE" {
        format!("{name} is a Linux (ELF) binary, not a Windows program - the build staged the wrong file")
    } else if magic == b"#!" {
        format!("{name} is a script, not a Windows program")
    } else {
        format!("{name} is not a Windows program")
    }
}

pub fn check_runnable(path: &Path, role: &str) -> Result<Machine, String> {
    match machine_type(path) {
        Ok(machine) if machine.runnable_here() => Ok(machine),
        Ok(machine) => Err(format!("{role} at {} is {} and cannot run on this 64-bit build of Windows.", path.display(), machine.label())),
        Err(why) => Err(format!("{role} at {} cannot be used: {why}.", path.display())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn pe_with_machine(machine: u16) -> Vec<u8> {
        let mut bytes = vec![0u8; 0x40];
        bytes[0] = b'M';
        bytes[1] = b'Z';
        bytes[0x3C..0x40].copy_from_slice(&0x40u32.to_le_bytes());
        bytes.extend_from_slice(b"PE\0\0");
        bytes.extend_from_slice(&machine.to_le_bytes());
        bytes
    }

    #[test]
    fn reads_machine_types() {
        let dir = std::env::temp_dir().join(format!("ab-pe-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        for (name, machine, expect) in [("x64.exe", MACHINE_AMD64, Machine::X64), ("x86.exe", MACHINE_I386, Machine::X86)] {
            let path = dir.join(name);
            File::create(&path).unwrap().write_all(&pe_with_machine(machine)).unwrap();
            assert_eq!(machine_type(&path).unwrap(), expect);
        }
        let elf = dir.join("elf.exe");
        File::create(&elf).unwrap().write_all(b"\x7fELF\x02\x01").unwrap();
        assert!(machine_type(&elf).unwrap_err().contains("Linux (ELF)"));
        let _ = std::fs::remove_dir_all(dir);
    }
}
