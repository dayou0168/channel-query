#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backup readable Telegram bot state.

This script intentionally does not export the bot token. It can only back up
objects visible through Telegram Bot API and chats recorded by telegram_bot.py.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import channel_query_app as core
import telegram_bot


def call_api(token: str, api_base: str, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        result = telegram_bot.telegram_request(token, method, payload, api_base)
        return {"ok": True, "result": result.get("result")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def compact_registry_chat(entry: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "type",
        "title",
        "username",
        "first_name",
        "last_name",
        "first_seen_at",
        "last_seen_at",
        "last_seen_source",
        "bot_status",
        "previous_bot_status",
    )
    return {key: entry.get(key) for key in keys if entry.get(key) is not None}


def collect_bot_settings(token: str, api_base: str) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    simple_methods = (
        "getMe",
        "getWebhookInfo",
        "getMyName",
        "getMyDescription",
        "getMyShortDescription",
        "getChatMenuButton",
    )
    for method in simple_methods:
        settings[method] = call_api(token, api_base, method)
    settings["getMyCommands"] = {
        "default": call_api(token, api_base, "getMyCommands"),
        "all_private_chats": call_api(token, api_base, "getMyCommands", {"scope": {"type": "all_private_chats"}}),
        "all_group_chats": call_api(token, api_base, "getMyCommands", {"scope": {"type": "all_group_chats"}}),
        "all_chat_administrators": call_api(
            token,
            api_base,
            "getMyCommands",
            {"scope": {"type": "all_chat_administrators"}},
        ),
    }
    settings["getMyDefaultAdministratorRights"] = {
        "groups": call_api(token, api_base, "getMyDefaultAdministratorRights", {"for_channels": False}),
        "channels": call_api(token, api_base, "getMyDefaultAdministratorRights", {"for_channels": True}),
    }
    return settings


def collect_chat_snapshots(token: str, api_base: str, registry: dict[str, Any], bot_id: int | None) -> list[dict[str, Any]]:
    chats = registry.get("chats") if isinstance(registry, dict) else {}
    if not isinstance(chats, dict):
        return []

    snapshots: list[dict[str, Any]] = []
    for chat_id, entry in sorted(chats.items(), key=lambda item: str(item[0])):
        if not isinstance(entry, dict):
            continue
        snapshot: dict[str, Any] = {"registry": compact_registry_chat(entry), "chat_id": chat_id}
        snapshot["getChat"] = call_api(token, api_base, "getChat", {"chat_id": chat_id})
        snapshot["getChatAdministrators"] = call_api(token, api_base, "getChatAdministrators", {"chat_id": chat_id})
        snapshot["getChatMemberCount"] = call_api(token, api_base, "getChatMemberCount", {"chat_id": chat_id})
        if bot_id is not None:
            snapshot["getChatMember_bot"] = call_api(
                token,
                api_base,
                "getChatMember",
                {"chat_id": chat_id, "user_id": bot_id},
            )
        snapshots.append(snapshot)
    return snapshots


def write_backup(output_dir: Path, data: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    output_path = output_dir / f"telegram-state-{stamp}.json"
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    latest_path = output_dir / "telegram-state-latest.json"
    shutil.copyfile(output_path, latest_path)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="备份 Telegram 机器人可读取的配置、群组和权限快照")
    parser.add_argument("--config", default=os.environ.get("TELEGRAM_CONFIG_FILE", "telegram_config.json"))
    parser.add_argument("--output-dir", default=os.environ.get("TELEGRAM_BACKUP_DIR", str(core.DATA_DIR / "telegram-state-backups")))
    parser.add_argument("--registry-file", default=os.environ.get(telegram_bot.TELEGRAM_CHAT_REGISTRY_FILE_ENV, ""))
    args = parser.parse_args()

    config = telegram_bot.load_config(args.config)
    token = str(config.get("telegram_bot_token") or "").strip()
    if not token:
        print("缺少 telegram_bot_token。请填写配置或 TELEGRAM_BOT_TOKEN。", file=sys.stderr)
        return 2
    api_base = telegram_bot.normalize_telegram_api_base(config.get("telegram_api_base"))

    registry_path = Path(args.registry_file).expanduser() if args.registry_file else telegram_bot.telegram_chat_registry_path(config)
    registry = telegram_bot.load_chat_registry(registry_path)

    bot_settings = collect_bot_settings(token, api_base)
    me_result = (bot_settings.get("getMe") or {}).get("result") if (bot_settings.get("getMe") or {}).get("ok") else {}
    bot_id = me_result.get("id") if isinstance(me_result, dict) else None
    if bot_id is not None:
        try:
            bot_id = int(bot_id)
        except (TypeError, ValueError):
            bot_id = None

    data = {
        "version": 1,
        "generated_at": int(time.time()),
        "api_base": api_base,
        "registry_file": str(registry_path),
        "registry_updated_at": registry.get("updated_at") if isinstance(registry, dict) else None,
        "bot_settings": bot_settings,
        "known_chats": collect_chat_snapshots(token, api_base, registry, bot_id),
        "limits": {
            "cannot_list_all_chats_retroactively": True,
            "cannot_list_all_group_members": True,
            "does_not_include_bot_token": True,
        },
    }

    output_path = write_backup(Path(args.output_dir).expanduser(), data)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
