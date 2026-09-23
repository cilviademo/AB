<# Build vst3host.exe on Windows (x64, Release). Clones the VST3 SDK with submodules on first run. #>
[CmdletBinding()] param([string]$SdkTag = "v3.7.9_build_61")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path "third_party\vst3sdk\CMakeLists.txt")) {
    New-Item -ItemType Directory -Force third_party | Out-Null
    $env:GIT_LFS_SKIP_SMUDGE = "1"
    git clone --depth 1 --branch $SdkTag --recurse-submodules --shallow-submodules https://github.com/steinbergmedia/vst3sdk third_party\vst3sdk
}
cmake -S . -B build -A x64 | Out-Null
cmake --build build --config Release --target vst3host
& ".\build\Release\vst3host.exe" --version
