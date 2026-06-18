#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="${CHANNEL_QUERY_REPO_OWNER:-dayou0168}"
REPO_NAME="${CHANNEL_QUERY_REPO_NAME:-channel-query}"
REPO_BRANCH="${CHANNEL_QUERY_BRANCH:-main}"
REPO_URL="${CHANNEL_QUERY_REPO_URL:-https://github.com/${REPO_OWNER}/${REPO_NAME}.git}"
APP_DIR="${CHANNEL_QUERY_APP_DIR:-/opt/channel-query}"
GITHUB_TOKEN_VALUE="${CHANNEL_QUERY_GITHUB_TOKEN:-${GITHUB_TOKEN:-${GH_TOKEN:-}}}"

if [ "${EUID}" -ne 0 ]; then
  echo "请使用 root 执行，例如：curl ... | sudo bash"
  exit 1
fi

install_bootstrap_packages() {
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "当前脚本只支持 Debian / Ubuntu 系统。"
    exit 1
  fi
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl git
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
    git_with_auth -C "$APP_DIR" fetch origin "$REPO_BRANCH"
    git_with_auth -C "$APP_DIR" checkout "$REPO_BRANCH"
    git_with_auth -C "$APP_DIR" pull --ff-only origin "$REPO_BRANCH"
    return
  fi

  if [ -e "$APP_DIR" ] && [ ! -f "$APP_DIR/channel_query_app.py" ]; then
    echo "${APP_DIR} 已存在，但不是 channel-query 项目目录。请先移走或设置 CHANNEL_QUERY_APP_DIR。"
    exit 1
  fi

  if [ ! -f "$APP_DIR/channel_query_app.py" ]; then
    mkdir -p "$(dirname "$APP_DIR")"
    git_with_auth clone --branch "$REPO_BRANCH" "$REPO_URL" "$APP_DIR"
  fi
}

install_bootstrap_packages
prepare_source

exec bash "$APP_DIR/scripts/install-linux.sh"
