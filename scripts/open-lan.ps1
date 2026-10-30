# 让局域网里的手机/平板访问本项目的网页：
#   1) 需要的话加上 8787 的防火墙规则（只放行局域网，不开公网）
#   2) 打印手机该用的地址
# 用法：右键「以管理员身份运行」，或先开管理员 PowerShell 再执行本脚本。

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$rules = @(
  @{ Name = "media-automation Web 8787 (LAN)"; Port = 8787 },
  @{ Name = "media-automation Jellyfin 8096 (LAN)"; Port = 8096 }
)

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-not $isAdmin) {
  Write-Host "需要管理员权限才能改防火墙。" -ForegroundColor Yellow
  Write-Host "复制下面这条命令到「以管理员身份运行」的 PowerShell 里执行：" -ForegroundColor Yellow
  Write-Host ""
  foreach ($rule in $rules) {
    Write-Host ('  New-NetFirewallRule -DisplayName "{0}" -Direction Inbound -Protocol TCP -LocalPort {1} -Action Allow -Profile Any -RemoteAddress LocalSubnet' -f $rule.Name, $rule.Port)
  }
  Write-Host ""
  exit 1
}

foreach ($rule in $rules) {
  if (Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue) {
    Write-Host "防火墙规则已存在：$($rule.Name)" -ForegroundColor Green
  } else {
    New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Protocol TCP -LocalPort $rule.Port `
      -Action Allow -Profile Any -RemoteAddress LocalSubnet | Out-Null
    Write-Host "已放行 TCP $($rule.Port)（仅限本子网）" -ForegroundColor Green
  }
}

# 选一个真实的局域网地址：跳过回环、APIPA 和 WSL/Hyper-V 的虚拟网卡
$candidates = Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object {
    $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and
    $_.InterfaceAlias -notmatch 'WSL|Hyper-V|Default Switch|Loopback'
  } |
  Sort-Object @{ Expression = { if ($_.PrefixOrigin -eq "Dhcp") { 0 } else { 1 } } }

$ip = ($candidates | Select-Object -First 1).IPAddress
if (-not $ip) {
  Write-Host "没有找到局域网 IPv4 地址，检查一下网络连接。" -ForegroundColor Yellow
  exit 1
}

$url = "http://${ip}:$port"
Write-Host ""
Write-Host "手机连同一个 Wi-Fi，浏览器打开：" -ForegroundColor Cyan
Write-Host "  $url" -ForegroundColor Green

try {
  $health = Invoke-WebRequest "$url/health" -UseBasicParsing -TimeoutSec 5
  if ($health.StatusCode -eq 200) {
    Write-Host "  服务正常（/health 返回 200）" -ForegroundColor Green
  }
} catch {
  Write-Host "  服务没响应，先跑 .\scripts\start.ps1" -ForegroundColor Yellow
}

$envPath = Join-Path (Get-Location) ".env"
if (Test-Path $envPath) {
  $user = (Get-Content $envPath -Encoding UTF8 | Where-Object { $_ -match '^WEB_USERNAME=' } | Select-Object -First 1) -replace '^WEB_USERNAME=', ''
  $pass = (Get-Content $envPath -Encoding UTF8 | Where-Object { $_ -match '^WEB_PASSWORD=' } | Select-Object -First 1) -replace '^WEB_PASSWORD=', ''
  if ($pass) {
    Write-Host "  登录：$user / $pass"
  } else {
    Write-Host "  当前没设网页密码（WEB_PASSWORD 为空），局域网里谁都能进，建议设置一下。"
  }
}

Write-Host ""
Write-Host "手机打不开时依次检查：" -ForegroundColor Yellow
Write-Host "  1. 手机和电脑是不是同一个 Wi-Fi/子网（手机 IP 应和上面同段）"
Write-Host "  2. 电脑有没有开着 VPN/Clash 的 TUN 模式（可能拦截局域网访问）"
Write-Host "  3. 路由器是否开了「AP 隔离」，开了要关掉"
