# 渠道查询工具

## 项目固化入口

以后换对话窗口或换服务器继续维护时，优先看这几个文件：

- `AGENTS.md`：给后续 Codex / 维护者的项目接手说明。
- `docs/PROJECT_STATE.md`：当前项目功能、服务器现状、不要上传的敏感文件。
- `docs/INSTALL.md`：裸机 Linux 和 Docker Compose 两种一键部署方式。
- `docs/DEPLOY_LINUX.md`：Linux 服务器部署和更新流程。
- `docs/GITHUB_UPLOAD.md`：上传 GitHub 的安全流程。
- `SECURITY.md`：密钥、token、服务账号 JSON 的安全注意事项。

这个工具用于批量输入 WPPChat 账号，查询后台用户列表里的注册来源，再到 Google 表格里匹配“来源编号”左侧的渠道编码。

## 启动

```powershell
python channel_query_app.py
```

默认地址：

```text
http://127.0.0.1:8765
```

## 使用方式

1. 在“WPPChat账号”里粘贴账号，一行一个。
2. 在“Google表格链接”里填写你的表格网址，可以随时改成别的表格。
3. 先跑通逻辑时，建议在 Google 表格里点“文件 -> 下载 -> 逗号分隔值(.csv)”，然后上传 CSV；也可以直接粘贴 CSV 内容。
4. 后台连接不用手动填写 `x-token`。在网页里填写后台用户名、密码和谷歌验证码，点击“登录后台”，软件会自动获取 token。
5. 点击“开始查询”，结果可复制或下载 CSV。

## Google 表格读取

为了先跑通程序逻辑，推荐先用 CSV：

1. 打开 Google 表格。
2. 文件 -> 下载 -> 逗号分隔值(.csv)。
3. 回到工具页面上传 CSV。

普通网页登录 Google 可以用于查看和下载表格，但浏览器不会允许本地程序直接读取你的 Google 登录 Cookie。后续如果要全自动读取私有表格，可以再接下面两种方式：

- 服务账号 JSON：把表格共享给服务账号邮箱。
- Google OAuth：软件弹出 Google 授权页，只申请表格只读权限。

如果要给 Telegram 机器人实时读取每天更新的表格，推荐使用 Google OAuth：

1. 准备一个只有表格查看权限的 Google 账号。
2. 把表格共享给这个账号，权限选“查看者”。
3. 在网页工具里填写 OAuth 客户端 JSON 路径。
4. 点击“授权Google”，用这个只读账号登录。
5. 授权成功后，Google refresh token 会加密保存到本机，机器人每次查询都会实时读取 Google 表格。

OAuth 第一次使用需要准备一个 OAuth 客户端 JSON：

1. 打开 Google Cloud Console。
2. 创建或选择一个项目。
3. 启用 Google Sheets API。
4. 创建 OAuth 客户端 ID。
5. 应用类型建议选择“桌面应用”。
6. 下载 JSON 文件。
7. 在软件里填写这个 JSON 文件路径，然后点击“登录Google”。

如果选择“Web 应用”类型，需要把下面的地址加入授权重定向 URI：

```text
http://127.0.0.1:8765/oauth2callback
```

## 表格要求

Google 表格中必须有一列叫：

```text
来源编号
```

渠道编码必须在“来源编号”的左侧一列。

示例：

| 渠道编码 | 来源编号 |
| --- | --- |
| CH17 | 615b17 |
| CH25 | 615b25 |

注册来源会自动标准化：

```text
https://615b07.omdsy2e.top -> 615b07
615b07 -> 615b07
```

## Telegram 群机器人

机器人文件：

```powershell
python telegram_bot.py --config telegram_config.json
```

先复制配置模板：

```powershell
Copy-Item telegram_config.example.json telegram_config.json
```

然后编辑 `telegram_config.json`：

- `telegram_bot_token`：从 Telegram 的 `@BotFather` 创建机器人后拿到。
- `backend_base`：后台地址，例如 `https://zhheew.bw009.com`。
- `backend_token`：可以留空。网页里“登录后台”成功后会把 token 加密保存，机器人会自动读取。
- `sheet_csv_path`：实时读取 Google 表格时留空；只想临时使用固定 CSV 时再填，例如 `D:\Documents\渠道查询\channels.csv`。

如果机器人提示后台登录失败，回到网页工具重新填写后台密码和谷歌验证码，点击“登录后台”，再重启机器人即可。

如果机器人提示 Google 尚未登录，回到网页工具点击“授权Google”，用只有查看权限的 Google 账号登录，再重启机器人即可。

群机器人要能看见群里成员直接发送的普通账号消息，需要在 `@BotFather` 里关闭机器人 Privacy Mode：

```text
/mybots -> 选择机器人 -> Bot Settings -> Group Privacy -> Turn off
```

关闭后把机器人移出群，再重新加进群。之后群成员直接发送 WPPChat 账号，机器人会回复：

```text
WPPChat
注册IP
注册省份
注册来源
渠道编码
状态
```

机器人会直接回复发送账号的那条群消息；其中“账号”“注册来源”“渠道编码”使用代码格式显示，方便在 Telegram 客户端里点选复制。

同 IP 查询命令：

```text
查IP 172.15.217.52
```

机器人会回复这个注册 IP 下的所有账号和注册时间。

## Linux 服务器部署

服务器上建议同时运行两个进程：

- `channel_query_app.py`：只监听 `127.0.0.1`，用于你通过 SSH 隧道登录 Google 和后台，保存加密 token。
- `telegram_bot.py`：长期运行，群内成员发送 WPPChat 账号时实时查询后台和 Google 表格。

安装依赖：

```bash
cd /opt/channel-query
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

生成服务器主密钥：

```bash
python channel_query_app.py --generate-master-key
```

把输出保存到服务器环境变量文件，例如 `/opt/channel-query/.env`：

```bash
CHANNEL_QUERY_MASTER_KEY=这里填刚才生成的密钥
```

限制权限：

```bash
chmod 600 /opt/channel-query/.env
```

以后启动网页工具和机器人时，都必须加载同一个 `CHANNEL_QUERY_MASTER_KEY`：

```bash
set -a
source /opt/channel-query/.env
set +a
python channel_query_app.py --host 127.0.0.1 --port 8766
```

在你的电脑上开 SSH 隧道：

```bash
ssh -L 8766:127.0.0.1:8766 user@你的服务器IP
```

然后在你电脑浏览器打开：

```text
http://127.0.0.1:8766
```

在这个网页里：

1. 填 Google OAuth 客户端 JSON 在服务器上的路径，点击“授权Google”，用只有表格查看权限的账号登录。
2. 填后台用户名、密码、谷歌验证码，点击“登录后台”。
3. 如果要让机器人自动处理后台 token 过期，还要填写“自动续登录密钥”。这个是 Google Authenticator 绑定时的密钥或 otpauth 链接，不是当前 6 位验证码。

授权成功后会在服务器工作目录生成加密文件：

```text
.google_oauth_token.enc
.backend_token.enc
.backend_login.enc
```

这些文件只有配合同一个 `CHANNEL_QUERY_MASTER_KEY` 才能解密。

启动机器人：

```bash
set -a
source /opt/channel-query/.env
set +a
python telegram_bot.py --config telegram_config.json
```

如果后台 token 过期，重新通过 SSH 隧道打开网页工具，再登录后台一次即可；不需要改机器人代码。
如果已经保存了“自动续登录密钥”，机器人会在后台 token 过期时自动重新登录并重试查询。
