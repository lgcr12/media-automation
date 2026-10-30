# 开机兜底：等 Docker 引擎就绪后自动拉起媒体自动化全部容器
$log = "D:\Code\media-automation\data\autostart.log"
function Write-Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $log -Value $line -Encoding UTF8
}

Write-Log "=== 开机自启检查开始 ==="

# 1. Docker Desktop 没起来就先拉起来
$running = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
if (-not $running) {
    Write-Log "Docker Desktop 未运行，尝试启动"
    if (Test-Path "D:\Apps\DockerDesktop\Docker Desktop.exe") {
        Start-Process "D:\Apps\DockerDesktop\Docker Desktop.exe"
    } else {
        Write-Log "找不到 Docker Desktop.exe，退出"
        exit 1
    }
} else {
    Write-Log "Docker Desktop 已在运行"
}

# 2. 等引擎就绪（最多 5 分钟）
$ready = $false
for ($i = 0; $i -lt 50; $i++) {
    Start-Sleep -Seconds 6
    $ver = docker info --format "{{.ServerVersion}}" 2>$null
    if ($LASTEXITCODE -eq 0 -and $ver) {
        Write-Log "Docker 引擎就绪: $ver"
        $ready = $true
        break
    }
}
if (-not $ready) {
    Write-Log "等待 5 分钟 Docker 仍未就绪，放弃"
    exit 1
}

# 3. 拉起容器
Set-Location "D:\Code\media-automation"
$out = docker compose --profile station up -d worker station prowlarr qbittorrent flaresolverr jellyfin 2>&1
Write-Log ("compose up 输出: " + ($out -join " | "))

# 4. 等 worker 健康
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 5
    $state = docker inspect --format "{{.State.Status}}" media-automation-worker 2>$null
    if ($state -eq "running") {
        $ok = docker exec media-automation-worker python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8787/health',timeout=5)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Log "worker 健康检查通过"
            break
        }
    }
}
Write-Log "=== 开机自启检查结束 ==="