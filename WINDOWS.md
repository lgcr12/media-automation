# Windows 部署指南

本项目在 Windows 上使用 **Docker Desktop + WSL2 Linux 容器**，不是 Windows 容器。

## 1. 前置条件

- Windows 10/11 64 位
- BIOS 已开启虚拟化（VT-x / AMD-V）
- 安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Docker Desktop 设置里启用 **Use the WSL 2 based engine**
- 至少 15GB 可用磁盘空间（下载视频另算）

安装后启动 Docker Desktop，等左下角显示 **Engine running**。

## 2. 解压

把 `media-automation-windows-*.zip` 解压到本地目录，例如：

```text
C:\Users\你的用户名\media-automation
```

路径可以包含空格，但不要放在 `C:\Program Files` 这类需要管理员权限的目录。

解压后的结构应包含：

```text
media-automation/
├── docker-compose.yml
├── .env.example
├── worker/
├── scripts/
└── fonts/
```

> 压缩包不包含 `.env`、`data/settings.json`、Prowlarr/qBittorrent 配置和媒体文件，避免泄露密钥和携带缓存。

## 3. 启动

在项目目录打开 PowerShell：

```powershell
cd "C:\Users\你的用户名\media-automation"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

也可以直接双击：

```text
scripts\start.bat
```

脚本会：

1. 创建 `data`、`media`、`prowlarr/config`、`qbittorrent/config`
2. 从 `.env.example` 复制 `.env`
3. 检查 Docker Desktop，必要时尝试启动
4. 启动 worker、Prowlarr、qBittorrent、115-Station

第一次启动需要构建 worker 镜像，会下载 Python 依赖和 ffmpeg，通常需要几分钟。看到四个容器都 Up 即可。启动脚本会等待几秒再打印 qBittorrent 临时密码。

## 4. 首次配置

### 4.1 打开服务

- 搜索 / 任务 / 设置：<http://127.0.0.1:8787>
- Prowlarr：<http://127.0.0.1:9696>
- qBittorrent：<http://127.0.0.1:8081>
- 115-Station（可选）：<http://127.0.0.1:6060>

### 4.2 索引器（Prowlarr）

1. 在项目目录执行，一次性接入推荐索引器（已存在的会自动跳过）：

   ```powershell
   .\scripts\indexers.ps1 add
   ```

2. 需要私有 PT 站点或 Cloudflare 站点时，再打开 <http://127.0.0.1:9696>，在 **Indexers → Add Indexer** 手动添加。
3. 打开 **Settings → General**，复制 **API Key**（第 4.4 步要用）。

日常查看和自检：

```powershell
.\scripts\indexers.ps1 list     # 已接入的索引器
.\scripts\indexers.ps1 test     # 逐个测试连通性
.\scripts\indexers.ps1 search "芙莉莲"
```

### 4.3 qBittorrent

获取临时密码：

```powershell
docker logs media-automation-qbittorrent 2>&1 | Select-String -Pattern "password"
```

打开 <http://127.0.0.1:8081>，用户名默认 `admin`，用临时密码登录，然后在 **Settings → Web UI** 修改密码。

### 4.4 本服务

打开 <http://127.0.0.1:8787/setup>：

- Prowlarr 地址：`http://prowlarr:9696`
- Prowlarr API Key：粘贴刚才复制的 Key
- qBittorrent 地址：`http://qbittorrent:8081`
- qBittorrent 用户名 / 密码：填你刚修改的密码
- Telegram Token：可选
- 翻译接口：Ollama / DeepSeek / 其他 OpenAI 兼容接口
- 手机访问地址：填这台电脑的局域网 IP，例如 `http://192.168.1.20:8787`

保存后，如果修改了 Telegram Token，执行：

```powershell
docker compose restart worker
```

## 5. 手机访问

一键放行并打印手机地址（右键「以管理员身份运行」，或先开管理员 PowerShell 再执行）：

```powershell
.\scripts\open-lan.ps1
```

脚本会加一条**只对局域网**的入站规则（TCP 8787），并打印形如 `http://10.16.1.93:8787` 的地址和登录信息。

手动做的话：

```powershell
ipconfig
```

找到当前网卡的 **IPv4 地址**，在手机浏览器打开 `http://<这个IP>:8787`；如果之前在设置页填过“手机访问地址”，也改成同样的地址（Telegram 下载链接会用它）。

Windows Defender 防火墙需要允许：

- TCP 8787（本服务）
- TCP 9696（Prowlarr）
- TCP 8081（qBittorrent）
- TCP/UDP 6881（BT 端口）

只允许局域网/子网即可，不建议直接暴露到公网。手机打不开时先确认手机和电脑在同一子网，再看电脑有没有开 VPN/Clash 的 TUN 模式、路由器的「AP 隔离」有没有关。

