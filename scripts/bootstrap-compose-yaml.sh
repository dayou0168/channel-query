#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="${CHANNEL_QUERY_REPO_OWNER:-dayou0168}"
REPO_NAME="${CHANNEL_QUERY_REPO_NAME:-channel-query}"
REPO_BRANCH="${CHANNEL_QUERY_BRANCH:-main}"
APP_DIR="${CHANNEL_QUERY_APP_DIR:-/opt/channel-query}"
RAW_BASE="${CHANNEL_QUERY_RAW_BASE:-https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${REPO_BRANCH}}"
SKIP_UPGRADE="${CHANNEL_QUERY_SKIP_UPGRADE:-0}"
GITHUB_TOKEN_VALUE="${CHANNEL_QUERY_GITHUB_TOKEN:-${GITHUB_TOKEN:-${GH_TOKEN:-}}}"

if [ "${EUID}" -ne 0 ]; then
  echo "请使用 root 执行，例如：curl ... | sudo bash"
  exit 1
fi

download() {
  local url="$1"
  local output="$2"
  if [ -n "$GITHUB_TOKEN_VALUE" ]; then
    curl -fsSL -H "Authorization: Bearer ${GITHUB_TOKEN_VALUE}" "$url" -o "$output"
  else
    curl -fsSL "$url" -o "$output"
  fi
}

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
  apt-get install -y ca-certificates curl docker.io docker-compose-plugin
  systemctl enable --now docker
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

prepare_files() {
  mkdir -p "$APP_DIR/config" "$APP_DIR/data"
  chmod 700 "$APP_DIR/data"

  download "${RAW_BASE}/docker-compose.deploy.yml" "$APP_DIR/docker-compose.yml"

  if [ ! -f "$APP_DIR/.env" ]; then
    printf "CHANNEL_QUERY_MASTER_KEY=%s\n" "$(generate_fernet_key)" >"$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
  fi

  if [ ! -f "$APP_DIR/config/telegram_config.json" ]; then
    download "${RAW_BASE}/telegram_config.example.json" "$APP_DIR/config/telegram_config.json"
    sed -i 's|"service_account_file": ""|"service_account_file": "/config/service-account.json"|' "$APP_DIR/config/telegram_config.json"
    chmod 600 "$APP_DIR/config/telegram_config.json"
  fi
}

maybe_login_ghcr() {
  if [ -n "$GITHUB_TOKEN_VALUE" ]; then
    echo "$GITHUB_TOKEN_VALUE" | docker login ghcr.io -u "$REPO_OWNER" --password-stdin >/dev/null 2>&1 || {
      echo "GHCR 登录失败。如果镜像是私有的，请确认 token 有 Packages: Read 权限。"
    }
  fi
}

maybe_start_bot() {
  if grep -q "replace_with_botfather_token\|your_sheet_id" "$APP_DIR/config/telegram_config.json"; then
    echo "config/telegram_config.json 仍是模板内容，已下载 compose 文件但暂不启动机器人。"
    return
  fi
  compose up -d bot
}

install_system_packages
prepare_files
maybe_login_ghcr
compose pull
maybe_start_bot

echo
echo "Docker Compose YAML 部署完成。"
echo "项目目录：${APP_DIR}"
echo "Compose 文件：${APP_DIR}/docker-compose.yml"
echo
echo "下一步："
echo "1. 编辑 ${APP_DIR}/config/telegram_config.json"
echo "2. 上传 ${APP_DIR}/config/service-account.json，并把 Google 表格共享给 client_email"
echo "3. 启动机器人：cd ${APP_DIR} && docker compose up -d bot"
echo "4. 如需网页工具：cd ${APP_DIR} && docker compose --profile web up -d web"
echo "5. 查看日志：cd ${APP_DIR} && docker compose logs -f bot"
