$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$databaseLine = Get-Content -LiteralPath ".env" | Where-Object { $_ -match "^DATABASE_URL=" } | Select-Object -First 1
if ($null -eq $databaseLine) {
    throw "DATABASE_URL is missing from .env"
}
$env:DATABASE_URL = ($databaseLine.Substring("DATABASE_URL=".Length) -replace "/ainza(?=\?|$)", "/ainza_restaurant_e2e")
$runtimeLine = Get-Content -LiteralPath ".env" | Where-Object { $_ -match "^LOCAL_LLM_RUNTIME_MODE=" } | Select-Object -First 1
$runtimeMode = if ($null -eq $runtimeLine) { "local" } else { $runtimeLine.Substring("LOCAL_LLM_RUNTIME_MODE=".Length) }
if ($runtimeMode -notin @("local", "remote")) {
    throw "LOCAL_LLM_RUNTIME_MODE must be local or remote"
}
$baseUrlLine = Get-Content -LiteralPath ".env" | Where-Object { $_ -match "^LOCAL_LLM_BASE_URL=" } | Select-Object -First 1
$modelLine = Get-Content -LiteralPath ".env" | Where-Object { $_ -match "^LOCAL_LLM_MODEL=" } | Select-Object -First 1
$modelPathLine = Get-Content -LiteralPath ".env" | Where-Object { $_ -match "^LOCAL_LLM_MODEL_PATH=" } | Select-Object -First 1
if ($null -eq $modelLine -or $null -eq $baseUrlLine) {
    throw "LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL are required in .env"
}
$env:LOCAL_LLM_MODEL = $modelLine.Substring("LOCAL_LLM_MODEL=".Length)
$env:LOCAL_LLM_BASE_URL = $baseUrlLine.Substring("LOCAL_LLM_BASE_URL=".Length)

$apiKeyLine = Get-Content -LiteralPath ".env" | Where-Object { $_ -match "^LOCAL_LLM_API_KEY=" } | Select-Object -First 1
if ($null -ne $apiKeyLine) {
    $env:LOCAL_LLM_API_KEY = $apiKeyLine.Substring("LOCAL_LLM_API_KEY=".Length)
}
if ($runtimeMode -eq "local") {
    if ($null -eq $modelPathLine) {
        throw "LOCAL_LLM_MODEL_PATH is required when LOCAL_LLM_RUNTIME_MODE=local"
    }
    $env:LOCAL_LLM_MODEL_PATH = $modelPathLine.Substring("LOCAL_LLM_MODEL_PATH=".Length)
}

function Get-HttpJson([string]$Url) {
    try {
        $headers = @{}
        if (-not [string]::IsNullOrWhiteSpace($env:LOCAL_LLM_API_KEY)) {
            $headers["Authorization"] = "Bearer $($env:LOCAL_LLM_API_KEY)"
        }
        return Invoke-RestMethod -Uri $Url -Headers $headers -TimeoutSec 5
    }
    catch {
        return $null
    }
}

function Test-PortInUse([int]$Port) {
    return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1)
}

$llmModels = $null
if ($runtimeMode -eq "local") {
    if (-not (Test-Path -LiteralPath "D:\talkative menu\runtimes\llama.cpp\llama-server.exe")) {
        throw "Missing llama-server: D:\talkative menu\runtimes\llama.cpp\llama-server.exe"
    }
    if (-not (Test-Path -LiteralPath $env:LOCAL_LLM_MODEL_PATH)) {
        throw "Missing model: $env:LOCAL_LLM_MODEL_PATH"
    }
    $llmModels = Get-HttpJson "$($env:LOCAL_LLM_BASE_URL)/models"
    if ($null -eq $llmModels) {
        if (Test-PortInUse 8081) {
            throw "Port 8081 is occupied by an unrecognized service"
        }
        $llmOut = Join-Path $projectRoot "tmp\human-typed-llama.out.log"
        $llmErr = Join-Path $projectRoot "tmp\human-typed-llama.err.log"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $llmOut) | Out-Null
        $llmLauncher = '"{0}"' -f (Join-Path $projectRoot "scripts\start_local_llm.ps1")
        Start-Process -FilePath "powershell.exe" -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $llmLauncher
        ) -RedirectStandardOutput $llmOut -RedirectStandardError $llmErr -WindowStyle Hidden
        $deadline = (Get-Date).AddMinutes(5)
        while ((Get-Date) -lt $deadline -and $null -eq (Get-HttpJson "$($env:LOCAL_LLM_BASE_URL)/models")) {
            Start-Sleep -Seconds 2
        }
    }
} else {
    $llmModels = Get-HttpJson "$($env:LOCAL_LLM_BASE_URL)/models"
}
if ($null -eq $llmModels) {
    throw "Configured AI inference endpoint is not healthy"
}
$modelIds = @($llmModels.data | ForEach-Object {
    if ($null -ne $_.id) {
        $id = [string]$_.id
        if ($id.StartsWith("models/")) {
            $id.Substring("models/".Length)
        } else {
            $id
        }
    }
})

if ($modelIds -notcontains $env:LOCAL_LLM_MODEL) {
    throw "Configured AI endpoint does not expose the expected $env:LOCAL_LLM_MODEL model"
}
Write-Host "[PASS] configured AI inference endpoint healthy"

$health = Get-HttpJson "http://127.0.0.1:8000/health"
if ($null -eq $health) {
    if (Test-PortInUse 8000) {
        throw "Port 8000 is occupied by an unrecognized service"
    }
    $apiOut = Join-Path $projectRoot "tmp\human-typed-fastapi.out.log"
    $apiErr = Join-Path $projectRoot "tmp\human-typed-fastapi.err.log"
    Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList @(
        "-m", "uvicorn", "ainza_restaurant.main:app", "--host", "127.0.0.1", "--port", "8000"
    ) -WorkingDirectory $projectRoot -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline -and $null -eq (Get-HttpJson "http://127.0.0.1:8000/health")) {
        Start-Sleep -Seconds 1
    }
}
$health = Get-HttpJson "http://127.0.0.1:8000/health"
if ($null -eq $health -or $health.status -ne "ok") {
    throw "FastAPI did not become healthy within 60 seconds"
}
$openApi = Get-HttpJson "http://127.0.0.1:8000/openapi.json"
if ($null -eq $openApi -or -not $openApi.paths.'/api/v1/ai/conversations/{conversation_token}/messages') {
    throw "FastAPI does not expose the expected customer AI conversation endpoint"
}
Write-Host "[PASS] FastAPI healthy"

& .\.venv\Scripts\python.exe scripts\prepare_human_typed_test.py
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
& .\.venv\Scripts\python.exe scripts\talk_to_menu_human_cli.py
