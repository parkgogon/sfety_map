import unittest
from unittest.mock import patch

import telegram_utils


class TelegramUtilsTests(unittest.TestCase):
    @patch("telegram_utils.send_telegram_alert")
    def test_batch_reports_complete_delivery(self, send_alert):
        send_alert.return_value = (True, "ok")
        result = telegram_utils.send_telegram_alert_batch(
            "token",
            "chat",
            ["one", "two"],
        )
        self.assertTrue(result.success)
        self.assertEqual(result.sent_count, 2)
        self.assertEqual(result.total_count, 2)

    @patch("telegram_utils.send_telegram_alert")
    def test_batch_reports_partial_failure(self, send_alert):
        send_alert.side_effect = [(True, "ok"), (False, "network")]
        result = telegram_utils.send_telegram_alert_batch(
            "token",
            "chat",
            ["one", "two", "three"],
        )
        self.assertFalse(result.success)
        self.assertEqual(result.sent_count, 1)
        self.assertEqual(result.total_count, 3)
        self.assertIn("1/3", result.message)


if __name__ == "__main__":
    unittest.main()
