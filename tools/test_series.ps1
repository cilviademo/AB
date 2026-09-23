# Soak the engine suite on Windows (ADDENDUM B7): N sequential runs, runs under a CPU hog, random-order runs.
# Usage: powershell -File tools\test_series.ps1 [-N 3] [-Hog 2] [-Random 2]
param([int]$N = 3, [int]$Hog = 2, [int]$Random = 2)
Set-Location (Join-Path $PSScriptRoot "..\engine")
function Run($label, $extra) {
    Write-Host "== $label"
    python -m pytest -q -p no:cacheprovider @extra 2>&1 | Select-String -Pattern "^FAILED|^ERROR|passed|failed|error"
}
for ($r = 1; $r -le $N; $r++) { Run "sequential $r" @("-p", "no:randomly") }
if ($Hog -gt 0) {
    $jobs = @()
    for ($i = 1; $i -le [Environment]::ProcessorCount; $i++) { $jobs += Start-Job { $t = Get-Date; while (((Get-Date) - $t).TotalSeconds -lt 900) { } } }
    for ($r = 1; $r -le $Hog; $r++) { Run "under CPU hog $r" @("-p", "no:randomly") }
    $jobs | Stop-Job; $jobs | Remove-Job
}
python -c "import pytest_randomly" 2>$null
if ($LASTEXITCODE -eq 0) { for ($r = 1; $r -le $Random; $r++) { Run "random order $r" @("-p", "randomly") } } else { Write-Host "random order: pip install pytest-randomly to enable" }
