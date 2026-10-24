import datetime as dt
import unittest

from fastapi.testclient import TestClient

from safety_dashboard.api.app import create_app
from safety_dashboard.operations.readiness import OperationalReadinessService


UTC = dt.timezone.utc
NOW = dt.datetime(2026, 8, 26, 3, 0, tzinfo=UTC)


class FixedReadiness(OperationalReadinessService):
    def check(self, now=None):
        return super().check(NOW)


class OperationalReadinessTests(unittest.TestCase):
    def service(self, values=None, *, raises=False):
        def status():
            if raises:
                raise RuntimeError("Firestore detail must not leak")
            return values or {}

        return FixedReadiness(status)

    def client(self, service):
        return TestClient(create_app(operational_readiness_service=service))

    def test_live_worker_with_recent_run_is_ready(self):
        service = self.service({
            "mode": "live",
            "last_run_at": NOW - dt.timedelta(minutes=5),
            "kma_health": "LIVE",
        })
        response = self.client(service).get("/api/v1/health/operations")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["worker"]["age_seconds"], 300)
        self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_stale_worker_returns_service_unavailable(self):
        service = self.service({
            "mode": "live",
            "last_run_at": (NOW - dt.timedelta(minutes=11)).isoformat(),
            "kma_health": "LIVE",
        })
        response = self.client(service).get("/api/v1/health/operations")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["worker"]["status"], "stale")
        self.assertEqual(response.json()["reason"], "worker_stale")

    def test_non_live_mode_is_degraded_even_when_worker_is_recent(self):
        service = self.service({
            "mode": "preview",
            "last_run_at": NOW - dt.timedelta(minutes=1),
            "kma_health": "LIVE",
        })
        response = self.client(service).get("/api/v1/health/operations")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["reason"], "automation_not_live")

    def test_kma_error_is_reported_but_is_not_misclassified_as_worker_outage(self):
        service = self.service({
            "mode": "live",
            "last_run_at": NOW - dt.timedelta(minutes=5),
            "kma_health": "ERROR",
        })
        response = self.client(service).get("/api/v1/health/operations")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["kma"]["status"], "error")
        self.assertEqual(response.json()["reason"], "ready")

    def test_missing_run_and_store_error_are_degraded_without_internal_detail(self):
        missing = self.client(self.service({})).get(
            "/api/v1/health/operations"
        )
        self.assertEqual(missing.status_code, 503)
        self.assertEqual(missing.json()["reason"], "worker_has_not_run")

        failed = self.client(self.service(raises=True)).get(
            "/api/v1/health/operations"
        )
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.json()["reason"], "status_store_unavailable")
        self.assertNotIn("Firestore detail", failed.text)


if __name__ == "__main__":
    unittest.main()
