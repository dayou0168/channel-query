#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 机器人版本。

用法：
1. 向 @BotFather 创建机器人，拿到 bot token
2. 复制 telegram_config.example.json 为 telegram_config.json 并填写配置
3. python telegram_bot.py --config telegram_config.json

机器人收到 WPPChat 账号后，返回：
WPPChat账号、注册IP、注册省份、注册来源、渠道编码、状态
未匹配时返回“未查到”。
"""

from __future__ import annotations

import argparse
import html
import ipaddress
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import channel_query_app as core


MAX_MESSAGE_LEN = 3800
DEFAULT_TELEGRAM_API_BASE = "https://api.telegram.org"
DEFAULT_TELEGRAM_ALLOWED_UPDATES = ["message", "my_chat_member"]
TELEGRAM_CHAT_REGISTRY_FILE_ENV = "TELEGRAM_CHAT_REGISTRY_FILE"
RETRYABLE_TELEGRAM_HTTP_STATUS = {500, 502, 503, 504}
INITIAL_RETRY_DELAY = 5
MAX_RETRY_DELAY = 300


class TelegramRetryableError(RuntimeError):
    pass


class RetryBackoff:
    def __init__(self, initial_delay: int = INITIAL_RETRY_DELAY, max_delay: int = MAX_RETRY_DELAY) -> None:
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.delay = initial_delay

    def reset(self) -> None:
        self.delay = self.initial_delay

    def next_delay(self) -> int:
        current = self.delay
        self.delay = min(self.max_delay, self.delay * 2)
        return current


def load_config(path: str) -> dict[str, Any]:
    config_path = Path(path)
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        config = {}
    env_map = {
        "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
        "telegram_api_base": "TELEGRAM_API_BASE",
        "telegram_allowed_updates": "TELEGRAM_ALLOWED_UPDATES",
        "telegram_chat_registry_file": TELEGRAM_CHAT_REGISTRY_FILE_ENV,
        "backend_base": "WPPCHAT_BACKEND_URL",
        "backend_token": "WPPCHAT_X_TOKEN",
        "sheet_url": "CHANNEL_QUERY_SHEET_URL",
        "sheet_csv_path": "CHANNEL_QUERY_SHEET_CSV_PATH",
        "service_account_file": "CHANNEL_QUERY_SERVICE_ACCOUNT_FILE",
    }
    for key, env_name in env_map.items():
        if os.environ.get(env_name):
            config[key] = os.environ[env_name]
    return config


def normalize_telegram_api_base(value: Any) -> str:
    text = str(value or DEFAULT_TELEGRAM_API_BASE).strip()
    if not text:
        text = DEFAULT_TELEGRAM_API_BASE
    if "://" not in text:
        text = "https://" + text
    return text.rstrip("/")


def parse_allowed_updates(value: Any) -> list[str]:
    if not value:
        return list(DEFAULT_TELEGRAM_ALLOWED_UPDATES)
    if isinstance(value, list):
        updates = [str(item).strip() for item in value if str(item).strip()]
    else:
        updates = [item.strip() for item in re.split(r"[\s,，;；]+", str(value)) if item.strip()]
    return updates or list(DEFAULT_TELEGRAM_ALLOWED_UPDATES)


def telegram_chat_registry_path(config: dict[str, Any] | None = None) -> Path:
    value = ""
    if config:
        value = str(config.get("telegram_chat_registry_file") or "").strip()
    value = value or os.environ.get(TELEGRAM_CHAT_REGISTRY_FILE_ENV, "").strip()
    path = Path(value).expanduser() if value else core.DATA_DIR / ".telegram_chats.json"
    if not path.is_absolute():
        path = (core.DATA_DIR / path).resolve()
    return path


def load_chat_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "chats": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "chats": {}}
    if not isinstance(data, dict):
        return {"version": 1, "chats": {}}
    if not isinstance(data.get("chats"), dict):
        data["chats"] = {}
    data.setdefault("version", 1)
    return data


def save_chat_registry(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, path)


def chat_summary(chat: dict[str, Any]) -> dict[str, Any]:
    return {
        key: chat.get(key)
        for key in ("id", "type", "title", "username", "first_name", "last_name")
        if chat.get(key) is not None
    }


def record_chat(
    chat: dict[str, Any] | None,
    config: dict[str, Any],
    source: str,
    member_update: dict[str, Any] | None = None,
) -> None:
    if not chat or chat.get("id") is None:
        return
    try:
        now = int(time.time())
        path = telegram_chat_registry_path(config)
        data = load_chat_registry(path)
        chats = data.setdefault("chats", {})
        chat_id = str(chat["id"])
        entry = chats.get(chat_id) if isinstance(chats.get(chat_id), dict) else {}
        previous_last_seen = int(entry.get("last_seen_at") or 0)

        changed = False
        for key, value in chat_summary(chat).items():
            if entry.get(key) != value:
                changed = True
            entry[key] = value

        if member_update:
            changed = True
            new_member = member_update.get("new_chat_member") or {}
            old_member = member_update.get("old_chat_member") or {}
            if new_member:
                entry["bot_status"] = new_member.get("status")
                entry["bot_member"] = new_member
            if old_member:
                entry["previous_bot_status"] = old_member.get("status")

        if not changed and now - previous_last_seen < 300:
            return

        entry.setdefault("first_seen_at", now)
        entry["last_seen_at"] = now
        entry["last_seen_source"] = source
        chats[chat_id] = entry
        data["updated_at"] = now
        save_chat_registry(path, data)
    except Exception as exc:
        print(f"保存Telegram群登记失败：{exc}", file=sys.stderr)


def telegram_request(
    token: str,
    method: str,
    payload: dict[str, Any] | None = None,
    api_base: str = DEFAULT_TELEGRAM_API_BASE,
) -> dict[str, Any]:
    url = f"{normalize_telegram_api_base(api_base)}/bot{token}/{method}"
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=65) as response:
            result = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        if exc.code in RETRYABLE_TELEGRAM_HTTP_STATUS:
            raise TelegramRetryableError(f"Telegram API临时错误：HTTP {exc.code} {body}") from exc
        raise RuntimeError(f"Telegram API错误：HTTP {exc.code} {body}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise TelegramRetryableError("Telegram API网络超时") from exc
    except urllib.error.URLError as exc:
        reason = exc.reason if hasattr(exc, "reason") else exc
        raise TelegramRetryableError(f"Telegram API网络错误：{reason}") from exc
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API错误：{result}")
    return result


def get_updates(token: str, offset: int | None, api_base: str, allowed_updates: list[str]) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {"timeout": 55, "allowed_updates": allowed_updates}
    if offset is not None:
        payload["offset"] = offset
    return telegram_request(token, "getUpdates", payload, api_base).get("result") or []


def send_message(
    token: str,
    chat_id: int,
    text: str,
    reply_to_message_id: int | None = None,
    parse_mode: str | None = None,
    api_base: str = DEFAULT_TELEGRAM_API_BASE,
) -> None:
    for chunk in split_message(text):
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
            payload["allow_sending_without_reply"] = True
        if parse_mode:
            payload["parse_mode"] = parse_mode
        telegram_request(
            token,
            "sendMessage",
            payload,
            api_base,
        )


def split_message(text: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        candidate = current + ("\n" if current else "") + line
        if len(candidate) > MAX_MESSAGE_LEN:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [text]


def read_sheet_csv(config: dict[str, Any]) -> str:
    csv_path = config.get("sheet_csv_path")
    if csv_path:
        path = Path(str(csv_path)).expanduser()
        if not path.exists():
            raise RuntimeError(f"渠道表CSV不存在：{path}")
        return path.read_text(encoding=config.get("sheet_csv_encoding") or "utf-8-sig")
    return ""


def html_code(value: Any) -> str:
    text = str(value or "未查到").strip() or "未查到"
    return f"<code>{html.escape(text)}</code>"


def html_text(value: Any) -> str:
    return html.escape(str(value or "未查到").strip() or "未查到")


def display_source(row: dict[str, Any]) -> str:
    return str(row.get("source_id") or core.normalize_source(row.get("source")) or row.get("source") or "未查到")


def display_province(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "未查到"
    parts = [part for part in re.split(r"\s+", text) if part]
    if parts and parts[0] == "中国":
        return " ".join(parts[1:]) or "未查到"
    return text


def normalize_ipv4(value: str) -> str | None:
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    return str(ip) if ip.version == 4 else None


def is_ip_command(text: str) -> bool:
    value = text.strip()
    return bool(
        re.match(r"^/ip(?:@\w+)?(?:\s+|$)", value, flags=re.IGNORECASE)
        or re.match(r"^查\s*ip(?:\s+|[:：]|$)", value, flags=re.IGNORECASE)
    )


def parse_ip_query(text: str) -> list[str]:
    value = text.strip()
    command_match = re.match(r"^/ip(?:@\w+)?(?:\s+|$)(.*)$", value, flags=re.IGNORECASE | re.DOTALL)
    if command_match:
        value = command_match.group(1).strip()
    else:
        command_match = re.match(r"^查\s*ip(?:\s+|[:：]|$)(.*)$", value, flags=re.IGNORECASE | re.DOTALL)
        if command_match:
            value = command_match.group(1).strip()
    tokens = [item.strip() for item in re.split(r"[\s,，;；]+", value) if item.strip()]
    if not tokens:
        return []
    ips: list[str] = []
    for token in tokens:
        ip = normalize_ipv4(token)
        if not ip:
            return []
        if ip not in ips:
            ips.append(ip)
    return ips


def query_ip_text(text: str, config: dict[str, Any]) -> str:
    ips = parse_ip_query(text)
    if not ips:
        return "请发送IP地址，或使用 查IP 1.2.3.4。"
    token, _ = core.get_backend_token(config.get("backend_token") or "")
    backend_base = config.get("backend_base") or core.BACKEND_BASE_URL
    limit = int(config.get("ip_query_limit") or 500)
    lines: list[str] = []
    for ip in ips:
        rows = core.call_backend_users_by_ip(ip, token, backend_base, limit)
        lines.append(f"同IP查询：{html_code(ip)}")
        if not rows:
            lines.append("未查到同IP注册账号。")
            lines.append("")
            continue
        for row in rows:
            account = row.get("username") or "未查到"
            register_time = core.format_backend_time(core.first_backend_value(row, "register_time", "created", "create_time"))
            lines.append(f"账号：{html_code(account)}")
            lines.append(f"注册时间：{html_text(register_time)}")
            lines.append("")
        suffix = f"，只显示前 {limit} 个" if len(rows) >= limit else ""
        lines.append(f"合计 {len(rows)} 个{suffix}。")
        lines.append("")
    return "\n".join(lines).strip()


def query_text(text: str, config: dict[str, Any]) -> str:
    accounts = core.parse_accounts(text)
    if not accounts:
        return "请发送 WPPChat 账号，可以一行一个，也可以用空格或逗号分隔。"

    body = {
        "accounts": accounts,
        "backendBase": config.get("backend_base") or core.BACKEND_BASE_URL,
        "backendToken": config.get("backend_token") or "",
        "sheetUrl": config.get("sheet_url") or core.DEFAULT_SHEET_URL,
        "sheetCsv": read_sheet_csv(config),
        "serviceAccountFile": config.get("service_account_file") or "",
    }
    data = core.query_accounts(body)
    lines = ["查询结果："]
    for row in data["results"]:
        lines.extend(
            [
                f"账号：{html_code(row['account'])}",
                f"注册IP：{html_code(row.get('register_ip'))}",
                f"注册省份：{html_text(display_province(row.get('register_province')))}",
                f"注册来源：{html_code(display_source(row))}",
                f"渠道编码：{html_code(row['channel_code'])}",
                f"状态：{html_text(row['status'])}",
                "",
            ]
        )
    summary = data["summary"]
    lines.append(f"合计 {summary['total']} 个，查到 {summary['found']} 个，未查到 {summary['missing']} 个。")
    return "\n".join(lines)


def handle_message(token: str, message: dict[str, Any], config: dict[str, Any], api_base: str) -> None:
    chat = message.get("chat") or {}
    record_chat(chat, config, "message")
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    text = (message.get("text") or "").strip()
    if not chat_id:
        return
    if text in ("/start", "/help"):
        send_message(
            token,
            chat_id,
            "发送 WPPChat 账号即可查询注册IP、注册省份、注册来源和渠道编码。\n"
            "发送 查IP 1.2.3.4 即可查询同IP注册账号和注册时间。\n"
            "支持批量：一行一个，或用空格、逗号分隔。\n"
            "例：\nabc915915\nbvcxzsdfgh\n查IP 172.15.217.52",
            reply_to_message_id=message_id,
            api_base=api_base,
        )
        return
    try:
        if is_ip_command(text) or parse_ip_query(text):
            reply = query_ip_text(text, config)
        else:
            reply = query_text(text, config)
        send_message(token, chat_id, reply, reply_to_message_id=message_id, parse_mode="HTML", api_base=api_base)
    except TelegramRetryableError:
        raise
    except Exception as exc:
        send_message(token, chat_id, f"查询失败：{exc}", reply_to_message_id=message_id, api_base=api_base)


def handle_my_chat_member(update: dict[str, Any], config: dict[str, Any]) -> None:
    member_update = update.get("my_chat_member") or {}
    record_chat(member_update.get("chat") or {}, config, "my_chat_member", member_update)


def main() -> None:
    parser = argparse.ArgumentParser(description="WPPChat 渠道查询 Telegram 机器人")
    parser.add_argument("--config", default="telegram_config.json")
    args = parser.parse_args()

    config = load_config(args.config)
    token = config.get("telegram_bot_token")
    if not token:
        print("缺少 telegram_bot_token。请填写 telegram_config.json 或 TELEGRAM_BOT_TOKEN。", file=sys.stderr)
        sys.exit(1)
    api_base = normalize_telegram_api_base(config.get("telegram_api_base"))
    allowed_updates = parse_allowed_updates(config.get("telegram_allowed_updates"))

    startup_backoff = RetryBackoff()
    while True:
        try:
            me = telegram_request(token, "getMe", api_base=api_base)
            break
        except TelegramRetryableError as exc:
            delay = startup_backoff.next_delay()
            print(f"Telegram连接暂时失败：{exc}。{delay}秒后重试。", file=sys.stderr)
            time.sleep(delay)
    username = (me.get("result") or {}).get("username", "")
    print(f"Telegram机器人已启动：@{username}" if username else "Telegram机器人已启动")

    offset: int | None = None
    loop_backoff = RetryBackoff()
    while True:
        try:
            updates = get_updates(token, offset, api_base, allowed_updates)
            loop_backoff.reset()
            for update in updates:
                offset = int(update["update_id"]) + 1
                message = update.get("message")
                if message:
                    handle_message(token, message, config, api_base)
                if update.get("my_chat_member"):
                    handle_my_chat_member(update, config)
        except KeyboardInterrupt:
            print("\n已停止。")
            return
        except TelegramRetryableError as exc:
            delay = loop_backoff.next_delay()
            print(f"Telegram连接暂时失败：{exc}。{delay}秒后重试。", file=sys.stderr)
            time.sleep(delay)
        except Exception as exc:
            delay = loop_backoff.next_delay()
            print(f"运行错误：{exc}。{delay}秒后重试。", file=sys.stderr)
            time.sleep(delay)


if __name__ == "__main__":
    main()
