# 重装系统后接手说明

更新时间：2026-07-10

这份文档用于本机重装系统、换对话窗口、换电脑或换服务器后继续维护项目。

## 仓库

```text
https://github.com/dayou0168/channel-query
```

当前约定：以后更新代码或文档后，默认提交并推送到 `origin/main`，除非用户明确说不要同步。

重装系统后先安装 Git / GitHub CLI，然后克隆仓库：

```bash
git clone https://github.com/dayou0168/channel-query.git
cd channel-query
```

如果仓库保持 Private，需要先登录 GitHub：

```bash
gh auth login
```

## 首先阅读

接手后按顺序看：

1. `AGENTS.md`
2. `docs/PROJECT_STATE.md`
3. `docs/INSTALL.md`
4. `docs/DEPLOY_LINUX.md`
5. `docs/BACKUP_RESTORE.md`
6. `docs/REINSTALL_HANDOFF.md`
7. `README.md`

## 当前项目状态

项目是 WPPChat 渠道查询工具和 Telegram 群机器人。

已支持：

- 群成员发送 WPPChat 账号，机器人按原消息回复查询结果。
- 查询字段包括账号、注册 IP、注册省份、注册来源、渠道编码等。
- 注册来源会标准化，例如 `https://615b19.xxx.top` 显示为 `615b19`。
- 支持 `查IP 172.15.217.52` 查询同注册 IP 下的账号和注册时间。
- 支持 Google 表格实时读取。
- 支持后台 token 加密保存。
- 支持保存后台账号密码和 TOTP 绑定密钥后自动续登录。
- 支持 `TELEGRAM_API_BASE` 自定义 Telegram Bot API 地址。
- Telegram 500/502/503/504 或网络超时时会自动退避重试。
- 支持自动登记机器人见过的 Telegram 群/私聊。
- 支持 Telegram 状态快照和运行时灾备包。

## 当前已知卡点

最近一次排查的后台域名：

```text
https://qiann.bw006.com
```

服务器侧证据：

```text
机器人服务器出口 IP：47.79.38.159
后台域名解析 IP：47.238.130.109
GET /：HTTP 200，前端页面正常
GET /api/login：HTTP 404，属于正常现象，因为登录接口是 POST
POST /api/login：HTTP 403 Access denied
```

结论：

```text
POST /api/login 在进入登录逻辑前被 nginx / WAF / 网关 / IP 白名单策略拒绝。
这不是账号密码、验证码、TOTP、Google 表格或机器人代码问题。
```

继续处理时优先让后台方确认：

```text
请放行服务器出口 IP 47.79.38.159 到 qiann.bw006.com 的 API 登录和用户列表接口：
POST /api/login
POST /api/im/imUserInfo/list
```

在后台没有放行前，不建议改机器人登录逻辑。

## 生产服务器运行时文件

这些文件不在 GitHub，需要从服务器灾备包恢复：

- `.env`
- `telegram_config.json` 或 `config/telegram_config.json`
- `service-account.json`
- `google-oauth-client.json`
- `.backend_token.enc`
- `.backend_login.enc`
- `.google_oauth_token.enc`
- `.telegram_chats.json`
- `data/`
- `channels.csv`

其中 `.env` 里的 `CHANNEL_QUERY_MASTER_KEY` 必须和 `.backend_token.enc`、`.backend_login.enc`、`.google_oauth_token.enc` 配套，否则无法解密。

## 重装前必须做的备份

如果重装的是运行机器人的 Linux 服务器，先创建运行时灾备包：

```bash
sudo CHANNEL_QUERY_APP_DIR=/opt/channel-query \
  CHANNEL_QUERY_BACKUP_DIR=/opt/channel-query-backups \
  /opt/channel-query/scripts/backup-runtime.sh
```

建议使用加密备份：

```bash
sudo sh -c 'umask 077; openssl rand -base64 48 > /root/.channel-query-backup-passphrase'

sudo CHANNEL_QUERY_APP_DIR=/opt/channel-query \
  CHANNEL_QUERY_BACKUP_DIR=/opt/channel-query-backups \
  CHANNEL_QUERY_BACKUP_PASSPHRASE_FILE=/root/.channel-query-backup-passphrase \
  /opt/channel-query/scripts/backup-runtime.sh
```

把下面两类文件保存到安全位置：

```text
channel-query-runtime-*.tar.gz.enc
/root/.channel-query-backup-passphrase
```

没有密码文件就无法解密 `.enc` 灾备包。

## 新服务器恢复

先按 `docs/INSTALL.md` 安装项目，再导入灾备包：

```bash
sudo CHANNEL_QUERY_APP_DIR=/opt/channel-query \
  CHANNEL_QUERY_BACKUP_PASSPHRASE_FILE=/root/.channel-query-backup-passphrase \
  /opt/channel-query/scripts/restore-runtime.sh /root/channel-query-runtime-xxxx.tar.gz.enc
```

裸机重启：

```bash
sudo systemctl restart channel-query-bot
sudo journalctl -u channel-query-bot -f
```

Docker Compose 重启：

```bash
cd /opt/channel-query
sudo docker compose up -d bot
sudo docker compose logs -f bot
```

## 重装本机后继续开发

Windows 本机重装后：

1. 安装 Git 和 GitHub CLI。
2. `gh auth login` 登录 GitHub。
3. 克隆本仓库。
4. 打开仓库后先读 `AGENTS.md` 和本文件。
5. 需要验证 Python 代码时运行：

```bash
python -m py_compile channel_query_app.py telegram_bot.py scripts/backup-telegram-state.py
```

如果修改 Linux 部署逻辑，还要同步检查：

- `docs/INSTALL.md`
- `docs/DEPLOY_LINUX.md`
- `scripts/install.sh`
- `scripts/bootstrap-linux.sh`
- `scripts/bootstrap-docker.sh`
- `scripts/bootstrap-compose-yaml.sh`
- `scripts/install-linux.sh`
- `scripts/install-docker.sh`
- `docker-compose.deploy.yml`
- `.github/workflows/docker-image.yml`
- `scripts/update.sh`

## 安全边界

不要把真实运行时文件提交到 GitHub。GitHub 里只保存代码、示例配置和文档。

真实 token、后台账号、Google 凭证、灾备包和加密密钥必须只保存在服务器或安全备份位置。
