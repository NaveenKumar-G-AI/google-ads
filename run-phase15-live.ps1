param(
    [Parameter(Mandatory=$true)][string]$Start,
    [Parameter(Mandatory=$true)][string]$End,
    [string]$BusinessTruth,
    [Nullable[int]]$ConversionLagDays,
    [switch]$SkipAnalysis,
    [switch]$SkipGemini,
    [switch]$NoReplayProbe,
    [switch]$NoApplyMigrations,
    [string]$ReportDir = "phase15-live-reports"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found on PATH. Install Python 3.11-3.14 first."
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating local virtual environment..."
    python -m venv .venv
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment Python was not created successfully."
}

# Install the exact pinned runtime from this artifact. Secrets are never passed as CLI arguments.
& $python -m pip install --upgrade pip
& $python -m pip install -e ".[dev]"

$argsList = @(
    "examples_phase15_live.py",
    "--start", $Start,
    "--end", $End,
    "--report-dir", $ReportDir
)

if ($BusinessTruth) { $argsList += @("--business-truth", $BusinessTruth) }
if ($ConversionLagDays -ne $null) { $argsList += @("--conversion-lag-days", [string]$ConversionLagDays) }
if ($SkipAnalysis) { $argsList += "--skip-analysis" }
if ($SkipGemini) { $argsList += "--skip-gemini" }
if ($NoReplayProbe) { $argsList += "--no-replay-probe" }
if ($NoApplyMigrations) { $argsList += "--no-apply-migrations" }

& $python @argsList
exit $LASTEXITCODE
