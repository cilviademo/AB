<# Developer setup on Windows: engine (editable), UI deps, Rust check. #>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
python -m pip install -q -e "engine[dev]"
Push-Location app; npm ci --no-audit --no-fund; Pop-Location
cargo check --manifest-path app\src-tauri\Cargo.toml
Write-Host "ok: run 'ab-cli --text doctor'"
