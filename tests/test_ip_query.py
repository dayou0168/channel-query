import unittest

import channel_query_app as app


class BackendIpQueryTests(unittest.TestCase):
    def test_backend_row_ip_values_accepts_common_aliases(self):
        row = {
            "clientIp": "183.202.211.13",
            "客户端ip地址": "10.0.0.1",
            "note": "not an ip",
        }

        self.assertEqual(app.backend_row_ip_values(row), ["183.202.211.13", "10.0.0.1"])

    def test_ip_query_merges_backend_query_modes(self):
        calls = []

        def fake_post_backend_list_auto_refresh(base, token, payload):
            calls.append(payload.copy())
            if "address" in payload:
                return (
                    [
                        {"id": 1, "username": "first", "address": "183.202.211.13"},
                        {"id": 2, "username": "second", "address": "183.202.211.13"},
                    ],
                    2,
                )
            if "client_ip" in payload and payload["is_like"] == 2:
                return (
                    [
                        {"id": 1, "username": "first", "address": "183.202.211.13"},
                        {"id": 2, "username": "second", "address": "183.202.211.13"},
                        {"id": 3, "username": "third", "clientIp": "183.202.211.13"},
                    ],
                    3,
                )
            return ([{"id": 999, "username": "other", "address": "8.8.8.8"}], 1)

        original = app.post_backend_list_auto_refresh
        app.post_backend_list_auto_refresh = fake_post_backend_list_auto_refresh
        try:
            rows = app.call_backend_users_by_ip("183.202.211.13", "token", "https://example.test")
        finally:
            app.post_backend_list_auto_refresh = original

        self.assertEqual([row["username"] for row in rows], ["first", "second", "third"])
        self.assertIn(("address", 2), [(next(key for key in call if key in app.BACKEND_IP_QUERY_KEYS), call["is_like"]) for call in calls])
        self.assertIn(("client_ip", 2), [(next(key for key in call if key in app.BACKEND_IP_QUERY_KEYS), call["is_like"]) for call in calls])


if __name__ == "__main__":
    unittest.main()
