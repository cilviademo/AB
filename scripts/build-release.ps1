<#
.SYNOPSIS
    Build the AB Windows release: portable ZIP (single AB.exe + bundled engine).
.DESCRIPTION
    Run from a plain PowerShell on the studio PC. Needs Python 3.11+, Node 22+,
    Rust (msvc) and CMake + MSVC Build Tools (for vst3host) on PATH.
    1. PyInstaller → engine/dist/ab-engine/            → app/src-tauri/resources/ab-engine/
    2. cmake       → native/vst3host/build/Release/vst3host.exe → app/src-tauri/resources/bin/
    3. npm build   → app/dist + app/static-engine/dist/cli.mjs  → resources/static-engine/
    4. tauri build → app/src-tauri/target/release/AB.exe
    5. make-portable.ps1 → release/AB-v<version>-Windows.zip (+ SHA256SUMS)
.EXAMPLE
    .\scripts\build-release.ps1
    .\scripts\build-release.ps1 -SkipEngine -SkipHost
#>
[CmdletBinding()]
param([switch]$SkipEngine, [switch]$SkipHost, [switch]$SkipInstaller)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$app = Join-Path $repo "app"
$tauri = Join-Path $app "src-tauri"
Set-Location $repo

function Require($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { throw "$name not found. $hint" }
}
Require python "Install Python 3.11+ and add it to PATH."
Require npm "Install Node 22+."
Require cargo "Install Rust (msvc toolchain) from https://rustup.rs."

if (-not $SkipEngine) {
    Write-Host "Building the engine (PyInstaller)..." -ForegroundColor Cyan
    Push-Location (Join-Path $repo "engine")
    python -m pip install --quiet -e "." pyinstaller
    python -m PyInstaller ab-engine.spec --noconfirm
    Pop-Location
    $dst = Join-Path $tauri "resources\ab-engine"
    if (Test-Path $dst) { Get-ChildItem $dst -Exclude PLACEHOLDER.txt | Remove-Item -Recurse -Force }
    Copy-Item (Join-Path $repo "engine\dist\ab-engine\*") $dst -Recurse -Force
    $reply = '{"id":1,"method":"ping"}' | & (Join-Path $dst "ab-engine.exe")
    if ($reply -notmatch '"ok":\s*true') { throw "the packaged engine did not answer ping: $reply" }
}

if (-not $SkipHost) {
    Require cmake "Install CMake and MSVC Build Tools."
    Write-Host "Building vst3host..." -ForegroundColor Cyan
    Push-Location (Join-Path $repo "native\vst3host")
    cmake -S . -B build -A x64
    cmake --build build --config Release
    Pop-Location
    $bin = Join-Path $tauri "resources\bin"
    New-Item -ItemType Directory -Path $bin -Force | Out-Null
    Copy-Item (Join-Path $repo "native\vst3host\build\Release\vst3host.exe") $bin -Force
}

Write-Host "Building the UI and static engine..." -ForegroundColor Cyan
Push-Location $app
npm ci
npm run build
Pop-Location
$se = Join-Path $tauri "resources\static-engine"
New-Item -ItemType Directory -Path $se -Force | Out-Null
Copy-Item (Join-Path $app "static-engine\dist\cli.mjs") $se -Force

Write-Host "Building AB.exe (tauri build)..." -ForegroundColor Cyan
Push-Location $app
if ($SkipInstaller) { npx tauri build --no-bundle } else { npx tauri build }
Pop-Location

& (Join-Path $PSScriptRoot "make-portable.ps1") -Portable
