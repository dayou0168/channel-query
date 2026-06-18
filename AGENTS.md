# Codex 项目维护说明

请用中文和用户沟通。

开始任何开发前，先阅读：

- `docs/PROJECT_STATE.md`
- `docs/INSTALL.md`
- `docs/DEPLOY_LINUX.md`
- `README.md`

## 项目用途

这是 WPPChat 渠道查询工具和 Telegram 群机器人。群成员发送 WPPChat 账号，机器人查询后台用户列表，再用 Google 表格“来源编号”匹配“渠道编码”，最后回复账号、注册 IP、注册省份、注册来源、渠道编码等信息。

## 安全要求

不要提交、打印或覆盖这些文件：

- `.env`
- `telegram_config.json`
- `service-account.json`
- `google-oauth-client.json`
- `.backend_token.enc`
- `.backend_login.enc`
- `.google_oauth_token.enc`
- `channels.csv`
- `.channel_query_draft.json`

如果必须新增配置，优先更新示例文件，例如 `.env.example` 或 `telegram_config.example.json`。

## 验证要求

修改 Python 代码后至少运行：

```bash
python -m py_compile channel_query_app.py telegram_bot.py
```

修改 Linux 部署逻辑后，同步检查：

- `docs/INSTALL.md`
- `docs/DEPLOY_LINUX.md`
- `scripts/install.sh`
- `scripts/install-linux.sh`
- `scripts/install-docker.sh`
- `scripts/update.sh`

## GitHub 同步要求

用户要求：以后更新代码或项目文档后，同步更新到 GitHub。

默认流程：

1. 修改完成后先运行必要验证。
2. 检查 `git status -sb`，确认没有误提交敏感文件或无关文件。
3. 提交到当前分支。
4. 推送到 `origin/main`。

除非用户明确说“先不要提交”或“先不要推送”，否则每次完成修改都要同步到 GitHub。

## 服务器约定

生产服务器目录默认是：

```text
/opt/channel-query
```

systemd 服务名默认是：

```text
channel-query-bot
```

常用命令：

```bash
sudo systemctl restart channel-query-bot
sudo journalctl -u channel-query-bot -f
```
