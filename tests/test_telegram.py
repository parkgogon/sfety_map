import unittest
from unittest.mock import Mock, patch

import requests

from safety_dashboard.adapters.telegram import TelegramNotifier


class TelegramDeliveryTests(unittest.TestCase):
    @patch("safety_dashboard.adapters.telegram.requests.post")
    def test_success_reports_every_message(self, post):
        post.return_value = Mock(json=lambda: {"ok": True})
        result = TelegramNotifier("fake-token", "fake-chat").send_batch(("one", "two"))
        self.assertTrue(result.success)
        self.assertEqual((result.sent_count, result.total_count), (2, 2))
        self.assertEqual(post.call_count, 2)

    @patch("safety_dashboard.adapters.telegram.requests.post")
    def test_partial_failure_stops_before_remaining_messages(self, post):
        post.side_effect = [
            Mock(json=lambda: {"ok": True}),
            requests.Timeout("fake failure"),
        ]
        result = TelegramNotifier("fake-token", "fake-chat").send_batch(
            ("one", "two", "three")
        )
        self.assertFalse(result.success)
        self.assertEqual((result.sent_count, result.total_count), (1, 3))
        self.assertEqual(post.call_count, 2)
