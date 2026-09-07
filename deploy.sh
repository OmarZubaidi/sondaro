#!/usr/bin/env bash
# Sync this folder to the server and rebuild. Same command for first install
# and every update afterwards.
#
# `docker compose pull` is a no-op for a locally-built image, so this script is
# the update path — a pull-based updater will never rebuild it.
set -euo pipefail

HOST="${SONDARO_HOST:?not set — the deploy target, e.g. SONDARO_HOST=you@your-vm ./deploy.sh}"
DATA_DIR="${SONDARO_DATA_DIR:-/appdata/sondaro}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/"

echo "==> preparing ${HOST}"
# -t so the rsync install below can prompt for a sudo password. Ubuntu server
# images don't ship rsync, and the sync step is two lines away.
ssh -t "$HOST" '
  set -e
  command -v rsync >/dev/null || sudo apt-get install -y rsync
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
  if ssh "$HOST" "test -s '$DATA_DIR/sondaro.db'" 2>/dev/null; then
    echo "==> the server already has a database, leaving it alone"
  else
    echo "==> seeding the server with your local cache"
    # checkpoint first so the -wal contents are folded into the file we copy
    sqlite3 "$LOCAL_DB" 'PRAGMA wal_checkpoint(TRUNCATE);' >/dev/null 2>&1 || true
    # Land it somewhere writable without sudo, then do every privileged step in
    # a single `ssh -t`: sudo needs a terminal to prompt for a password, and a
    # second session would be a second tty and so a second prompt.
    scp -q "$LOCAL_DB" "$HOST:/tmp/sondaro-seed.db"
    echo "    (sudo on the server — it may ask for your password)"
    ssh -t "$HOST" "
      set -e
      sudo mkdir -p '$DATA_DIR'
      sudo mv /tmp/sondaro-seed.db '$DATA_DIR/sondaro.db'
      sudo chown -R 3002:3002 '$DATA_DIR'
    "
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
