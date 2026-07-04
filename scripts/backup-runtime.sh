#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${CHANNEL_QUERY_APP_DIR:-/opt/channel-query}"
BACKUP_DIR="${CHANNEL_QUERY_BACKUP_DIR:-/opt/channel-query-backups}"
REMOTE_TARGET="${CHANNEL_QUERY_BACKUP_REMOTE:-}"
PASSPHRASE_FILE="${CHANNEL_QUERY_BACKUP_PASSPHRASE_FILE:-}"
PASSPHRASE="${CHANNEL_QUERY_BACKUP_PASSPHRASE:-}"
KEEP_LOCAL="${CHANNEL_QUERY_BACKUP_KEEP:-168}"

if [ ! -d "$APP_DIR" ]; then
  echo "项目目录不存在：$APP_DIR"
  exit 1
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

PAYLOAD_DIR="$WORK_DIR/channel-query-runtime"
mkdir -p "$PAYLOAD_DIR"

copy_if_exists() {
  local source_path="$1"
  local target_path="$2"
  if [ -e "$source_path" ]; then
    mkdir -p "$(dirname "$PAYLOAD_DIR/$target_path")"
    cp -a "$source_path" "$PAYLOAD_DIR/$target_path"
  fi
}

copy_if_exists "$APP_DIR/.env" ".env"
copy_if_exists "$APP_DIR/telegram_config.json" "telegram_config.json"
copy_if_exists "$APP_DIR/service-account.json" "service-account.json"
copy_if_exists "$APP_DIR/google-oauth-client.json" "google-oauth-client.json"
copy_if_exists "$APP_DIR/docker-compose.yml" "docker-compose.yml"
copy_if_exists "$APP_DIR/docker-compose.deploy.yml" "docker-compose.deploy.yml"

copy_if_exists "$APP_DIR/config" "config"
copy_if_exists "$APP_DIR/data" "data"

for name in \
  .backend_token.enc \
  .backend_login.enc \
  .google_oauth_token.enc \
  .backend_token \
  .backend_token.dpapi \
  .google_oauth_token.dpapi \
  .channel_query_draft.json \
  .telegram_chats.json \
  channels.csv
do
  copy_if_exists "$APP_DIR/$name" "$name"
done

cat >"$PAYLOAD_DIR/RESTORE.md" <<'EOF'
# Channel Query Runtime Backup

This archive contains runtime files for disaster recovery. It may include:

- .env with CHANNEL_QUERY_MASTER_KEY
- telegram_config.json
- service-account.json or google-oauth-client.json
- encrypted backend / Google tokens
- Telegram known-chat registry
- Docker Compose config and mounted config/data directories

Keep it private. Anyone with this archive can likely run the bot.
EOF

cat >"$PAYLOAD_DIR/manifest.json" <<EOF
{
  "created_at": "$(date -Iseconds)",
  "hostname": "$(hostname 2>/dev/null || true)",
  "app_dir": "$APP_DIR",
  "contains_secrets": true
}
EOF

STAMP="$(date +%Y%m%d-%H%M%S)"
HOSTNAME_SAFE="$(hostname 2>/dev/null | tr -c 'A-Za-z0-9._-' '_' | sed 's/_*$//' || echo server)"
ARCHIVE_PATH="$BACKUP_DIR/channel-query-runtime-${HOSTNAME_SAFE}-${STAMP}.tar.gz"

tar -C "$WORK_DIR" -czf "$ARCHIVE_PATH" channel-query-runtime
chmod 600 "$ARCHIVE_PATH"
FINAL_PATH="$ARCHIVE_PATH"

if [ -n "$PASSPHRASE_FILE" ] || [ -n "$PASSPHRASE" ]; then
  if ! command -v openssl >/dev/null 2>&1; then
    echo "已创建未加密备份，但未找到 openssl，无法加密：$ARCHIVE_PATH"
    exit 1
  fi

  ENCRYPTED_PATH="${ARCHIVE_PATH}.enc"
  if [ -n "$PASSPHRASE_FILE" ]; then
    openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 \
      -in "$ARCHIVE_PATH" \
      -out "$ENCRYPTED_PATH" \
      -pass "file:$PASSPHRASE_FILE"
  else
    openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 \
      -in "$ARCHIVE_PATH" \
      -out "$ENCRYPTED_PATH" \
      -pass "pass:$PASSPHRASE"
  fi
  chmod 600 "$ENCRYPTED_PATH"
  rm -f "$ARCHIVE_PATH"
  FINAL_PATH="$ENCRYPTED_PATH"
fi

if [ -n "$REMOTE_TARGET" ]; then
  if command -v rsync >/dev/null 2>&1; then
    rsync -az "$FINAL_PATH" "$REMOTE_TARGET"
  else
    scp "$FINAL_PATH" "$REMOTE_TARGET"
  fi
fi

if [[ "$KEEP_LOCAL" =~ ^[0-9]+$ ]] && [ "$KEEP_LOCAL" -gt 0 ]; then
  mapfile -t backup_files < <(find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'channel-query-runtime-*.tar.gz' -o -name 'channel-query-runtime-*.tar.gz.enc' \) | sort)
  if [ "${#backup_files[@]}" -gt "$KEEP_LOCAL" ]; then
    remove_count=$(("${#backup_files[@]}" - KEEP_LOCAL))
    for ((i = 0; i < remove_count; i++)); do
      rm -f "${backup_files[$i]}"
    done
  fi
fi

echo "$FINAL_PATH"
