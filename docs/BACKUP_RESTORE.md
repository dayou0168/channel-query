# 备份与恢复

这个文档用于灾备：如果当前服务器故障，在新服务器导入备份后，让机器人尽量和之前一样工作。

## 结论

必须备份的是运行时配置和密钥：

- `.env`：里面的 `CHANNEL_QUERY_MASTER_KEY` 用来解密本地加密文件。
- `telegram_config.json` 或 `config/telegram_config.json`：里面有 Bot Token、后台地址、表格地址等。
- `service-account.json` 或 `google-oauth-client.json`：Google 表格读取凭证。
- `.backend_token.enc`、`.backend_login.enc`、`.google_oauth_token.enc`：后台登录和 Google OAuth 的加密状态。
- `data/`：Docker 部署时的加密状态、群登记文件和备份快照。
- `.telegram_chats.json`：裸机部署时记录到的已知群/私聊。

Telegram 群组关系和管理员权限不在你的服务器本地，它们存放在 Telegram 服务器。只要新服务器继续使用同一个 Bot Token，并且机器人没有被移出原来的群，新服务器启动后就会继续在原群工作。

如果 Bot Token 被重置，或者机器人被踢出群，就不能靠本地备份自动恢复；需要重新把机器人拉进群并重新分配管理员权限。

## Telegram 状态能备份什么

项目里有两个备份工具：

1. `scripts/backup-runtime.sh`

   创建完整灾备包，用于迁移到新服务器继续运行。这个包包含敏感文件。

2. `scripts/backup-telegram-state.py`

   通过 Telegram Bot API 导出可读取的机器人状态，例如机器人资料、命令、菜单、默认管理员权限、已知群的管理员列表、群人数、机器人在群里的权限状态。

Telegram Bot API 不能从零列出机器人加入过的所有群，也不能列出群内所有普通成员。项目只能备份机器人运行期间见过的群，或者收到 `my_chat_member` 更新的群。官方 Bot API 文档里，`getUpdates` 需要指定 `allowed_updates` 才能接收对应更新，群信息类接口也都需要已知的 `chat_id`。

官方文档：

- <https://core.telegram.org/bots/api#getupdates>
- <https://core.telegram.org/bots/api#getchat>
- <https://core.telegram.org/bots/api#getchatadministrators>

## 自动记录群

机器人现在默认使用：

```json
"telegram_allowed_updates": ["message", "my_chat_member"]
```

这样它会自动记录：

- 群成员发送消息时的群 ID、群名、群类型。
- 机器人被拉进群、踢出群、权限变化时的状态。

默认登记文件：

- 裸机部署：`/opt/channel-query/.telegram_chats.json`
- Docker 部署：`/opt/channel-query/data/.telegram_chats.json`

如果已有群以前没有被记录，让群里随便发一条机器人能看到的消息，或者把机器人移出后重新拉进群，就会登记到文件里。

## 创建灾备包

裸机或 Docker Compose 都可以在宿主机执行：

```bash
sudo CHANNEL_QUERY_APP_DIR=/opt/channel-query \
  CHANNEL_QUERY_BACKUP_DIR=/opt/channel-query-backups \
  /opt/channel-query/scripts/backup-runtime.sh
```

生成的文件类似：

```text
/opt/channel-query-backups/channel-query-runtime-server-20260704-120000.tar.gz
```

这个文件包含敏感配置。建议加密：

```bash
sudo sh -c 'umask 077; openssl rand -base64 48 > /root/.channel-query-backup-passphrase'

sudo CHANNEL_QUERY_APP_DIR=/opt/channel-query \
  CHANNEL_QUERY_BACKUP_DIR=/opt/channel-query-backups \
  CHANNEL_QUERY_BACKUP_PASSPHRASE_FILE=/root/.channel-query-backup-passphrase \
  /opt/channel-query/scripts/backup-runtime.sh
```

生成的文件会变成：

