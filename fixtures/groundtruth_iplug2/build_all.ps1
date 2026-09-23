# Build ground-truth fixture #2 (iPlug2) on Windows two ways (ADDENDUM A5, BLOCKERS B-008):
#   out\release\   Release + PDB
#   out\stripped\  Release, no PDB (/DEBUG:NONE)  <- the recovery input
# Clones iPlug2 (pinned tag) into third_party\ on first run; iPlug2's own script fetches the VST3 SDK.
# Binaries are never committed. Not verified in the Linux development environment.
param(
    [string]$IPlug2Tag = "v1.0.0",   # pin: last tagged iPlug2 release; bump deliberately and record in docs/DEPENDENCIES.md
    [int]$Jobs = [Environment]::ProcessorCount
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "third_party\iPlug2\iPlug2.cmake")) {
    New-Item -ItemType Directory -Force third_party | Out-Null
    git clone --depth 1 --branch $IPlug2Tag https://github.com/iPlug2/iPlug2 third_party\iPlug2
    Push-Location third_party\iPlug2\Dependencies\IPlug
    .\download-iplug-sdks.sh 2>$null; if ($LASTEXITCODE -ne 0) { Write-Host "run Dependencies\IPlug\download-iplug-sdks.sh from Git Bash to fetch the VST3 SDK" }
    Pop-Location
}
python gen.py

function Build([string]$name, [string]$strip) {
    cmake -S . -B "build\$name" -G "Visual Studio 17 2022" -A x64 -DAB_STRIP=$strip | Out-Null
    cmake --build "build\$name" --config Release --target ABGroundTruthIP_vst3 -- /m:$Jobs
    Remove-Item -Recurse -Force "out\$name" -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force "out\$name" | Out-Null
    $bundle = Get-ChildItem -Recurse -Directory "build\$name" | Where-Object { $_.Name -eq "ABGroundTruthIP.vst3" } | Select-Object -First 1
    if (-not $bundle) { throw "no .vst3 bundle produced for $name" }
    Copy-Item -Recurse $bundle.FullName "out\$name\"
    Write-Host "built out\$name\ABGroundTruthIP.vst3 (strip=$strip)"
}
Build "release" "OFF"
Build "stripped" "ON"

$out = @{}
foreach ($v in @("release", "stripped")) {
    $bin = Get-ChildItem -Recurse -File "out\$v" | Where-Object { $_.Extension -in ".vst3", ".dll" -and $_.Length -gt 32768 } | Select-Object -First 1
    if ($bin) { $out[$v] = @{ path = $bin.FullName; size = $bin.Length; sha256 = (Get-FileHash -Algorithm SHA256 $bin.FullName).Hash.ToLower() } }
}
$out | ConvertTo-Json | Set-Content "out\builds.json"
Get-Content "out\builds.json"
