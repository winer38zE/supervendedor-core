# Ejecutar antes de deploy a Coolify
# Uso: .\scripts\run_tests.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    Write-Host "Creando venv..."
    python -m venv .venv
}

& .\.venv\Scripts\Activate.ps1
pip install -q pytest httpx

$env:ENV = "development"
$env:FOLLOWUP_SCHEDULER_ENABLED = "false"

Write-Host "Ejecutando tests de humo..."
python -m pytest tests/test_smoke.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "OK — listo para deploy"
