import io
import json
import unittest
import urllib.error
from unittest import mock

import channel_query_app as app


class FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.data


def http_error(code, body=b"<html>temporary upstream error</html>"):
    return urllib.error.HTTPError(
        "https://sheets.googleapis.com/v4/spreadsheets/test",
        code,
        "Server Error",
        {},
        io.BytesIO(body),
    )


class GoogleApiRetryTests(unittest.TestCase):
    def test_retryable_http_error_recovers(self):
        with (
            mock.patch.object(
                app.urllib.request,
                "urlopen",
                side_effect=[http_error(502), http_error(503), FakeResponse({"sheets": []})],
            ) as urlopen,
            mock.patch.object(app.time, "sleep") as sleep,
        ):
            result = app.google_api_get_json("https://sheets.googleapis.com/test", "test-token", "服务账号")

        self.assertEqual({"sheets": []}, result)
        self.assertEqual(3, urlopen.call_count)
        self.assertEqual([mock.call(1), mock.call(2)], sleep.call_args_list)

    def test_retryable_http_error_returns_short_message_after_retries(self):
        with (
            mock.patch.object(
                app.urllib.request,
                "urlopen",
                side_effect=[http_error(502) for _ in range(4)],
            ) as urlopen,
            mock.patch.object(app.time, "sleep") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "暂时失败（HTTP 502）.*已自动重试") as raised:
                app.google_api_get_json("https://sheets.googleapis.com/test", "test-token", "服务账号")

        self.assertNotIn("<html>", str(raised.exception))
        self.assertEqual(4, urlopen.call_count)
        self.assertEqual([mock.call(1), mock.call(2), mock.call(4)], sleep.call_args_list)

    def test_permission_error_does_not_retry(self):
        with (
            mock.patch.object(app.urllib.request, "urlopen", side_effect=http_error(403)) as urlopen,
            mock.patch.object(app.time, "sleep") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "服务账号无权读取表格"):
                app.google_api_get_json("https://sheets.googleapis.com/test", "test-token", "服务账号")

        self.assertEqual(1, urlopen.call_count)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
