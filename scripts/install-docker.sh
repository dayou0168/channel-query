#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${CHANNEL_QUERY_REPO_URL:-https://github.com/dayou0168/channel-query.git}"
SKIP_UPGRADE="${CHANNEL_QUERY_SKIP_UPGRADE:-0}"
GITHUB_TOKEN_VALUE="${CHANNEL_QUERY_GITHUB_TOKEN:-${GITHUB_TOKEN:-${GH_TOKEN:-}}}"

if [ "${EUID}" -ne 0 ]; then
  echo "请使用 root 执行，例如：sudo bash scripts/install-docker.sh"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
if [ -n "${CHANNEL_QUERY_APP_DIR:-}" ]; then
  APP_DIR="${CHANNEL_QUERY_APP_DIR}"
elif [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/../docker-compose.yml" ]; then
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
  apt-get install -y ca-certificates curl git docker.io docker-compose-plugin
  systemctl enable --now docker
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

  if [ -f "$APP_DIR/docker-compose.yml" ]; then
    return
  fi

  mkdir -p "$(dirname "$APP_DIR")"
  git_with_auth clone "$REPO_URL" "$APP_DIR"
}

compose() {
  cd "$APP_DIR"
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    echo "没有找到 Docker Compose。请确认 docker-compose-plugin 已安装。"
    exit 1
  fi
}

generate_fernet_key() {
  head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n'
}

ensure_runtime_files() {
  cd "$APP_DIR"
  mkdir -p config data
  chmod 700 data

  if [ ! -f ".env" ]; then
    printf "CHANNEL_QUERY_MASTER_KEY=%s\n" "$(generate_fernet_key)" >.env
  elif grep -q "replace_with_generated_master_key" .env || ! grep -q "^CHANNEL_QUERY_MASTER_KEY=" .env; then
    local key
    key="$(generate_fernet_key)"
    if grep -q "^CHANNEL_QUERY_MASTER_KEY=" .env; then
      sed -i "s|^CHANNEL_QUERY_MASTER_KEY=.*|CHANNEL_QUERY_MASTER_KEY=${key}|" .env
    else
      printf "\nCHANNEL_QUERY_MASTER_KEY=%s\n" "$key" >>.env
    fi
  fi
  chmod 600 .env

  if [ ! -f "config/telegram_config.json" ]; then
    cat >config/telegram_config.json <<JSON
{
  "telegram_bot_token": "123456:replace_with_botfather_token",
  "telegram_api_base": "https://api.telegram.org",
  "backend_base": "https://zhheew.bw009.com",
  "backend_token": "",
  "sheet_url": "https://docs.google.com/spreadsheets/d/your_sheet_id/edit?gid=0#gid=0",
  "sheet_csv_path": "",
  "service_account_file": "/config/service-account.json"
}
JSON
  fi
  chmod 600 config/telegram_config.json
}

maybe_start_bot() {
  if grep -q "replace_with_botfather_token\|your_sheet_id" "$APP_DIR/config/telegram_config.json"; then
    echo "config/telegram_config.json 仍是模板内容，暂不启动机器人。"
    return
  fi
  compose up -d bot
}

install_system_packages
prepare_source
ensure_runtime_files
compose build
maybe_start_bot

echo
echo "Docker Compose 部署完成。"
echo "项目目录：${APP_DIR}"
echo
echo "下一步："
echo "1. 编辑 ${APP_DIR}/config/telegram_config.json"
echo "2. 上传 ${APP_DIR}/config/service-account.json，并把 Google 表格共享给 client_email"
echo "3. 启动机器人：cd ${APP_DIR} && docker compose up -d bot"
echo "4. 如需网页工具：cd ${APP_DIR} && docker compose --profile web up -d web"
echo "5. 查看日志：cd ${APP_DIR} && docker compose logs -f bot"
if [ -f /var/run/reboot-required ]; then
  echo
  echo "系统提示需要重启，建议安排时间执行：reboot"
fi
