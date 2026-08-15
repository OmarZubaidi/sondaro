#!/usr/bin/env bash
# Sync this folder to the server and rebuild. Same command for first
# install and every update afterwards.
#
# `docker compose pull` is a no-op for a
# locally-built image, so this script is sondaro's update path, not sondaro-update.
set -euo pipefail

HOST="${SONDARO_HOST:-you@your-vm}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/"

echo "==> preparing ${HOST}"
ssh "$HOST" '
  set -e
  docker network inspect proxy >/dev/null 2>&1 || docker network create proxy
  mkdir -p ~/sondaro
'

echo "==> syncing source"
# --delete mirrors the tree so removed files actually disappear. .env is
# excluded from both the copy and the delete: it holds the API keys and must
# survive every deploy. This is the single most important line in the script.
rsync -az --delete \
  --exclude '.env' \
  --exclude 'node_modules' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.venv' \
  --exclude 'dist' \
  --exclude '*.db' \
  "$SRC" "$HOST:sondaro/"

echo "==> building and starting"
ssh "$HOST" '
  set -e
  cd ~/sondaro
  if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "!! created ~/sondaro/.env from the example."
    echo "!! fill in the API keys, then run this again."
    exit 1
  fi
  docker compose -p sondaro up -d --build
  docker image prune -f
'

echo "==> done"
