#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p data media/inbox media/output media/downloads fonts prowlarr/config qbittorrent/config
test -f .env || cp .env.example .env
DOCKER_BIN="$(command -v docker || true)"
if [ -z "$DOCKER_BIN" ] && [ -x /Applications/Docker.app/Contents/Resources/bin/docker ]; then
  DOCKER_BIN=/Applications/Docker.app/Contents/Resources/bin/docker
fi
if [ -z "$DOCKER_BIN" ]; then
  echo "找不到 Docker，请安装 Docker Desktop。" >&2
  exit 127
fi
export PATH="$(dirname "$DOCKER_BIN"):$PATH"
"$DOCKER_BIN" compose --profile station up -d worker station prowlarr qbittorrent flaresolverr jellyfin
echo "搜索/任务/配置：http://127.0.0.1:8787"
echo "Prowlarr 索引器：http://127.0.0.1:9696（首次先跑 scripts/indexers.sh add 批量接入）"
echo "qBittorrent：http://127.0.0.1:8081（临时密码见下方日志）"
echo "115-Station：http://127.0.0.1:6060"
"$DOCKER_BIN" logs media-automation-qbittorrent 2>&1 | grep -iE "password|密码" | tail -1 || true
"$DOCKER_BIN" compose ps
