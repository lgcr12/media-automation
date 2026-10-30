$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

New-Item -ItemType Directory -Force -Path `
  data, media/inbox, media/output, media/downloads, fonts, `
  prowlarr/config, qbittorrent/config | Out-Null

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
}

function Find-Docker {
  $command = Get-Command docker -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }
  foreach ($candidate in @(
      "C:\Program Files\Docker\Docker\resources\bin\docker.exe",
      "D:\Apps\DockerDesktop\resources\bin\docker.exe",
      "D:\Apps\Docker Desktop\resources\bin\docker.exe"
  )) {
    if (Test-Path $candidate) { return $candidate }
  }
  throw "找不到 Docker，请先安装并启动 Docker Desktop。"
}

function Find-DockerDesktop([string]$dockerCli) {
  $candidates = New-Object System.Collections.Generic.List[string]
  # docker.exe 在 <安装根>\resources\bin\ 下，桌面程序在 <安装根>\Docker Desktop.exe
  if ($dockerCli) {
    $root = Split-Path (Split-Path (Split-Path $dockerCli -Parent) -Parent) -Parent
    $candidates.Add((Join-Path $root "Docker Desktop.exe"))
  }
  $candidates.Add("C:\Program Files\Docker\Docker\Docker Desktop.exe")
  $candidates.Add("D:\Apps\DockerDesktop\Docker Desktop.exe")
  $candidates.Add("D:\Apps\Docker Desktop\Docker Desktop.exe")
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) { return $candidate }
  }
  return $null
}

$docker = Find-Docker

# 尝试启动 Docker Desktop，并等待 daemon 就绪
$desktop = Find-DockerDesktop $docker
$running = $false
try {
  & $docker info *> $null
  $running = ($LASTEXITCODE -eq 0)
} catch {
  $running = $false
}
if (-not $running) {
  if (-not $desktop) {
    throw "Docker daemon 未运行，且找不到 Docker Desktop。请手动启动 Docker Desktop 后重试。"
  }
  Write-Host "正在启动 Docker Desktop..." -ForegroundColor Cyan
  Start-Process $desktop
  $ready = $false
  for ($i = 0; $i -lt 120; $i++) {
    try {
      & $docker info *> $null
      if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
  }
  if (-not $ready) { throw "Docker Desktop 未在 120 秒内就绪，请手动启动后重试。" }
}

& $docker compose --profile station up -d worker station prowlarr qbittorrent flaresolverr jellyfin
if ($LASTEXITCODE -ne 0) { throw "docker compose 启动失败，请检查上方日志。" }

Write-Host ""
Write-Host "搜索 / 任务 / 配置：http://127.0.0.1:8787" -ForegroundColor Green
Write-Host "Prowlarr：http://127.0.0.1:9696"
Write-Host "qBittorrent：http://127.0.0.1:8081"
Write-Host "115-Station：http://127.0.0.1:6060"
Write-Host "索引器：.\scripts\indexers.ps1 add（首次接入推荐索引器，已存在的会跳过）" -ForegroundColor Yellow
Write-Host ""

# Prowlarr 的索引器大多在墙外，走 .env 里的 MEDIA_HTTP_PROXY；代理没开时索引器会全部不可用
$proxyPort = 7897
if (Test-Path ".env") {
  $proxyLine = Get-Content ".env" -Encoding UTF8 | Where-Object { $_ -match '^\s*MEDIA_HTTP_PROXY\s*=' } | Select-Object -First 1
  if ($proxyLine -match ':(\d{2,5})\s*$') { $proxyPort = [int]$Matches[1] }
}
$proxyUp = $false
try {
  $proxyUp = [bool](Get-NetTCPConnection -State Listen -LocalPort $proxyPort -ErrorAction SilentlyContinue)
} catch { }
if (-not $proxyUp) {
  Write-Host "注意：本地代理端口 $proxyPort 没有监听，Prowlarr 的索引器会全部不可用。" -ForegroundColor Yellow
  Write-Host "      先启动 Clash Verge（D:\clash\Clash Verge\clash-verge.exe），再执行 .\scripts\indexers.ps1 test 确认。" -ForegroundColor Yellow
  Write-Host ""
}

# 列出没跑完的任务，确认断点续传已经接上
$jobsFile = Join-Path (Get-Location) "data/jobs.json"
if (Test-Path $jobsFile) {
  $jobs = $null
  # worker 会周期性重写 jobs.json，偶尔会读到写了一半的文件，重试几次即可
  for ($i = 0; $i -lt 5 -and $null -eq $jobs; $i++) {
    try {
      $jobs = Get-Content $jobsFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
      Start-Sleep -Milliseconds 300
    }
  }
  if ($null -eq $jobs) {
    Write-Host "暂时读不到 data/jobs.json，任务进度请看 http://127.0.0.1:8787" -ForegroundColor Yellow
  } else {
    $pending = @($jobs | Where-Object { $_.status -in @("queued", "downloading", "awaiting_source", "processing") })
    if ($pending.Count -gt 0) {
      Write-Host "未完成任务（worker 会自动接着跑）：" -ForegroundColor Cyan
      foreach ($job in $pending) {
        $percent = 0
        if ($job.download -and $job.download.progress) {
          $percent = [math]::Round([double]$job.download.progress * 100, 2)
        }
        Write-Host ("  {0}  {1}  {2}%" -f $job.id, $job.status, $percent)
      }
      Write-Host "进度页：http://127.0.0.1:8787" -ForegroundColor Green
    }
  }
}

Start-Sleep -Seconds 5
Write-Host "qBittorrent 临时密码（如果还没设置）：" -ForegroundColor Yellow
# docker logs 会往 stderr 写代理/连接日志，Stop 模式下会被当成错误中断脚本。
$previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $docker logs media-automation-qbittorrent 2>&1 | Select-String -Pattern "password" | Select-Object -Last 1
& $docker compose ps
$ErrorActionPreference = $previous
