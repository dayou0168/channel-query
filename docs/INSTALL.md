# 两种一键安装方式

项目现在支持两种服务器安装方式：

- 裸机 Linux 部署：直接在服务器上安装 Python、依赖和 systemd 服务。
- Docker Compose 部署：安装 Docker / Compose，用容器运行机器人和网页工具。

两种方式都适合 Ubuntu / Debian。

## 重要说明

当前 GitHub 仓库是私有仓库。私有仓库不能直接无权限 `curl raw.githubusercontent.com`，需要 GitHub token。

如果以后把仓库改成 Public，裸机 Linux 就可以直接一条命令安装：

```bash
curl -fsSL https://raw.githubusercontent.com/dayou0168/channel-query/main/scripts/bootstrap-linux.sh | sudo bash
```

Docker Compose 也可以一条命令安装：

```bash
curl -fsSL https://raw.githubusercontent.com/dayou0168/channel-query/main/scripts/bootstrap-docker.sh | sudo bash
```

如果仓库保持 Private，推荐先准备一个只读 GitHub token，然后这样执行。token 不要发到聊天窗口。GitHub token 只需要这个私有仓库的 `Contents: Read-only` 权限。

```bash
read -rsp "GitHub Token: " CHANNEL_QUERY_GITHUB_TOKEN; echo
curl -fsSL -H "Authorization: Bearer ${CHANNEL_QUERY_GITHUB_TOKEN}" \
  https://raw.githubusercontent.com/dayou0168/channel-query/main/scripts/bootstrap-linux.sh \
  | sudo CHANNEL_QUERY_GITHUB_TOKEN="${CHANNEL_QUERY_GITHUB_TOKEN}" bash
unset CHANNEL_QUERY_GITHUB_TOKEN
```

Docker Compose 私有仓库安装命令：

```bash
read -rsp "GitHub Token: " CHANNEL_QUERY_GITHUB_TOKEN; echo
curl -fsSL -H "Authorization: Bearer ${CHANNEL_QUERY_GITHUB_TOKEN}" \
  https://raw.githubusercontent.com/dayou0168/channel-query/main/scripts/bootstrap-docker.sh \
  | sudo CHANNEL_QUERY_GITHUB_TOKEN="${CHANNEL_QUERY_GITHUB_TOKEN}" bash
unset CHANNEL_QUERY_GITHUB_TOKEN
```

这个远程入口脚本会自动安装基础依赖、拉取 GitHub 仓库，然后继续执行项目里的安装脚本。

## 方式一：裸机 Linux 一键部署

适合你希望直接用 systemd 管理机器人的场景。

```bash
curl -fsSL https://raw.githubusercontent.com/dayou0168/channel-query/main/scripts/bootstrap-linux.sh | sudo bash
```

脚本会自动做这些事：

- `apt update`
- `apt upgrade -y`
- 安装 `git`、`python3`、`python3-venv`、`python3-pip`
- 从 GitHub 拉取项目到 `/opt/channel-query`
- 创建 Python 虚拟环境 `.venv`
- 安装 `requirements.txt`
- 自动生成 `.env` 里的 `CHANNEL_QUERY_MASTER_KEY`
- 创建 `telegram_config.json` 模板
- 创建 systemd 服务 `channel-query-bot`
- 如果配置已经填好，会自动启动机器人；如果还是模板内容，会暂不启动

如果你不想执行系统升级，只想安装依赖：

```bash
curl -fsSL https://raw.githubusercontent.com/dayou0168/channel-query/main/scripts/bootstrap-linux.sh \
  | sudo CHANNEL_QUERY_SKIP_UPGRADE=1 bash
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

## 方式二：Docker Compose 直接 YAML 部署

这是你说的“通过 yaml 配置文件直接部署”。它不需要服务器上有完整源码，只需要下载 `docker-compose.deploy.yml`，然后从 GHCR 拉取已经构建好的镜像。

前提：GitHub Actions 已经成功构建镜像：

```text
ghcr.io/dayou0168/channel-query:latest
```

如果 GitHub Actions 构建失败，并提示：

```text
The job was not started because recent account payments have failed or your spending limit needs to be increased.
```

这不是项目代码问题，需要到 GitHub 的 `Billing & plans` 里处理账单或提高 Actions spending limit。处理完成后，重新运行 `Build Docker Image` workflow，镜像生成后才能使用直接 YAML 部署。

如果镜像包是 Private，需要先登录 GHCR：

```bash
echo "你的GitHubToken" | sudo docker login ghcr.io -u dayou0168 --password-stdin
```

token 需要 `Packages: Read` 权限。如果镜像包设置成 Public，就不需要登录。

公开仓库时可以用这一条命令安装：

```bash
curl -fsSL https://raw.githubusercontent.com/dayou0168/channel-query/main/scripts/bootstrap-compose-yaml.sh | sudo bash
```

当前仓库是 Private，使用这一条：

```bash
read -rsp "GitHub Token: " CHANNEL_QUERY_GITHUB_TOKEN; echo
curl -fsSL -H "Authorization: Bearer ${CHANNEL_QUERY_GITHUB_TOKEN}" \
  https://raw.githubusercontent.com/dayou0168/channel-query/main/scripts/bootstrap-compose-yaml.sh \
  | sudo CHANNEL_QUERY_GITHUB_TOKEN="${CHANNEL_QUERY_GITHUB_TOKEN}" bash
