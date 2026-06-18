# 项目状态说明

这份文件用于“固化项目”。以后即使换了对话窗口，把这个仓库和本文件发给 Codex，就可以继续接着做。

## 项目目标

群成员在 Telegram 群里发送 WPPChat 账号，机器人自动：

1. 到后台用户列表查询账号信息。
2. 取出注册 IP、注册省份、注册时间、注册来源。
3. 把注册来源标准化，例如 `https://615b19.utcjni7.top` 显示为 `615b19`。
4. 到 Google 表格里用“来源编号”匹配左侧“渠道编码”。
5. 回复发送者那条消息，并把账号、IP、注册来源、渠道编码用 Telegram 代码格式显示，方便单击复制。

机器人还支持同 IP 查询：

```text
查IP 172.15.217.52
```

返回这个注册 IP 下的所有账号和注册时间。

## 核心文件

- `channel_query_app.py`：网页工具和核心查询逻辑。
- `telegram_bot.py`：Telegram 群机器人。
- `telegram_config.example.json`：机器人配置模板。
- `.env.example`：服务器环境变量模板。
- `requirements.txt`：Python 依赖。
- `docs/INSTALL.md`：裸机 Linux 和 Docker Compose 两种一键部署方式。
- `docs/DEPLOY_LINUX.md`：Linux 服务器部署流程。
- `docs/GITHUB_UPLOAD.md`：上传 GitHub 流程。
- `Dockerfile`：Docker 镜像构建文件。
- `docker-compose.yml`：Docker Compose 服务定义，包含 `bot` 和可选 `web`。
- `scripts/install-linux.sh`：裸机 Linux 一键部署脚本。
- `scripts/install-docker.sh`：Docker Compose 一键部署脚本。
- `scripts/install.sh`：服务器首次安装辅助脚本。
- `scripts/update.sh`：服务器更新代码辅助脚本。
- `scripts/status.sh`：查看机器人状态和日志。
- `scripts/start-web.sh`：在服务器本机启动网页工具，用 SSH 隧道访问。

## 当前功能状态

- 支持批量 WPPChat 账号查询。
- 支持 Telegram 群内按消息回复。
- 支持账号、IP、注册来源、渠道编码单击复制。
- 支持注册省份清洗：`中国 江西 景德镇` 显示为 `江西 景德镇`，非中国地区完整显示。
- 支持 Google 表格实时读取，推荐使用服务账号 JSON。
- 支持后台 token 加密保存。
- 支持后台 token 过期后自动续登录，前提是已经保存后台账号密码和 TOTP 绑定密钥。
- 支持 `查IP` 命令查询同注册 IP 账号。
- 支持裸机 Linux 一键部署和 Docker Compose 一键部署。

## 后台接口

当前后台基础地址：

```text
https://zhheew.bw009.com
```

主要接口：

- 登录：`POST /api/login`
- 用户列表：`POST /api/im/imUserInfo/list`

用户列表查询会使用后台默认模糊查询逻辑，不做前端精确匹配。

## Google 表格

表格需要有一列：

```text
来源编号
```

渠道编码在“来源编号”左侧一列。

服务器部署推荐使用 Google 服务账号：

1. 在 Google Cloud 创建服务账号 JSON。
2. 把 Google 表格共享给 JSON 里的 `client_email`。
3. 权限选择“查看者”即可。
4. 在 `telegram_config.json` 里填写：

```json
{
  "sheet_url": "https://docs.google.com/spreadsheets/d/表格ID/edit?gid=工作表gid#gid=工作表gid",
  "service_account_file": "/opt/channel-query/service-account.json"
}
```

## 服务器约定

服务器 IP 不写入仓库。继续维护时从实际部署环境或用户说明中确认。

建议服务器目录：

```text
/opt/channel-query
```

建议 systemd 服务名：

```text
channel-query-bot
```

常用命令：

```bash
sudo systemctl restart channel-query-bot
sudo systemctl status channel-query-bot --no-pager
sudo journalctl -u channel-query-bot -f
```

## 不要上传到 GitHub 的文件

这些文件包含账号、token、密钥或真实数据，必须只保存在服务器或本机：

- `.env`
- `.backend_token.enc`
- `.backend_login.enc`
- `.google_oauth_token.enc`
- `telegram_config.json`
- `service-account.json`
- `google-oauth-client.json`
- `channels.csv`
- `.channel_query_draft.json`

`.gitignore` 已经默认排除了这些文件。

## 以后继续开发时先做什么

新对话窗口里可以这样说：

```text
这是 WPPChat 渠道查询 Telegram 机器人项目。请先阅读 docs/PROJECT_STATE.md，再继续。
```

然后再说明你要改的功能。

## GitHub 同步约定

仓库地址：

```text
https://github.com/dayou0168/channel-query
```

以后更新代码或项目文档后，默认需要提交并推送到 GitHub，除非用户明确说先不要同步。