```text
channel-query-runtime-server-20260704-120000.tar.gz.enc
```

密码文件也必须另外安全保存。如果丢了，`.enc` 备份无法解密。

## 传到备份服务器

先在主服务器配置到备份服务器的 SSH key，然后执行：

```bash
sudo CHANNEL_QUERY_APP_DIR=/opt/channel-query \
  CHANNEL_QUERY_BACKUP_DIR=/opt/channel-query-backups \
  CHANNEL_QUERY_BACKUP_PASSPHRASE_FILE=/root/.channel-query-backup-passphrase \
  CHANNEL_QUERY_BACKUP_REMOTE=backup-user@备份服务器IP:/srv/backups/channel-query/ \
  /opt/channel-query/scripts/backup-runtime.sh
```

`CHANNEL_QUERY_BACKUP_REMOTE` 支持 `rsync/scp` 格式。推荐备份服务器上的目录权限只给备份账号读取。

本地默认保留最近 168 个运行时灾备包。可以通过 `CHANNEL_QUERY_BACKUP_KEEP` 调整，例如按小时备份时保留 30 天：

```bash
CHANNEL_QUERY_BACKUP_KEEP=720
```

## 定时自动备份

编辑 root 的定时任务：

```bash
sudo crontab -e
```

每小时备份一次：

```cron
10 * * * * CHANNEL_QUERY_APP_DIR=/opt/channel-query CHANNEL_QUERY_BACKUP_DIR=/opt/channel-query-backups CHANNEL_QUERY_BACKUP_PASSPHRASE_FILE=/root/.channel-query-backup-passphrase CHANNEL_QUERY_BACKUP_REMOTE=backup-user@备份服务器IP:/srv/backups/channel-query/ /opt/channel-query/scripts/backup-runtime.sh >> /var/log/channel-query-backup.log 2>&1
```

查看备份日志：

```bash
sudo tail -f /var/log/channel-query-backup.log
```

## 创建 Telegram 状态快照

Docker Compose：

```bash
cd /opt/channel-query
sudo docker compose --profile backup run --rm telegram-state-backup
```

裸机：

```bash
cd /opt/channel-query
set -a
source .env
set +a
.venv/bin/python scripts/backup-telegram-state.py --config telegram_config.json
```

默认输出：

```text
Docker：/opt/channel-query/data/telegram-state-backups/telegram-state-latest.json
裸机：/opt/channel-query/telegram-state-backups/telegram-state-latest.json
```

这个快照用于检查群、命令、权限状态，不等于完整灾备。完整迁移仍以 `backup-runtime.sh` 生成的灾备包为准。

## 恢复到新服务器

先在新服务器安装项目，但暂时不要启动机器人。然后把备份包和密码文件传到新服务器。

恢复加密备份：

```bash
sudo CHANNEL_QUERY_APP_DIR=/opt/channel-query \
  CHANNEL_QUERY_BACKUP_PASSPHRASE_FILE=/root/.channel-query-backup-passphrase \
  /opt/channel-query/scripts/restore-runtime.sh /root/channel-query-runtime-server-20260704-120000.tar.gz.enc
```

恢复未加密备份：

```bash
sudo CHANNEL_QUERY_APP_DIR=/opt/channel-query \
  /opt/channel-query/scripts/restore-runtime.sh /root/channel-query-runtime-server-20260704-120000.tar.gz
```

重启机器人：

裸机：

```bash
sudo systemctl restart channel-query-bot
sudo journalctl -u channel-query-bot -f
```

Docker Compose：

```bash
cd /opt/channel-query
sudo docker compose up -d bot
sudo docker compose logs -f bot
```

恢复后验证：

1. 在原来的 Telegram 群里发送一个 WPPChat 账号。
2. 机器人能回复查询结果，说明 Bot Token、后台凭证、Google 表格凭证都恢复成功。
3. 如果机器人没有回应，先确认原群里机器人没有被移除，BotFather 的 Privacy Mode 仍然关闭。
