<#
.SYNOPSIS
    Build the unseen fixture (ADDENDUM B8 test 1) on Windows. Default: only the stripped recovery input.
      out\stripped\  Release, no PDB, /DEBUG:NONE
    JUCE is shared with fixtures\groundtruth (cloned there on first run of its build_all.ps1, or pass -JuceDir).
.NOTES
    Needs CMake 3.22+, MSVC Build Tools (x64), Python 3.11+, git.
#>
[CmdletBinding()]
param([string]$JuceDir = "", [string[]]$Variants = @("stripped"), [string]$JuceTag = "8.0.9")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not $JuceDir) { $JuceDir = Join-Path (Split-Path -Parent $PSScriptRoot) "groundtruth\third_party\JUCE" }
if (-not (Test-Path (Join-Path $JuceDir "CMakeLists.txt"))) {
    New-Item -ItemType Directory -Force (Split-Path -Parent $JuceDir) | Out-Null
    $env:GIT_LFS_SKIP_SMUDGE = "1"
    git clone --depth 1 --branch $JuceTag https://github.com/juce-framework/JUCE $JuceDir
}
python gen.py
function Build($name, $type, $strip) {
    cmake -S . -B "build\$name" -A x64 -DJUCE_DIR="$JuceDir" -DAB_STRIP=$strip | Out-Null
    cmake --build "build\$name" --config $type --target ABUnseen_VST3
    if (Test-Path "out\$name") { Remove-Item "out\$name" -Recurse -Force }
    New-Item -ItemType Directory -Force "out\$name" | Out-Null
    Copy-Item "build\$name\ABUnseen_artefacts\$type\VST3\ABUnseen.vst3" "out\$name\" -Recurse
    Write-Host "built out\$name\ABUnseen.vst3 ($type, strip=$strip)" -ForegroundColor Green
}
foreach ($v in $Variants) {
    switch ($v) {
        "debug"    { Build "debug" "Debug" "OFF" }
        "release"  { Build "release" "Release" "OFF" }
        "stripped" { Build "stripped" "Release" "ON" }
        default    { throw "unknown variant $v" }
    }
}
$builds = @{}
foreach ($v in @("debug", "release", "stripped")) {
    if (-not (Test-Path "out\$v")) { continue }
    $bin = Get-ChildItem "out\$v" -Recurse -Filter "*.vst3" -File | Where-Object { $_.Length -gt 32768 } | Select-Object -First 1
    $builds[$v] = @{ path = $bin.FullName; size = $bin.Length; sha256 = (Get-FileHash $bin.FullName -Algorithm SHA256).Hash.ToLower() }
}
$builds | ConvertTo-Json | Set-Content "out\builds.json" -Encoding UTF8
Get-Content "out\builds.json"
