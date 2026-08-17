import datetime as dt
import unittest
from unittest.mock import Mock, patch

from safety_dashboard.adapters.operational_health import HttpSystemHealthProbe
from safety_dashboard.adapters.telegram import TelegramNotifier


class OperationalHealthTests(unittest.TestCase):
    @patch("safety_dashboard.adapters.telegram.requests.post")
    def test_get_chat_checks_access_without_posting_message(self, post):
        response = Mock()
        response.json.return_value = {
            "ok": True,
            "result": {"title": "K-ECO 시설 재난특보"},
        }
        response.raise_for_status.return_value = None
        post.return_value = response

        result = TelegramNotifier("bot-token", "-100123").check_chat()

        self.assertTrue(result.success)
        self.assertEqual(result.title, "K-ECO 시설 재난특보")
        self.assertIn("/getChat", post.call_args.args[0])
        self.assertNotIn("/sendMessage", post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs["json"], {"chat_id": "-100123"})

    @patch("safety_dashboard.adapters.operational_health.requests.get")
    def test_web_api_and_telegram_are_combined(self, get):
        response = Mock(status_code=200)
        get.return_value = response
        telegram = Mock()
        telegram.check_chat.return_value = Mock(
            success=True,
            title="사용자 채널",
            message="",
        )
        report = HttpSystemHealthProbe(
            "https://example.test",
            telegram,
        ).check(dt.datetime(2026, 8, 17, tzinfo=dt.timezone.utc))

        self.assertTrue(report.healthy)
        self.assertEqual(len(report.checks), 3)
        self.assertEqual({item.name for item in report.checks}, {
            "사용자 웹",
            "공개 API",
            "사용자 Telegram",
        })
        telegram.check_chat.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
