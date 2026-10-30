param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Arguments
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Find-Docker {
  $command = Get-Command docker -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }
  $candidate = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
  if (Test-Path $candidate) { return $candidate }
  throw "找不到 Docker，请先启动 Docker Desktop。"
}

$docker = Find-Docker
$running = & $docker ps --filter "name=media-automation-worker" --format "{{.Names}}"
if (-not $running) {
  throw "worker 容器没有运行，请先执行 .\scripts\start.ps1"
}

& $docker exec media-automation-worker python indexers.py @Arguments
exit $LASTEXITCODE
