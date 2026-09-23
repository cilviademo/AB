# AB — Artifact Bench · Windows bootstrap + smoke test
# Run from the unzipped source root in PowerShell:   powershell -ExecutionPolicy Bypass -File .\bootstrap_windows.ps1
# Needs: Python 3.11+ (python.org or winget), Node.js 20+, Git. Optional for the deeper stages: CMake + Visual Studio 2022
# Build Tools (Desktop C++) for native\vst3host and the fixtures; `ab-cli tools install` fetches JDK/Ghidra/pluginval/JUCE.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Need($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { Write-Host "MISSING  $cmd — $hint" -ForegroundColor Red; exit 2 }
    Write-Host ("OK       {0,-8} {1}" -f $cmd, ((Get-Command $cmd).Source))
}
Write-Host "== prerequisites"
Need python "install Python 3.11+ from python.org (tick 'Add to PATH') or: winget install Python.Python.3.12"
Need node   "install Node.js 20+ LTS: winget install OpenJS.NodeJS.LTS"
Need git    "install Git for Windows: winget install Git.Git"
$py = (python -c "import sys;print('%d.%d' % sys.version_info[:2])")
if ([version]$py -lt [version]"3.11") { Write-Host "UNSUPPORTED Python $py — 3.11+ required" -ForegroundColor Red; exit 2 }

Write-Host "`n== engine (Python sidecar + ab-cli)"
python -m pip install --upgrade pip | Out-Null
python -m pip install -e "engine[dev]"
Write-Host "`n== static engine (frozen Static Recovery v2, Node)"
Push-Location app
npm ci --no-audit --no-fund
npm run build
Pop-Location

# ab-cli.exe lives in Python's Scripts folder, which is not always on PATH: call the module directly
function ab { python -m ab_engine.cli @args }

Write-Host "`n== doctor (AVAILABLE | MISSING | WRONG_VERSION | UNSUPPORTED, with what to install)"
ab --text doctor

Write-Host "`n== smoke test on the committed synthetic plugin (a well-formed PE; no runtime host needed)"
$ws = Join-Path $env:LOCALAPPDATA "AB-smoke"
$ingest = ab --workspace $ws ingest --name SynthPlug "fixtures\synthetic\SynthPlug.vst3" | ConvertFrom-Json
$job = $ingest.data.jobs[0].job_id
Write-Host "job $job → $($ingest.data.jobs[0].project_dir)"
ab --workspace $ws run $job --stage INGESTED --stage STATIC_COMPLETE --option prefer_node=true | Out-Null
ab --workspace $ws --text route "fixtures\synthetic\SynthPlug.vst3"
$export = ab --workspace $ws export $job --zip | ConvertFrom-Json
Write-Host ("export → {0}  files {1}  GIT_READY {2}  path findings {3}  secret findings {4}" -f $export.data.out_dir, $export.data.files, $export.data.git_ready.ok, $export.data.path_findings.Count, $export.data.secret_findings.Count)
ab --workspace $ws --text reference | Select-Object -First 12

Write-Host "`n== engine unit tests (127 on Linux; first Windows run — please report any failure with the output)"
Push-Location engine
python -m pytest -q
Pop-Location

Write-Host "`nDone. Next steps:"
Write-Host "  ab-cli --workspace $ws ingest `"C:\path\to\YourPlugin.vst3`"        # then: run <job> --stage INGESTED --stage STATIC_COMPLETE"
Write-Host "  native\vst3host\build_all.ps1                                          # CMake + MSVC → runtime, probes, differential harness"
Write-Host "  ab-cli tools install                                                   # JDK 21, Ghidra, pluginval, JUCE (pinned SHA-256)"
Write-Host "  fixtures\groundtruth\build_all.ps1                                     # the known-source fixture, three ways; then ab-cli ground-truth <job> --phase 4"
Write-Host "  cd app; npm run tauri dev                                              # the desktop shell (needs the Rust toolchain)"
