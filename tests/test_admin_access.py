import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from safety_dashboard.admin.access import (
    AdminAccessDeniedError,
    AdminAccessSettings,
    AdminAccessThrottledError,
    AdminAccessVerifier,
)
from safety_dashboard.api.app import create_app


class _MonitoringService:
    def monitoring(self, force_refresh=False, simulation=False):
        return {"api_version": "v1", "facilities": []}


class AdminAccessVerifierTests(unittest.TestCase):
    def test_correct_password_returns_server_session_seconds(self):
        verifier = AdminAccessVerifier(
            AdminAccessSettings(password="안전한-password", session_seconds=3600)
        )

        self.assertEqual(verifier.verify("안전한-password"), 3600)
        with self.assertRaises(AdminAccessDeniedError):
            verifier.verify("wrong-password")

    def test_repeated_failures_are_temporarily_throttled(self):
        clock = [100.0]
        verifier = AdminAccessVerifier(
            AdminAccessSettings(
                password="safe-password",
                failure_limit=3,
                failure_window_seconds=60,
            ),
            monotonic=lambda: clock[0],
        )
        for _ in range(3):
            with self.assertRaises(AdminAccessDeniedError):
                verifier.verify("wrong-password")
        with self.assertRaises(AdminAccessThrottledError):
            verifier.verify("safe-password")

        clock[0] = 161.0
        self.assertGreater(verifier.verify("safe-password"), 0)

    def test_api_does_not_return_password_and_disables_cache(self):
        verifier = AdminAccessVerifier(
            AdminAccessSettings(password="safe-password", session_seconds=7200)
        )
        client = TestClient(
            create_app(
                service=_MonitoringService(),
                admin_access_service=verifier,
            )
        )

        denied = client.post(
            "/internal/v1/admin/access",
            json={"password": "wrong-password"},
        )
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn("wrong-password", denied.text)
        empty = client.post(
            "/internal/v1/admin/access",
            json={"password": ""},
        )
        self.assertEqual(empty.status_code, 403)
        self.assertNotIn('"input"', empty.text)

        accepted = client.post(
            "/internal/v1/admin/access",
            json={"password": "safe-password"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["status"], "ok")
        self.assertEqual(accepted.json()["expires_in"], 7200)
        self.assertIn("token", accepted.json())
        self.assertIn("keco_admin_session", accepted.cookies)
        self.assertEqual(accepted.headers["cache-control"], "private, no-store")
        self.assertNotIn("safe-password", accepted.text)


class AdminSessionManagerTests(unittest.TestCase):
    def test_create_and_verify_token_round_trip(self):
        from safety_dashboard.admin.session import (
            AdminSessionExpiredError,
            AdminSessionManager,
        )

        clock = [1000.0]
        manager = AdminSessionManager("test-secret", default_lifetime_seconds=3600, time_fn=lambda: clock[0])
        token = manager.create_token()

        session = manager.verify_token(token)
        self.assertEqual(session.created_at, 1000)
        self.assertEqual(session.expires_at, 4600)

        # 유효 시간 내 검증 성공
        clock[0] = 4599.0
        self.assertEqual(manager.verify_token(token).expires_at, 4600)

        # 만료 시점 초과 시 오류
        clock[0] = 4600.0
        with self.assertRaises(AdminSessionExpiredError):
            manager.verify_token(token)

    def test_tampered_token_is_rejected(self):
        from safety_dashboard.admin.session import (
            AdminSessionError,
            AdminSessionManager,
        )

        manager = AdminSessionManager("test-secret")
        token = manager.create_token()

        with self.assertRaises(AdminSessionError):
            manager.verify_token(token + "tampered")

        with self.assertRaises(AdminSessionError):
            manager.verify_token("")


if __name__ == "__main__":
    unittest.main()
