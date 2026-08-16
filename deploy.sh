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

# A local test run builds a real index: hundreds of API calls, and for JamBase
# some of them billable. Carry it over on first deploy rather than paying twice.
# Only ever seeds an empty target — an existing database on the server is never
# overwritten, since by then it's the newer one.
LOCAL_DB="${SRC}.data/sondaro.db"
if [ -f "$LOCAL_DB" ]; then
  if ssh "$HOST" 'test -s /appdata/sondaro/sondaro.db' 2>/dev/null; then
    echo "==> the server already has a database, leaving it alone"
  else
    echo "==> seeding the server with your local cache"
    # checkpoint first so the -wal contents are folded into the file we copy
    sqlite3 "$LOCAL_DB" 'PRAGMA wal_checkpoint(TRUNCATE);' >/dev/null 2>&1 || true
    ssh "$HOST" 'sudo mkdir -p /appdata/sondaro && sudo chown 3002:3002 /appdata/sondaro'
    scp -q "$LOCAL_DB" "$HOST:/tmp/sondaro-seed.db"
    ssh "$HOST" 'sudo mv /tmp/sondaro-seed.db /appdata/sondaro/sondaro.db \
      && sudo chown 3002:3002 /appdata/sondaro/sondaro.db'
  fi
fi

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
