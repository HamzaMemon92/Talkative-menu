Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

& ".\.venv\Scripts\python.exe" "scripts\prepare_v1_acceptance.py"
if ($LASTEXITCODE -ne 0) {
    throw "V1 acceptance preparation failed."
}

function Get-Health {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 5
    }
    catch {
        return $null
    }
}

$health = Get-Health
if ($null -eq $health) {
    $logDirectory = Join-Path $root "tmp"
    New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
    Start-Process -FilePath (Join-Path $root ".venv\Scripts\python.exe") -ArgumentList @(
        "-m", "uvicorn", "ainza_restaurant.main:app", "--host", "127.0.0.1", "--port", "8000"
    ) -WorkingDirectory $root `
        -RedirectStandardOutput (Join-Path $logDirectory "v1-acceptance-api.out.log") `
        -RedirectStandardError (Join-Path $logDirectory "v1-acceptance-api.err.log") `
        -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Seconds 1
        $health = Get-Health
    } while ($null -eq $health -and (Get-Date) -lt $deadline)
}
if ($null -eq $health -or $health.status -ne "ok") {
    throw "FastAPI did not become healthy within 60 seconds."
}

& ".\.venv\Scripts\python.exe" "scripts\talk_to_menu_human_cli.py" `
    "--state-file" "tmp\v1_acceptance_state.json"
