import socket
import unittest
from unittest.mock import Mock, patch

import requests

from scripts.test_support import ExternalNetworkBlocked, NetworkGuard
from safety_dashboard.adapters.telegram import TelegramNotifier
from safety_dashboard.adapters.solapi import SolapiNotifier
from safety_dashboard.alerts.domain import OutgoingSmsMessage


class NetworkGuardTests(unittest.TestCase):
    def test_real_telegram_request_is_blocked_without_exposing_request(self):
        with NetworkGuard() as guard:
            with self.assertRaises(ExternalNetworkBlocked) as raised:
                TelegramNotifier("private-test-token", "fake-chat").send_batch(
                    ("test",)
                )
            self.assertNotIn("private-test-token", str(raised.exception))
            self.assertEqual(guard.attempts, 1)

    def test_mocked_telegram_transport_still_checks_message_contract(self):
        with NetworkGuard() as guard:
            with patch("safety_dashboard.adapters.telegram.requests.post") as post:
                post.return_value = Mock(json=lambda: {"ok": True})
                result = TelegramNotifier("fake-token", "fake-chat").send_batch(
                    ("test",)
                )
            self.assertTrue(result.success)
            self.assertEqual(post.call_args.kwargs["json"]["text"], "test")
            guard.assert_unused()

    def test_swallowed_sms_transport_error_still_fails_guard(self):
        service = Mock()
        service.request_type = lambda **kwargs: kwargs
        service.request_config_type = None
        service.send.side_effect = lambda *_args: requests.post(
            "https://example.invalid/send"
        )
        with NetworkGuard() as guard:
            notifier = SolapiNotifier(
                "fake-key", "fake-secret", "01000000000", service=service
            )
            notifier.send(
                OutgoingSmsMessage(
                    "delivery",
                    "batch",
                    "hash",
                    "01000000000",
                    "test",
                    ("F-1",),
                    ("T-1",),
                )
            )
            with self.assertRaises(ExternalNetworkBlocked):
                guard.assert_unused()

    def test_tcp_helpers_and_direct_sockets_are_blocked(self):
        with NetworkGuard() as guard:
            with self.assertRaises(ExternalNetworkBlocked):
                socket.create_connection(("example.invalid", 443))
            with socket.socket() as connection:
                with self.assertRaises(ExternalNetworkBlocked):
                    connection.connect(("127.0.0.1", 1))
                with self.assertRaises(ExternalNetworkBlocked):
                    connection.connect_ex(("127.0.0.1", 1))
            self.assertEqual(guard.attempts, 3)
