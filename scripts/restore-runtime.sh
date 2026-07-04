#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${CHANNEL_QUERY_APP_DIR:-/opt/channel-query}"
PASSPHRASE_FILE="${CHANNEL_QUERY_BACKUP_PASSPHRASE_FILE:-}"
PASSPHRASE="${CHANNEL_QUERY_BACKUP_PASSPHRASE:-}"

if [ $# -lt 1 ]; then
  echo "用法：CHANNEL_QUERY_APP_DIR=/opt/channel-query bash scripts/restore-runtime.sh 备份文件.tar.gz[.enc]"
  exit 1
fi

BACKUP_FILE="$1"
if [ ! -f "$BACKUP_FILE" ]; then
  echo "备份文件不存在：$BACKUP_FILE"
  exit 1
fi

WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

TAR_PATH="$WORK_DIR/runtime.tar.gz"
case "$BACKUP_FILE" in
  *.enc)
    if ! command -v openssl >/dev/null 2>&1; then
      echo "未找到 openssl，无法解密备份。"
      exit 1
    fi
    if [ -n "$PASSPHRASE_FILE" ]; then
      openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
        -in "$BACKUP_FILE" \
        -out "$TAR_PATH" \
        -pass "file:$PASSPHRASE_FILE"
    elif [ -n "$PASSPHRASE" ]; then
      openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
        -in "$BACKUP_FILE" \
        -out "$TAR_PATH" \
        -pass "pass:$PASSPHRASE"
    else
      echo "这是加密备份。请先设置 CHANNEL_QUERY_BACKUP_PASSPHRASE_FILE 或 CHANNEL_QUERY_BACKUP_PASSPHRASE。"
      exit 1
    fi
    ;;
  *)
    cp "$BACKUP_FILE" "$TAR_PATH"
    ;;
esac

tar -C "$WORK_DIR" -xzf "$TAR_PATH"
PAYLOAD_DIR="$WORK_DIR/channel-query-runtime"
if [ ! -d "$PAYLOAD_DIR" ]; then
  echo "备份格式不正确：没有找到 channel-query-runtime 目录。"
  exit 1
fi

mkdir -p "$APP_DIR"
cp -a "$PAYLOAD_DIR/." "$APP_DIR/"

chmod 600 "$APP_DIR/.env" 2>/dev/null || true
chmod 600 "$APP_DIR/telegram_config.json" 2>/dev/null || true
chmod 600 "$APP_DIR/service-account.json" 2>/dev/null || true
chmod 600 "$APP_DIR/google-oauth-client.json" 2>/dev/null || true
chmod 700 "$APP_DIR/config" 2>/dev/null || true
chmod 700 "$APP_DIR/data" 2>/dev/null || true
chmod 600 "$APP_DIR/config/telegram_config.json" 2>/dev/null || true
chmod 600 "$APP_DIR/config/service-account.json" 2>/dev/null || true
chmod 600 "$APP_DIR/config/google-oauth-client.json" 2>/dev/null || true

echo "已恢复到：$APP_DIR"
echo "请检查配置后重启机器人。裸机：systemctl restart channel-query-bot；Docker：cd $APP_DIR && docker compose up -d bot"
