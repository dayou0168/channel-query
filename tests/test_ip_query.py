import unittest

import channel_query_app as app
import telegram_bot as bot


class BackendIpQueryTests(unittest.TestCase):
    def test_backend_row_ip_values_accepts_common_aliases(self):
        row = {
            "clientIp": "198.51.100.42",
            "客户端ip地址": "203.0.113.9",
            "note": "not an ip",
        }

        self.assertEqual(app.backend_row_ip_values(row), ["198.51.100.42", "203.0.113.9"])

    def test_ip_query_resolves_ip_record_user_ids_through_user_list(self):
        ip_calls = []
        user_calls = []

        def fake_post_backend_ip_records_auto_refresh(base, token, payload):
            ip_calls.append(payload.copy())
            return (
                [
                    {"user_id": 10001, "ip_addr": "198.51.100.42"},
                    {"user_id": 10001, "ip_addr": "198.51.100.42"},
                    {"user_id": "10002", "ip_addr": "198.51.100.42"},
                    {"user_id": 999, "ip_addr": "203.0.113.9"},
                ],
                4,
            )

        def fake_post_backend_list_auto_refresh(base, token, payload):
            user_calls.append(payload.copy())
            user_id = payload["user_id"]
            return (
                [
                    {
                        "user_id": user_id,
                        "username": f"wpp-{user_id}",
                        "register_time": "2026-08-16 15:34:37",
                    }
                ],
                1,
            )

        original_ip = app.post_backend_ip_records_auto_refresh
        original_user = app.post_backend_list_auto_refresh
        app.post_backend_ip_records_auto_refresh = fake_post_backend_ip_records_auto_refresh
        app.post_backend_list_auto_refresh = fake_post_backend_list_auto_refresh
        try:
            rows = app.call_backend_users_by_ip("198.51.100.42", "token", "https://example.test")
        finally:
            app.post_backend_ip_records_auto_refresh = original_ip
            app.post_backend_list_auto_refresh = original_user

        self.assertEqual(ip_calls, [{"page": 1, "page_size": 100, "ip_addr": "198.51.100.42"}])
        self.assertEqual([call["user_id"] for call in user_calls], [10001, 10002])
        self.assertEqual([row["username"] for row in rows], ["wpp-10001", "wpp-10002"])

    def test_user_lookup_rejects_nonmatching_user_list_row(self):
        def fake_post_backend_list_auto_refresh(base, token, payload):
            return ([{"user_id": 999, "username": "wrong"}], 2)

        original = app.post_backend_list_auto_refresh
        app.post_backend_list_auto_refresh = fake_post_backend_list_auto_refresh
        try:
            row = app.call_backend_user_by_id(10001, "token", "https://example.test")
        finally:
            app.post_backend_list_auto_refresh = original

        self.assertIsNone(row)

    def test_telegram_ip_reply_uses_wppchat_and_registration_time(self):
        original_token = app.get_backend_token
        original_query = app.call_backend_users_by_ip
        app.get_backend_token = lambda configured_token: ("token", "test")
        app.call_backend_users_by_ip = lambda ip, token, base, limit: [
            {"user_id": 10001, "username": "demo_account", "register_time": "2026-08-16 15:34:37"}
        ]
        try:
            reply = bot.query_ip_text("查IP 198.51.100.42", {"backend_base": "https://example.test"})
        finally:
            app.get_backend_token = original_token
            app.call_backend_users_by_ip = original_query

        self.assertIn("WPPChat号：<code>demo_account</code>", reply)
        self.assertIn("注册时间：2026-08-16 15:34:37", reply)


if __name__ == "__main__":
    unittest.main()
