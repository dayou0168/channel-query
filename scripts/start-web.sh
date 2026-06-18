#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8766}"

cd "$APP_DIR"

set -a
source .env
set +a

exec .venv/bin/python channel_query_app.py --host "$HOST" --port "$PORT"
