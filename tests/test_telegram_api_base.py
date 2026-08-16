import json
import os
import tempfile
import unittest
from unittest import mock

import telegram_bot as bot


class TelegramApiBaseTests(unittest.TestCase):
    def test_environment_api_base_overrides_json_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "telegram_config.json")
            with open(config_path, "w", encoding="utf-8") as file:
                json.dump(
                    {
                        "telegram_bot_token": "test-token",
                        "telegram_api_base": "https://api.telegram.org",
                    },
                    file,
                )
            with mock.patch.dict(os.environ, {"TELEGRAM_API_BASE": "https://telegram-proxy.example/api"}):
                config = bot.load_config(config_path)

        self.assertEqual(config["telegram_api_base"], "https://telegram-proxy.example/api")

    def test_telegram_request_uses_custom_api_base(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self):
                return b'{"ok":true,"result":{"username":"test_bot"}}'

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return FakeResponse()

        with mock.patch.object(bot.urllib.request, "urlopen", fake_urlopen):
            result = bot.telegram_request(
                "123456:test-token",
                "getMe",
                api_base="telegram-proxy.example/api/",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(captured["url"], "https://telegram-proxy.example/api/bot123456:test-token/getMe")
        self.assertEqual(captured["timeout"], 65)


if __name__ == "__main__":
    unittest.main()