## 6. 停止与重启

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop.ps1
```

或双击 `scripts\stop.bat`。脚本会 `docker compose down --timeout 60`，给 qBittorrent 留时间把断点写进配置。

重启电脑后，先启动 Docker Desktop，再运行 `start.ps1`。

### 下载中要关机

1. 关机前先停服务：

   ```powershell
   .\scripts\stop.ps1
   ```

2. 开机后启动 Docker Desktop，再执行：

   ```powershell
   .\scripts\start.ps1
   ```

3. 没下完的任务会自动接着下（worker 启动时重新接管 `downloading` 状态的任务）。进度可能有 0.1%~0.5% 回退，qBittorrent 会先校验分片再继续，属于正常现象。

数据都在本地，不会丢：断点在 `qbittorrent/config/`，半成品在 `media/downloads/`，任务状态在 `data/jobs.json`。

关机期间下载会停。想让下载在关机时继续，只能用云端离线下载（115-Station：磁力交给 115 云端下完，再从 115 取回）。

想开机自动恢复，需要两件事（默认都没开，需要你手动同意）：

1. Docker Desktop → Settings → General → 勾选 **Start Docker Desktop when you sign in**；
2. 把 `scripts\start.ps1` 的快捷方式放进 `shell:startup`（Win+R 输入 `shell:startup`）。

## 7. 更新代码

保留以下内容，不要删除：

- `.env`
- `data/settings.json`
- `prowlarr/config/`
- `qbittorrent/config/`
- `media/`

用新版代码覆盖其他文件，然后执行：

```powershell
docker compose build worker
docker compose up -d
```

如果只改网页/配置，不需要重建；如果改了 `worker/*.py`、`Dockerfile`、`requirements.txt`，必须重建。

## 8. 数据与备份

| 内容 | 路径 |
|---|---|
| Telegram / 翻译 / 下载配置 | `data/settings.json` |
| 任务状态 | `data/jobs.json` |
| Prowlarr 索引器和 API Key | `prowlarr/config/` |
| qBittorrent 密码和任务配置 | `qbittorrent/config/` |
| 下载中文件 | `media/downloads/` |
| 待处理 / 输出 | `media/inbox/`、`media/output/` |
| 成品自动归档 | `D:\MediaDownloads\`（`ARCHIVE_HOST_DIR` 可改） |

备份时把 `data`、`prowlarr/config`、`qbittorrent/config` 和 `media/output` 复制走即可。

## 9. 常见问题

### 构建卡在 ffmpeg 下载

Dockerfile 会从 GitHub 下载对应架构的静态 ffmpeg。GitHub 不可达时，在 `.env` 填一个可访问的同名镜像地址：

```env
FFMPEG_URL=https://你的镜像地址/ffmpeg-master-latest-linux64-gpl.tar.xz
```

然后：

```powershell
docker compose build --no-cache worker
docker compose up -d worker
```

### Docker 拉取镜像很慢

Docker Desktop → Settings → Resources → Proxies，填写代理；或在 `.env` 设置：

```env
MEDIA_HTTP_PROXY=http://host.docker.internal:7897
```

具体端口按你的 Clash / VPN 实际端口修改。

### 项目在 D 盘

Docker Desktop → Settings → Resources → File sharing，把 D 盘加入共享，然后重新启动。

### 端口被占用

修改 `docker-compose.yml` 左侧端口，例如：

```yaml
ports:
  - "8788:8787"
```

同时把 `.env` 里的 `BASE_URL` 改成新端口。

### 搜索没有结果

先确认索引器接好了：

```powershell
.\scripts\indexers.ps1 status
.\scripts\indexers.ps1 test
```

`索引器：0 个` 说明还没执行 `.\scripts\indexers.ps1 add`；如果测试结果全是 `blocked by CloudFlare Protection`，需要给 Prowlarr 配置 FlareSolverr 或代理（Prowlarr → Settings → Indexers → Indexer Proxies）。

如果测试结果全是 `SSL connection could not be established` / DNS 错误，**通常是代理没启动**（开机后最常见）：Prowlarr 通过 `.env` 里的 `MEDIA_HTTP_PROXY` 访问墙外站点。先启动 Clash Verge，再确认端口在监听：

```powershell
Get-NetTCPConnection -State Listen -LocalPort 7897
.\scripts\indexers.ps1 test
```

### 下载一直 0% 或很慢

任务卡现在会显示实际百分比、已下载/总大小和「做种 x/y」，先看这三个数：

- **做种 0/0**：这个种子没人做种，删掉任务换一个做种数更多的结果。
- **做种个位数、速度几十 KB/s**：冷门老种（AV 资源尤其常见），只能等或换种子。
- **做种显示很多，但实际只连上几个**：你的 6881 端口没有对外映射。在路由器上把 **TCP/UDP 6881** 转发到这台电脑，并在 Windows 防火墙放行，可连接的做种会明显变多。
- 外面开着 Clash 之类代理时，确认 BT 流量没走代理——P2P 走代理通常更慢甚至完全不通。

### Docker Desktop 起不来

- 确认 WSL2 已安装：`wsl --status`
- Docker Desktop → Troubleshoot → Restart
- 检查磁盘是否已满
- 必要时重启 Windows

## 10. 安全建议

- 8787 默认没有登录保护，建议在 `.env` 设置 `WEB_PASSWORD`
- `TELEGRAM_ALLOWED_USER_IDS` 填自己的 Telegram 数字 ID，不要留空
- qBittorrent 不要使用默认临时密码
- Prowlarr / qBittorrent 只绑定 `127.0.0.1`
- 不要把 8787 直接暴露到公网；需要远程访问时用 Tailscale、WireGuard 或反向代理加 HTTPS
- 只处理你有权获取和使用的内容
