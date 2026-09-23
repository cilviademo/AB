<#
.SYNOPSIS
    Assemble the portable AB ZIP from a completed Tauri build and verify it by running it.
.DESCRIPTION
    Layout (the app resolves resources relative to the executable):
        AB/
          AB.exe
          resources/ab-engine/ab-engine.exe + _internal/
          resources/bin/vst3host.exe
          resources/static-engine/cli.mjs
          licenses/
          README.txt
#>
[CmdletBinding()]
param([string]$Version, [switch]$Portable)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$tauri = Join-Path $repo "app\src-tauri"
$release = Join-Path $tauri "target\release"
if (-not $Version) { $Version = (Get-Content (Join-Path $tauri "tauri.conf.json") -Raw | ConvertFrom-Json).version }

$exe = Join-Path $release "AB.exe"
if (-not (Test-Path $exe)) { throw "AB.exe not found at $exe. Run scripts\build-release.ps1 first." }
$engine = Join-Path $tauri "resources\ab-engine\ab-engine.exe"
if (-not (Test-Path $engine)) { throw "The engine was not built (resources\ab-engine\ab-engine.exe missing)." }

$dist = Join-Path $repo "dist\AB"
$out = Join-Path $repo "release"
if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
New-Item -ItemType Directory -Path $dist, $out -Force | Out-Null

Copy-Item $exe (Join-Path $dist "AB.exe")
Copy-Item (Join-Path $tauri "resources") (Join-Path $dist "resources") -Recurse -Force
Get-ChildItem (Join-Path $dist "resources") -Recurse -Filter PLACEHOLDER.txt | Remove-Item -Force
Copy-Item (Join-Path $repo "licenses") (Join-Path $dist "licenses") -Recurse -Force
Copy-Item (Join-Path $repo "LICENSE.txt") $dist -Force
if ($Portable) { Set-Content (Join-Path $dist "portable.flag") "AB keeps its data in the Data folder beside this file." -Encoding UTF8 }

@"
AB — Artifact Bench $Version
Recover. Reconstruct. Rebuild.

RUNNING IT
  Extract this whole folder somewhere you can write to, then double-click AB.exe.
  Keep the folder together: AB.exe needs the resources folder next to it.

FIRST LAUNCH
  Windows SmartScreen may say "Windows protected your PC" because this build is
  not code-signed. Click "More info", then "Run anyway". Once.
  If Windows says the Edge WebView2 runtime is missing, install it from
  https://go.microsoft.com/fwlink/p/?LinkId=2124703 and start AB again.

WHAT YOU NEED
  Nothing. Python, Node and Rust are not required — AB ships its own engine
  and its isolated VST3 host. Optional, detected when present: Ghidra + JDK
  (decompiler stage), CMake + MSVC Build Tools (rebuild), pluginval (validation).
  AB offers to download JDK, Ghidra and pluginval into %LOCALAPPDATA%\AB\tools,
  verified against pinned checksums.

WHERE YOUR FILES GO
  Projects    %USERPROFILE%\Documents\AB\Projects
  Exports     %USERPROFILE%\Documents\AB\Exports
  App data    %LOCALAPPDATA%\AB   (jobs.db, objects, knowledge cache, tools, logs)

PORTABLE MODE
  A file called portable.flag next to AB.exe keeps everything in a Data folder
  beside the executable.

PLUGINS ARE NEVER LOADED IN AB ITSELF
  Every plugin runs inside vst3host.exe, a separate process with a timeout and
  a Job Object. A plugin crash fails its stage; AB keeps running.

OFFLINE
  Core recovery makes no network calls. Only the optional tool downloader does.
"@ | Set-Content (Join-Path $dist "README.txt") -Encoding UTF8

Write-Host "Verifying the assembled layout..." -ForegroundColor Cyan
$reply = '{"id":1,"method":"ping"}' | & (Join-Path $dist "resources\ab-engine\ab-engine.exe")
if ($reply -notmatch '"ok":\s*true') { throw "the engine in the portable layout did not answer ping: $reply" }

$zip = Join-Path $out "AB-v$Version-Windows.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $dist -DestinationPath $zip -CompressionLevel Optimal
Get-ChildItem $out -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" } |
    ForEach-Object { "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.Name } |
    Set-Content (Join-Path $out "SHA256SUMS.txt") -Encoding UTF8

Write-Host "Verifying the extracted ZIP..." -ForegroundColor Cyan
$check = Join-Path ([System.IO.Path]::GetTempPath()) ("ab-ziptest-" + [guid]::NewGuid())
Expand-Archive -Path $zip -DestinationPath $check -Force
foreach ($required in @("AB\AB.exe", "AB\resources\ab-engine\ab-engine.exe")) {
    if (-not (Test-Path (Join-Path $check $required))) { Remove-Item $check -Recurse -Force; throw "missing from the ZIP: $required" }
}
$reply = '{"id":1,"method":"ping"}' | & (Join-Path $check "AB\resources\ab-engine\ab-engine.exe")
Remove-Item $check -Recurse -Force -ErrorAction SilentlyContinue
if ($reply -notmatch '"ok":\s*true') { throw "the engine inside the ZIP did not answer ping: $reply" }
Write-Host "Portable ZIP : $zip" -ForegroundColor Green
