$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$server = "D:\talkative menu\runtimes\llama.cpp\llama-server.exe"
$envFile = Join-Path $projectRoot ".env"

function Get-LocalSetting([string]$Name) {
    $line = Get-Content -LiteralPath $envFile | Where-Object { $_ -match "^$Name=" } | Select-Object -First 1
    if ($null -eq $line) {
        throw "$Name is missing from .env"
    }
    return $line.Substring("$Name=".Length)
}

function Get-LocalSettingOrDefault([string]$Name, [string]$Default) {
    $line = Get-Content -LiteralPath $envFile | Where-Object { $_ -match "^$Name=" } | Select-Object -First 1
    if ($null -eq $line) {
        return $Default
    }
    return $line.Substring("$Name=".Length)
}

$runtimeMode = Get-LocalSettingOrDefault "LOCAL_LLM_RUNTIME_MODE" "local"
if ($runtimeMode -ne "local") {
    throw "LOCAL_LLM_RUNTIME_MODE is remote; local llama-server startup is disabled"
}
$model = Get-LocalSetting "LOCAL_LLM_MODEL_PATH"
$alias = Get-LocalSetting "LOCAL_LLM_MODEL"

if (-not (Test-Path -LiteralPath $server)) {
    throw "Missing llama-server: $server"
}

if (-not (Test-Path -LiteralPath $model)) {
    throw "Missing model: $model"
}

& $server `
    -m $model `
    -a $alias `
    --host 127.0.0.1 `
    --port 8081 `
    --jinja `
    --reasoning-format deepseek `
    -c 8192 `
    -t 4 `
    -n 768 `
    --no-context-shift
