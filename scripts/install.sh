#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="channel-query-bot"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$APP_DIR"

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt
python -m py_compile channel_query_app.py telegram_bot.py

if [ ! -f ".env" ]; then
  cp .env.example .env
  chmod 600 .env
  echo "已创建 .env，请执行：.venv/bin/python channel_query_app.py --generate-master-key"
  echo "然后把生成的密钥填入 .env 的 CHANNEL_QUERY_MASTER_KEY。"
fi

if [ ! -f "telegram_config.json" ]; then
  cp telegram_config.example.json telegram_config.json
  chmod 600 telegram_config.json
  echo "已创建 telegram_config.json，请填写 Telegram token、表格链接和服务账号 JSON 路径。"
fi

cat >/etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=Channel Query Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/telegram_bot.py --config ${APP_DIR}/telegram_config.json
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ${SERVICE_NAME}

echo "安装完成。"
echo "下一步："
echo "1. 编辑 ${APP_DIR}/.env"
echo "2. 编辑 ${APP_DIR}/telegram_config.json"
echo "3. 放置 ${APP_DIR}/service-account.json 并共享 Google 表格给 client_email"
echo "4. 执行：systemctl start ${SERVICE_NAME}"
