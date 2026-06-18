#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${CHANNEL_QUERY_REPO_URL:-https://github.com/dayou0168/channel-query.git}"
SERVICE_NAME="${CHANNEL_QUERY_SERVICE_NAME:-channel-query-bot}"
SKIP_UPGRADE="${CHANNEL_QUERY_SKIP_UPGRADE:-0}"
GITHUB_TOKEN_VALUE="${CHANNEL_QUERY_GITHUB_TOKEN:-${GITHUB_TOKEN:-${GH_TOKEN:-}}}"

if [ "${EUID}" -ne 0 ]; then
  echo "请使用 root 执行，例如：sudo bash scripts/install-linux.sh"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
if [ -n "${CHANNEL_QUERY_APP_DIR:-}" ]; then
  APP_DIR="${CHANNEL_QUERY_APP_DIR}"
elif [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/../channel_query_app.py" ]; then
  APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  APP_DIR="/opt/channel-query"
fi

install_system_packages() {
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "当前脚本只支持 Debian / Ubuntu 系统。"
    exit 1
  fi

  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  if [ "$SKIP_UPGRADE" != "1" ]; then
    apt-get -y upgrade
  fi
  apt-get install -y ca-certificates curl git python3 python3-venv python3-pip
}

git_with_auth() {
  if [ -n "$GITHUB_TOKEN_VALUE" ]; then
    git -c "http.https://github.com/.extraheader=Authorization: Bearer ${GITHUB_TOKEN_VALUE}" "$@"
  else
    git "$@"
  fi
}

prepare_source() {
  if [ -d "$APP_DIR/.git" ]; then
    git_with_auth -C "$APP_DIR" pull --ff-only
    return
  fi

  if [ -f "$APP_DIR/channel_query_app.py" ]; then
    return
  fi

  mkdir -p "$(dirname "$APP_DIR")"
  git_with_auth clone "$REPO_URL" "$APP_DIR"
}

ensure_python_env() {
  cd "$APP_DIR"
  if [ ! -d ".venv" ]; then
    python3 -m venv .venv
  fi
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
  .venv/bin/python -m py_compile channel_query_app.py telegram_bot.py
}

generate_master_key() {
  "$APP_DIR/.venv/bin/python" "$APP_DIR/channel_query_app.py" --generate-master-key
}

ensure_env_file() {
  cd "$APP_DIR"
  if [ ! -f ".env" ]; then
    printf "CHANNEL_QUERY_MASTER_KEY=%s\n" "$(generate_master_key)" >.env
  elif grep -q "replace_with_generated_master_key" .env || ! grep -q "^CHANNEL_QUERY_MASTER_KEY=" .env; then
    local key
    key="$(generate_master_key)"
    if grep -q "^CHANNEL_QUERY_MASTER_KEY=" .env; then
      sed -i "s|^CHANNEL_QUERY_MASTER_KEY=.*|CHANNEL_QUERY_MASTER_KEY=${key}|" .env
    else
      printf "\nCHANNEL_QUERY_MASTER_KEY=%s\n" "$key" >>.env
    fi
  fi
  chmod 600 .env
}

ensure_config_file() {
  cd "$APP_DIR"
  if [ ! -f "telegram_config.json" ]; then
    cat >telegram_config.json <<JSON
{
  "telegram_bot_token": "123456:replace_with_botfather_token",
  "backend_base": "https://zhheew.bw009.com",
  "backend_token": "",
  "sheet_url": "https://docs.google.com/spreadsheets/d/your_sheet_id/edit?gid=0#gid=0",
  "sheet_csv_path": "",
  "service_account_file": "${APP_DIR}/service-account.json"
}
JSON
  fi
  chmod 600 telegram_config.json
}

install_systemd_service() {
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
  systemctl enable "${SERVICE_NAME}"
}

maybe_start_service() {
  if grep -q "replace_with_botfather_token\|your_sheet_id" "$APP_DIR/telegram_config.json"; then
    echo "telegram_config.json 仍是模板内容，暂不启动机器人。"
    return
  fi
  systemctl restart "${SERVICE_NAME}"
}

install_system_packages
prepare_source
ensure_python_env
ensure_env_file
ensure_config_file
install_systemd_service
maybe_start_service

echo
echo "裸机部署完成。"
echo "项目目录：${APP_DIR}"
echo "服务名：${SERVICE_NAME}"
echo
echo "下一步："
echo "1. 编辑 ${APP_DIR}/telegram_config.json"
echo "2. 上传 ${APP_DIR}/service-account.json，并把 Google 表格共享给 client_email"
echo "3. 如需网页登录后台保存 token，执行：${APP_DIR}/scripts/start-web.sh"
echo "4. 配置完成后启动机器人：systemctl restart ${SERVICE_NAME}"
echo "5. 查看日志：journalctl -u ${SERVICE_NAME} -f"
if [ -f /var/run/reboot-required ]; then
  echo
  echo "系统提示需要重启，建议安排时间执行：reboot"
fi
