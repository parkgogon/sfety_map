import csv
import datetime as dt
import io
import unittest

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from safety_dashboard.admin.session import AdminSessionManager
from safety_dashboard.alerts.admin import AlertAdminService
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.api.routes.notifications import build_router
from safety_dashboard.alerts.domain import AlertBatch, ManualTelegramCategory, ManualTelegramDispatch
from safety_dashboard.alerts.history import delivery_history, history_csv
from safety_dashboard.alerts.memory_store import InMemoryAlertStore
from safety_dashboard.application.context_info import KST
from safety_dashboard.application.message_pipeline import MemoryPipelineStore, stamp


class UnifiedHistoryTests(unittest.TestCase):
    def test_full_period_receipts_retries_and_csv(self):
        start = dt.datetime(2026, 11, 20, tzinfo=KST)
        before = start - dt.timedelta(seconds=1)
        alerts = InMemoryAlertStore()
        for key, mode in (("retry", "live"), ("preview", "preview")):
            alerts.save_batch(AlertBatch(key, before, (), mode), "DISPATCHED")
            alerts.update_batch_delivery(key, {"telegram_completed_at": start,
                                               "telegram_status": "SENT",
                                               "telegram_detail": "3건을 발송했습니다."})
        drill = ManualTelegramDispatch("drill", start, ManualTelegramCategory.DRILL, "", "",
                                       "simulation", ("a",), (), ())
        alerts.create_manual_dispatch(drill)
        alerts.update_manual_dispatch("drill", {"status": "SENT"})
        pipeline = MemoryPipelineStore()
        for i in range(206):
            time = stamp(start if i < 205 else start + dt.timedelta(days=1))
            state = "rejected" if i == 1 else "sent"
            pipeline.values[str(i)] = dict(queue_key=f"MH|{time}|{i}", updated_at=time,
                                           id=str(i), state=state, destination="admin_group" if i == 2 else "staff_group",
                                           message_id=None if i == 3 else i+1, record_id="test")
        report = delivery_history(alerts, pipeline, start.date(), start.date())
        self.assertEqual(report["sent"], {"automatic": 1, "disaster": 202})
        rows = report["events"]
        self.assertEqual(len(rows), 206)
        self.assertEqual(next(r for r in rows if r["id"] == "retry")["message_count"], 3)
        exported = list(csv.DictReader(io.StringIO(history_csv(report).decode("utf-8-sig"))))
        self.assertEqual([r["전파 ID"] for r in exported], [r["id"] for r in rows])
        self.assertTrue(all(r["처리 시각 (한국시간)"].startswith("2026-11-20") for r in exported))

    def test_route_authentication_csv_and_unavailable_store(self):
        pipeline = MemoryPipelineStore()
        preparation = SimpleNamespace(store_factory=lambda: pipeline)
        sessions = AdminSessionManager("test-session")
        admin = AlertAdminService(InMemoryAlertStore(), AlertSettings(admin_token="test-token"))
        app = FastAPI()
        app.include_router(build_router(SimpleNamespace(
            monitoring_service=None,
            session_manager=sessions,
            notification_admin=lambda: admin,
            message_notification_preparation=preparation,
        )))
        path = "/internal/v1/notifications/history?from=2026-11-20&to=2026-11-20"
        with TestClient(app) as client:
            self.assertEqual(client.get(path).status_code, 403)
            client.cookies.set(sessions.COOKIE_NAME, sessions.create_token())
            result = client.get(path)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.headers["cache-control"], "private, no-store")
            self.assertEqual(result.json()["events"], [])
            file = client.get(path + "&format=csv")
            self.assertEqual(file.status_code, 200)
            self.assertTrue(file.headers["content-type"].startswith("text/csv"))

            def unavailable():
                raise RuntimeError("test storage failure")

            preparation.store_factory = unavailable
            self.assertEqual(client.get(path).status_code, 503)
