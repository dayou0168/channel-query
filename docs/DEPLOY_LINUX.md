# Linux 服务器部署流程

以下流程适合 Ubuntu / Debian 服务器。

如果你只想按推荐方式快速安装，先看：

```text
docs/INSTALL.md
```

本文件保留更细的手动部署和排查流程。

## 1. 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git openssl rsync
```

如果创建虚拟环境时报错 `ensurepip is not available`，继续执行：

```bash
sudo apt install -y python3.12-venv
```

如果你的系统不是 Python 3.12，把命令里的版本号换成实际版本。

## 2. 下载项目

```bash
cd /opt
sudo git clone https://github.com/你的GitHub用户名/channel-query.git channel-query
sudo chown -R root:root /opt/channel-query
cd /opt/channel-query
```

如果还没有上传 GitHub，也可以先用 `scp` 把项目传到 `/opt/channel-query`。

## 3. 安装 Python 依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m py_compile channel_query_app.py telegram_bot.py
```

也可以用脚本：

```bash
chmod +x scripts/*.sh
sudo ./scripts/install.sh
```

## 4. 配置加密密钥

生成服务器主密钥：

```bash
cd /opt/channel-query
.venv/bin/python channel_query_app.py --generate-master-key
```

创建 `.env`：

```bash
cp .env.example .env
nano .env
```

把生成的密钥填到：

```text
CHANNEL_QUERY_MASTER_KEY=这里填生成的密钥
```

限制权限：

```bash
chmod 600 /opt/channel-query/.env
```

## 5. 配置 Telegram 机器人

复制模板：

```bash
cp telegram_config.example.json telegram_config.json
nano telegram_config.json
```

填写：

```json
{
  "telegram_bot_token": "从BotFather拿到的token",
  "telegram_api_base": "https://api.telegram.org",
  "telegram_allowed_updates": ["message", "my_chat_member"],
  "telegram_chat_registry_file": "",
  "backend_base": "https://zhheew.bw009.com",
  "backend_token": "",
  "sheet_url": "你的Google表格链接",
  "sheet_csv_path": "",
  "service_account_file": "/opt/channel-query/service-account.json"
}
```

`telegram_config.json` 不要上传 GitHub。

如果服务器访问 Telegram 官方接口不稳定，可以把 `telegram_api_base` 改成你自己的 Telegram Bot API 反代地址，例如：

```json
"telegram_api_base": "https://你的telegram-api反代域名"
```

## 6. 配置 Google 服务账号

把 Google Cloud 下载的服务账号 JSON 上传到：

```text
/opt/channel-query/service-account.json
```

限制权限：

```bash
chmod 600 /opt/channel-query/service-account.json
```

然后打开 Google 表格，点“共享”，把表格共享给 JSON 文件里的 `client_email`，权限选“查看者”。

## 7. 首次登录后台并保存加密 token

启动网页工具：

```bash
cd /opt/channel-query
set -a
source .env
set +a
.venv/bin/python channel_query_app.py --host 127.0.0.1 --port 8766
```

在你自己的电脑打开 SSH 隧道：

```bash
ssh -L 8766:127.0.0.1:8766 root@服务器IP
```

浏览器打开：

```text
http://127.0.0.1:8766
```

在网页里登录后台。登录成功后会生成：

```text
.backend_token.enc
```

如果要自动处理后台 token 过期，还要保存后台账号密码和 TOTP 绑定密钥。注意这里要填 Google Authenticator 绑定时的密钥或 `otpauth://` 链接，不是当前 6 位验证码。

成功后会生成：

```text
.backend_login.enc
```

## 8. 启动 systemd 服务

如果已经运行过 `scripts/install.sh`，服务文件会自动创建。也可以手动创建：

```bash
sudo nano /etc/systemd/system/channel-query-bot.service
```

内容：

```ini
[Unit]
Description=Channel Query Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/channel-query
EnvironmentFile=/opt/channel-query/.env
ExecStart=/opt/channel-query/.venv/bin/python /opt/channel-query/telegram_bot.py --config /opt/channel-query/telegram_config.json
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now channel-query-bot
```

查看状态：

```bash
sudo systemctl status channel-query-bot --no-pager
sudo journalctl -u channel-query-bot -f
```

## 9. 备份与恢复

完整流程看：

```text
docs/BACKUP_RESTORE.md
```

创建运行时灾备包：

```bash
sudo CHANNEL_QUERY_APP_DIR=/opt/channel-query /opt/channel-query/scripts/backup-runtime.sh
```

如果需要加密并传到另一台备份服务器：

```bash
sudo sh -c 'umask 077; openssl rand -base64 48 > /root/.channel-query-backup-passphrase'
sudo CHANNEL_QUERY_APP_DIR=/opt/channel-query \
  CHANNEL_QUERY_BACKUP_DIR=/opt/channel-query-backups \
  CHANNEL_QUERY_BACKUP_PASSPHRASE_FILE=/root/.channel-query-backup-passphrase \
  CHANNEL_QUERY_BACKUP_REMOTE=backup-user@备份服务器IP:/srv/backups/channel-query/ \
  /opt/channel-query/scripts/backup-runtime.sh
```

恢复到新服务器：

```bash
sudo CHANNEL_QUERY_APP_DIR=/opt/channel-query \
  CHANNEL_QUERY_BACKUP_PASSPHRASE_FILE=/root/.channel-query-backup-passphrase \
  /opt/channel-query/scripts/restore-runtime.sh /root/channel-query-runtime-xxxx.tar.gz.enc
```

恢复后重启：

```bash
sudo systemctl restart channel-query-bot
```

## 10. 更新代码

以后代码更新：

```bash
cd /opt/channel-query
sudo git pull
source .venv/bin/activate
pip install -r requirements.txt
python -m py_compile channel_query_app.py telegram_bot.py scripts/backup-telegram-state.py
sudo systemctl restart channel-query-bot
```

或使用：

```bash
sudo ./scripts/update.sh
```