unset CHANNEL_QUERY_GITHUB_TOKEN
```

脚本会自动做这些事：

- `apt update`
- `apt upgrade -y`
- 安装 `docker.io`、`docker-compose-plugin`
- 创建 `/opt/channel-query/docker-compose.yml`
- 创建 `/opt/channel-query/.env`
- 创建 `/opt/channel-query/config/telegram_config.json`
- 创建 `/opt/channel-query/data/`
- 拉取 `ghcr.io/dayou0168/channel-query:latest`
- 如果配置已经填好，会自动启动机器人；如果还是模板内容，会暂不启动

手动下载 YAML 的方式：

```bash
sudo mkdir -p /opt/channel-query/config /opt/channel-query/data
cd /opt/channel-query
sudo curl -fsSL \
  https://raw.githubusercontent.com/dayou0168/channel-query/main/docker-compose.deploy.yml \
  -o docker-compose.yml
sudo curl -fsSL \
  https://raw.githubusercontent.com/dayou0168/channel-query/main/telegram_config.example.json \
  -o config/telegram_config.json
sudo sh -c 'printf "CHANNEL_QUERY_MASTER_KEY=%s\n" "$(head -c 32 /dev/urandom | base64 | tr "+/" "-_")" > .env'
sudo chmod 600 .env config/telegram_config.json
sudo docker compose pull
sudo docker compose up -d bot
```

如果要启动网页工具：

```bash
cd /opt/channel-query
sudo docker compose --profile web up -d web
```

## 方式三：Docker Compose 源码构建部署

适合你以后要跑多个机器人，或者希望配合 Docker 面板管理的场景。

```bash
curl -fsSL https://raw.githubusercontent.com/dayou0168/channel-query/main/scripts/bootstrap-docker.sh | sudo bash
```

这个方式会先从 GitHub 拉取完整源码，然后在服务器本机执行 `docker compose build`。

脚本会自动做这些事：

- `apt update`
- `apt upgrade -y`
- 安装 `git`、`docker.io`、`docker-compose-plugin`
- 启动 Docker 服务
- 从 GitHub 拉取项目到 `/opt/channel-query`
- 创建 `.env`
- 创建 `config/telegram_config.json`
- 创建 `data/` 持久化目录
- 构建 Docker 镜像
- 如果配置已经填好，会自动启动机器人；如果还是模板内容，会暂不启动

如果你不想执行系统升级：

```bash
curl -fsSL https://raw.githubusercontent.com/dayou0168/channel-query/main/scripts/bootstrap-docker.sh \
  | sudo CHANNEL_QUERY_SKIP_UPGRADE=1 bash
```

Docker Compose 源码构建部署配置文件：

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

Docker Compose 直接 YAML 路径：

```text
/opt/channel-query/config/telegram_config.json
```

Docker Compose 源码构建路径：

```text
/opt/channel-query/config/telegram_config.json
```

裸机示例：

```json
{
  "telegram_bot_token": "从BotFather拿到的token",
  "telegram_api_base": "https://api.telegram.org",
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
  "telegram_api_base": "https://api.telegram.org",
  "backend_base": "https://zhheew.bw009.com",
  "backend_token": "",
  "sheet_url": "Google表格链接",
  "sheet_csv_path": "",
  "service_account_file": "/config/service-account.json"
}
```

如果服务器访问 Telegram 官方接口不稳定，可以把 `telegram_api_base` 改成你自己的 Telegram Bot API 反代地址。也可以在 `.env` 里填写：

```text
TELEGRAM_API_BASE=https://你的telegram-api反代域名
```

## 两种方式怎么选

只跑一个机器人，想简单稳定：选裸机 Linux。

以后要跑多个机器人，或者想用中文 Docker 面板管理：选 Docker Compose。

不要同时用两种方式启动同一个 Telegram Bot Token，否则 Telegram 会报 `HTTP 409 Conflict`。
