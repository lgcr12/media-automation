$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

$command = Get-Command docker -ErrorAction SilentlyContinue
$docker = if ($command) { $command.Source } else { "C:\Program Files\Docker\Docker\resources\bin\docker.exe" }
if (-not (Test-Path $docker) -and -not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw "找不到 Docker。"
}

& $docker compose --profile station down --timeout 60
