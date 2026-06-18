# 两种一键安装方式

项目现在支持两种服务器安装方式：

- 裸机 Linux 部署：直接在服务器上安装 Python、依赖和 systemd 服务。
- Docker Compose 部署：安装 Docker / Compose，用容器运行机器人和网页工具。

两种方式都适合 Ubuntu / Debian。

## 重要说明

当前 GitHub 仓库是私有仓库。服务器第一次拉代码前，需要先让服务器有权限访问仓库。推荐方式：

```bash
sudo apt update
sudo apt install -y git gh
gh auth login
gh repo clone dayou0168/channel-query /opt/channel-query
cd /opt/channel-query
```

如果你已经用别的方式把项目放到了 `/opt/channel-query`，可以直接进入目录执行安装脚本。

## 方式一：裸机 Linux 一键部署

适合你希望直接用 systemd 管理机器人的场景。

```bash
cd /opt/channel-query
sudo bash scripts/install-linux.sh
```

脚本会自动做这些事：

- `apt update`
- `apt upgrade -y`
- 安装 `git`、`python3`、`python3-venv`、`python3-pip`
- 创建 Python 虚拟环境 `.venv`
- 安装 `requirements.txt`
- 自动生成 `.env` 里的 `CHANNEL_QUERY_MASTER_KEY`
- 创建 `telegram_config.json` 模板
- 创建 systemd 服务 `channel-query-bot`
- 如果配置已经填好，会自动启动机器人；如果还是模板内容，会暂不启动

如果你不想执行系统升级，只想安装依赖：

```bash
cd /opt/channel-query
sudo CHANNEL_QUERY_SKIP_UPGRADE=1 bash scripts/install-linux.sh
```

裸机部署配置文件：

```text
/opt/channel-query/.env
/opt/channel-query/telegram_config.json
/opt/channel-query/service-account.json
```

启动机器人：

```bash
sudo systemctl restart channel-query-bot
```

查看日志：

```bash
sudo journalctl -u channel-query-bot -f
```

启动网页工具，用于登录后台、保存加密 token：

```bash
cd /opt/channel-query
sudo bash scripts/start-web.sh
```

然后在你自己的电脑打开 SSH 隧道：

```bash
ssh -L 8766:127.0.0.1:8766 root@服务器IP
```

浏览器打开：

```text
http://127.0.0.1:8766
```

## 方式二：Docker Compose 一键部署

适合你以后要跑多个机器人，或者希望配合 Docker 面板管理的场景。

```bash
cd /opt/channel-query
sudo bash scripts/install-docker.sh
```

脚本会自动做这些事：

- `apt update`
- `apt upgrade -y`
- 安装 `git`、`docker.io`、`docker-compose-plugin`
- 启动 Docker 服务
- 创建 `.env`
- 创建 `config/telegram_config.json`
- 创建 `data/` 持久化目录
- 构建 Docker 镜像
- 如果配置已经填好，会自动启动机器人；如果还是模板内容，会暂不启动

如果你不想执行系统升级：

```bash
cd /opt/channel-query
sudo CHANNEL_QUERY_SKIP_UPGRADE=1 bash scripts/install-docker.sh
```

Docker Compose 部署配置文件：

```text
/opt/channel-query/.env
/opt/channel-query/config/telegram_config.json
/opt/channel-query/config/service-account.json
/opt/channel-query/data/
```

`data/` 会保存加密后的后台 token、自动续登录配置和 Google token。不要删除。

启动机器人：

```bash
cd /opt/channel-query
sudo docker compose up -d bot
```

查看日志：

```bash
cd /opt/channel-query
sudo docker compose logs -f bot
```

启动网页工具：

```bash
cd /opt/channel-query
sudo docker compose --profile web up -d web
```

网页工具只监听服务器本机 `127.0.0.1:8766`，仍然建议用 SSH 隧道访问：

```bash
ssh -L 8766:127.0.0.1:8766 root@服务器IP
```

关闭网页工具：

```bash
cd /opt/channel-query
sudo docker compose --profile web stop web
```

停止机器人：

```bash
cd /opt/channel-query
sudo docker compose stop bot
```

## 配置 telegram_config.json

裸机路径：

```text
/opt/channel-query/telegram_config.json
```

Docker Compose 路径：

```text
/opt/channel-query/config/telegram_config.json
```

裸机示例：

```json
{
  "telegram_bot_token": "从BotFather拿到的token",
  "backend_base": "https://zhheew.bw009.com",
  "backend_token": "",
  "sheet_url": "Google表格链接",
  "sheet_csv_path": "",
  "service_account_file": "/opt/channel-query/service-account.json"
}
```

Docker Compose 示例：

```json
{
  "telegram_bot_token": "从BotFather拿到的token",
  "backend_base": "https://zhheew.bw009.com",
  "backend_token": "",
  "sheet_url": "Google表格链接",
  "sheet_csv_path": "",
  "service_account_file": "/config/service-account.json"
}
```

## 两种方式怎么选

只跑一个机器人，想简单稳定：选裸机 Linux。

以后要跑多个机器人，或者想用中文 Docker 面板管理：选 Docker Compose。

不要同时用两种方式启动同一个 Telegram Bot Token，否则 Telegram 会报 `HTTP 409 Conflict`。
