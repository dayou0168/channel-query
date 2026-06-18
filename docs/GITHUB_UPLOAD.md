# 上传 GitHub 流程

## 重要安全提醒

上传前确认不要上传这些文件：

- `.env`
- `telegram_config.json`
- `service-account.json`
- `google-oauth-client.json`
- `.backend_token.enc`
- `.backend_login.enc`
- `.google_oauth_token.enc`
- `channels.csv`
- `.channel_query_draft.json`

项目里的 `.gitignore` 已经排除了它们。

## Windows 安装 Git

当前这台 Windows 还没有 `git` 命令。先安装 Git：

1. 打开 [Git for Windows](https://git-scm.com/download/win)。
2. 下载并安装。
3. 安装后关闭当前 PowerShell，重新打开。
4. 验证：

```powershell
git --version
```

## 在 GitHub 创建空仓库

1. 打开 [GitHub New Repository](https://github.com/new)。
2. 仓库名建议：

```text
channel-query
```

3. 选择 Private 私有仓库。
4. 不要勾选 README、.gitignore、License。
5. 创建后复制仓库地址，例如：

```text
https://github.com/你的用户名/channel-query.git
```

## 本地初始化并上传

在 PowerShell 执行：

```powershell
cd "D:\Documents\渠道查询"
git init
git add AGENTS.md SECURITY.md .gitignore .env.example README.md requirements.txt channel_query_app.py telegram_bot.py telegram_config.example.json channels.example.csv docs scripts
git commit -m "Initial channel query bot"
git branch -M main
git remote add origin https://github.com/你的用户名/channel-query.git
git push -u origin main
```

如果 GitHub 要求登录，按提示在浏览器授权即可。

## 从服务器拉取

GitHub 上传完成后，服务器可以这样部署：

```bash
cd /opt
sudo git clone https://github.com/你的用户名/channel-query.git channel-query
cd /opt/channel-query
chmod +x scripts/*.sh
sudo ./scripts/install.sh
```

然后按 `docs/DEPLOY_LINUX.md` 填写 `.env`、`telegram_config.json` 和 `service-account.json`。
