<#
.SYNOPSIS
    Build the ground-truth fixture three ways on Windows (EXECUTE 1.6).
      out\debug\     Debug + PDB
      out\release\   Release + PDB
      out\stripped\  Release, no PDB, /DEBUG:NONE   <- the recovery input
    Binaries and PDBs are CI artifacts, never committed.
.NOTES
    Needs CMake 3.22+, MSVC Build Tools (x64), Python 3.11+, git. JUCE 8.0.9 is cloned on first run.
#>
[CmdletBinding()]
param([string]$JuceTag = "8.0.9")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path "third_party\JUCE\CMakeLists.txt")) {
    New-Item -ItemType Directory -Force third_party | Out-Null
    $env:GIT_LFS_SKIP_SMUDGE = "1"
    git clone --depth 1 --branch $JuceTag https://github.com/juce-framework/JUCE third_party\JUCE
}
python gen.py
function Build($name, $type, $strip) {
    cmake -S . -B "build\$name" -A x64 -DAB_STRIP=$strip | Out-Null
    cmake --build "build\$name" --config $type --target ABGroundTruth_VST3
    if (Test-Path "out\$name") { Remove-Item "out\$name" -Recurse -Force }
    New-Item -ItemType Directory -Force "out\$name" | Out-Null
    Copy-Item "build\$name\ABGroundTruth_artefacts\$type\VST3\ABGroundTruth.vst3" "out\$name\" -Recurse
    $pdb = Get-ChildItem "build\$name\ABGroundTruth_artefacts\$type" -Recurse -Filter "*.pdb" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pdb -and $strip -eq "OFF") { Copy-Item $pdb.FullName "out\$name\" }
    Write-Host "built out\$name\ABGroundTruth.vst3 ($type, strip=$strip)" -ForegroundColor Green
}
Build "debug" "Debug" "OFF"
Build "release" "Release" "OFF"
Build "stripped" "Release" "ON"
$builds = @{}
foreach ($v in @("debug", "release", "stripped")) {
    $bin = Get-ChildItem "out\$v" -Recurse -Filter "*.vst3" -File | Where-Object { $_.Length -gt 32768 } | Select-Object -First 1
    $builds[$v] = @{ path = $bin.FullName; size = $bin.Length; sha256 = (Get-FileHash $bin.FullName -Algorithm SHA256).Hash.ToLower() }
}
$builds | ConvertTo-Json | Set-Content "out\builds.json" -Encoding UTF8
Get-Content "out\builds.json"
