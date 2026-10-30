# 修复「电脑热点能连上、但没有互联网」的问题。
# 用法：右键「以管理员身份运行」，或先开管理员 PowerShell 再执行。
# 做的事情：
#   1. 检查以太网（公网出口）和热点网段是否正常
#   2. 把以太网标记为「专用网络」，避免 ICS 因网络类别不共享
#   3. 重启 Internet 连接共享 (SharedAccess / ICS) 服务，让它重新绑定公网网卡
#   4. 提示接下来要手动做的两步

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
  Write-Host "需要管理员权限。" -ForegroundColor Yellow
  Write-Host "右键本脚本 →「以管理员身份运行」。"
  exit 1
}

Write-Host "== 当前网络 ==" -ForegroundColor Cyan
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.InterfaceAlias -match '以太网|WLAN|本地连接' } |
  Select-Object InterfaceAlias, IPAddress, PrefixLength | Format-Table -AutoSize

$ethernet = Get-NetIPConfiguration -InterfaceAlias "以太网" -ErrorAction SilentlyContinue
if (-not $ethernet.IPv4DefaultGateway) {
  Write-Host "以太网没有默认网关，先确认网线/上网方式正常。" -ForegroundColor Yellow
  exit 1
}
Write-Host ("公网出口：以太网 -> 网关 {0}" -f $ethernet.IPv4DefaultGateway.NextHop) -ForegroundColor Green

# 清掉断开网卡上残留的默认路由（之前连 iPhone 热点会留下 172.20.10.1）
$wlan = Get-NetAdapter -Name "WLAN" -ErrorAction SilentlyContinue
if ($wlan -and $wlan.Status -ne "Up") {
  $stale = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
    Where-Object { $_.InterfaceIndex -eq $wlan.ifIndex }
  foreach ($route in $stale) {
    try {
      Remove-NetRoute -InputObject $route -Confirm:$false -ErrorAction Stop
      Write-Host ("已清掉 WLAN 上的残留默认路由：{0}" -f $route.NextHop) -ForegroundColor Green
    } catch {
      Write-Host ("清理残留路由失败：{0}" -f $_.Exception.Message) -ForegroundColor Yellow
    }
  }
}

try {
  Set-NetConnectionProfile -InterfaceAlias "以太网" -NetworkCategory Private -ErrorAction Stop
  Write-Host "已把以太网设为「专用网络」" -ForegroundColor Green
} catch {
  Write-Host ("设置网络类别失败：{0}" -f $_.Exception.Message) -ForegroundColor Yellow
}

Write-Host "== 重启 Internet 连接共享 ==" -ForegroundColor Cyan
foreach ($name in @("SharedAccess", "icssvc")) {
  $service = Get-Service -Name $name -ErrorAction SilentlyContinue
  if (-not $service) { continue }
  try {
    Restart-Service -Name $name -Force -ErrorAction Stop
    Write-Host ("  {0} 已重启" -f $name) -ForegroundColor Green
  } catch {
    Write-Host ("  {0} 重启失败：{1}" -f $name, $_.Exception.Message) -ForegroundColor Yellow
  }
}

Write-Host ""
Write-Host "接下来手动做两步：" -ForegroundColor Cyan
Write-Host "  1. 设置 → 网络和 Internet → 移动热点 → 关闭再打开"
Write-Host "     并把「共享我的 Internet 连接」选成 以太网"
Write-Host "  2. iPhone：无线局域网 → 点热点名 ⓘ → 忽略此网络 → 重新连接"
Write-Host "     弹「无互联网连接」时选「继续使用无线局域网」"
Write-Host ""
Write-Host "连接后先验证局域网：" -ForegroundColor Cyan
Write-Host "  iPhone Safari 打开 http://192.168.137.1:8787"
Write-Host "  能打开 = 局域网通了；再试外网，通 = NAT 正常"
Write-Host ""
Write-Host "如果外网还是不通，做一个判断：" -ForegroundColor Cyan
Write-Host "  iPhone 直接开 http://223.5.5.5"
Write-Host "    能打开（显示阿里 DNS 页面）= NAT 通、只是 DNS 没下发 → 在 iPhone 上手动设 DNS 223.5.5.5"
Write-Host "    打不开 = NAT 根本没生效（校园网/公司网常限制共享），换方案："
Write-Host "           反向用 iPhone 个人热点给电脑，或把文件传 115 网盘中转"
