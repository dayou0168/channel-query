#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="channel-query-bot"

cd "$APP_DIR"

if [ -d ".git" ]; then
  git pull
fi

source .venv/bin/activate
pip install -r requirements.txt
python -m py_compile channel_query_app.py telegram_bot.py scripts/backup-telegram-state.py

systemctl restart ${SERVICE_NAME}
systemctl status ${SERVICE_NAME} --no-pager
