# 安全说明

这个项目会接触 Telegram token、后台登录信息、Google 服务账号和加密 token。仓库应保持私有。

## 不要提交的内容

以下内容只能保存在本机或服务器：

- Telegram Bot Token
- 后台账号、密码、x-token
- Google 服务账号 JSON
- Google OAuth 客户端 JSON
- `.env`
- `*.enc`
- 真实用户数据 CSV

`.gitignore` 已经默认排除这些内容。

## 推荐做法

- GitHub 仓库选择 Private。
- 服务器上 `.env`、`telegram_config.json`、`service-account.json` 使用 `chmod 600`。
- `CHANNEL_QUERY_MASTER_KEY` 只保存在服务器，不发到聊天窗口，不上传 GitHub。
- 如果怀疑 token 泄露，立即在 BotFather、后台系统、Google Cloud 里轮换密钥。
