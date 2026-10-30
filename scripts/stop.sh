#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
DOCKER_BIN="$(command -v docker || true)"
if [ -z "$DOCKER_BIN" ] && [ -x /Applications/Docker.app/Contents/Resources/bin/docker ]; then
  DOCKER_BIN=/Applications/Docker.app/Contents/Resources/bin/docker
fi
if [ -z "$DOCKER_BIN" ]; then
  echo "找不到 Docker，请安装 Docker Desktop。" >&2
  exit 127
fi
export PATH="$(dirname "$DOCKER_BIN"):$PATH"
"$DOCKER_BIN" compose --profile station down --timeout 60
