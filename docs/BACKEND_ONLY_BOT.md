# 后台-only 查询机器人

这个模式不依赖 Google 表格，只对接后台。

适合单独创建一个“分支渠道查询机器人”：

- 发送 WPPChat 账号：查询注册 IP、注册省份、注册时间、注册来源。
- 发送 IP 或 `查IP 1.2.3.4`：查询同 IP 下注册的账号和注册时间。

## 配置文件

可以复制模板：

```bash
cp telegram_backend_only_config.example.json telegram_config.json
```

配置示例：

```json
{
  "telegram_bot_token": "从BotFather拿到的token",
  "backend_base": "https://zhheew.bw009.com",
  "backend_token": "",
  "backend_only": true,
  "ip_query_limit": 500
}
```

`backend_only` 为 `true` 时，账号查询不会读取 Google 表格，也不会返回渠道编码。

## 账号查询回复

```text
查询结果：
账号：yizhihen
注册IP：112.36.175.232
注册省份：山东 济南
注册时间：2026-07-02 12:00:00
注册来源：615b07
状态：已查到

合计 1 个，查到 1 个，未查到 0 个。
```

## 同 IP 查询

```text
查IP 112.36.175.232
```

回复：

```text
同IP查询：112.36.175.232
账号：account1
注册时间：2026-07-02 12:00:00

账号：account2
注册时间：2026-07-02 12:05:00
```

## Docker Compose

可以和现有容器编排共用镜像，只需要把 `/config/telegram_config.json` 换成后台-only 配置。

如果同一台服务器要同时跑“渠道编码机器人”和“后台-only 机器人”，要给第二个机器人使用不同的：

- Telegram Bot Token
- container_name
- config 目录
- data 目录

不要让两个容器使用同一个 Bot Token，否则 Telegram 会报 `409 Conflict`。
