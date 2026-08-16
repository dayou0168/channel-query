import unittest
from unittest import mock

import channel_query_app as app
import telegram_bot as bot


class ChannelMapFallbackTests(unittest.TestCase):
    def test_missing_channel_headers_still_returns_backend_account_details(self):
        backend_row = {
            "username": "demo_account",
            "address": "198.51.100.42",
            "font_rgb": "中国 河南 许昌",
            "sms_phone": "",
        }
        config = {
            "backend_base": "https://example.test",
            "backend_token": "test-token",
            "sheet_url": "https://docs.google.com/spreadsheets/d/test/edit?gid=0#gid=0",
            "service_account_file": "/config/service-account.json",
        }

        with (
            mock.patch.object(
                app,
                "load_channel_map",
                side_effect=app.ChannelMapSchemaError("渠道表中未找到“来源编号”列。"),
            ),
            mock.patch.object(app, "get_backend_token", return_value=("test-token", "配置")),
            mock.patch.object(app, "call_backend_user", return_value=backend_row),
            mock.patch.object(app.time, "sleep"),
        ):
            reply = bot.query_text("demo_account", config)

        self.assertIn("账号：<code>demo_account</code>", reply)
        self.assertIn("注册IP：<code>198.51.100.42</code>", reply)
        self.assertIn("注册省份：河南 许昌", reply)
        self.assertIn("注册来源：<code>未查到</code>", reply)
        self.assertIn("渠道编码：<code>未查到</code>", reply)
        self.assertIn("状态：注册来源为空", reply)

    def test_sheet_network_errors_are_not_suppressed(self):
        with mock.patch.object(app, "load_channel_map", side_effect=RuntimeError("Google表格读取失败：HTTP 403")):
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                app.query_accounts({"accounts": ["demo_account"]})

    def test_missing_channel_headers_preserves_backend_source(self):
        backend_row = {
            "username": "demo_account",
            "address": "198.51.100.42",
            "font_rgb": "中国 河南 许昌",
            "sms_phone": "https://615b07.example.test",
        }
        config = {
            "backend_base": "https://example.test",
            "backend_token": "test-token",
            "sheet_url": "https://docs.google.com/spreadsheets/d/test/edit?gid=0#gid=0",
            "service_account_file": "/config/service-account.json",
        }

        with (
            mock.patch.object(
                app,
                "load_channel_map",
                side_effect=app.ChannelMapSchemaError("渠道表中未找到“来源编号”列。"),
            ),
            mock.patch.object(app, "get_backend_token", return_value=("test-token", "配置")),
            mock.patch.object(app, "call_backend_user", return_value=backend_row),
            mock.patch.object(app.time, "sleep"),
        ):
            reply = bot.query_text("demo_account", config)

        self.assertIn("注册来源：<code>615b07</code>", reply)
        self.assertIn("渠道编码：<code>未查到</code>", reply)
        self.assertIn("状态：渠道表未匹配", reply)


if __name__ == "__main__":
    unittest.main()
