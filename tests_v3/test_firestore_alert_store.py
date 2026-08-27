import dataclasses
import datetime as dt
import unittest

from safety_dashboard.adapters.firestore_alert_audit import (
    FirestoreAlertAuditRepository,
)
from safety_dashboard.adapters.firestore_alert_common import ALERT_COLLECTIONS
from safety_dashboard.adapters.firestore_alert_delivery import (
    FirestoreAlertDeliveryRepository,
)
from safety_dashboard.adapters.firestore_alert_outbox import (
    FirestoreTelegramOutboxRepository,
)
from safety_dashboard.adapters.firestore_alert_state import (
    FirestoreAlertStateRepository,
)
from safety_dashboard.adapters.firestore_alerts import FirestoreAlertStore
from safety_dashboard.alerts.domain import (
    AlertBatch,
    ManualTelegramCategory,
    ManualTelegramDispatch,
    TelegramAudience,
    TelegramOutboxItem,
    TelegramPurpose,
)


class _FakeDocument:
    def __init__(self, client, path: str) -> None:
        self.client = client
        self.path = path

    def set(self, value, **_kwargs) -> None:
        self.client.documents[self.path] = dict(value)

    def create(self, value) -> None:
        self.client.documents[self.path] = dict(value)


class _FakeCollection:
    def __init__(self, client, name: str) -> None:
        self.client = client
        self.name = name

    def document(self, name: str) -> _FakeDocument:
        return _FakeDocument(self.client, f"{self.name}/{name}")


class _FakeFirestoreClient:
    def __init__(self) -> None:
        self.collection_calls: list[str] = []
        self.documents: dict[str, dict[str, object]] = {}

    def collection(self, name: str) -> _FakeCollection:
        self.collection_calls.append(name)
        return _FakeCollection(self, name)


class FirestoreAlertStoreContractTests(unittest.TestCase):
    def test_collection_names_remain_compatible(self) -> None:
        self.assertEqual(
            dataclasses.asdict(ALERT_COLLECTIONS),
            {
                "state": "alert_state",
                "batches": "alert_batches",
                "pending": "alert_pending",
                "deliveries": "alert_deliveries",
                "provider_messages": "alert_provider_messages",
                "metrics": "alert_metrics",
                "admin_notices": "alert_admin_notices",
                "telegram_outbox": "alert_telegram_outbox",
                "manual_dispatches": "alert_manual_dispatches",
            },
        )

    def test_facade_keeps_constructor_and_state_document_paths(self) -> None:
        client = _FakeFirestoreClient()

        store = FirestoreAlertStore(client=client)

        self.assertEqual(client.collection_calls, ["alert_state"])
        self.assertEqual(store.state_ref.path, "alert_state/current")
        self.assertEqual(store.lock_ref.path, "alert_state/dispatch_lock")
        self.assertEqual(store.status_ref.path, "alert_state/status")

    def test_facade_keeps_existing_worker_and_admin_methods(self) -> None:
        expected_methods = {
            "acquire_lock",
            "release_lock",
            "load_state",
            "save_state",
            "save_batch",
            "update_batch_delivery",
            "load_batch",
            "save_pending",
            "load_pending",
            "resolve_pending",
            "reserve_delivery",
            "record_delivery_result",
            "sms_count",
            "monthly_sms_count",
            "delivery_summary",
            "apply_provider_report",
            "enqueue_telegram",
            "due_telegram",
            "record_telegram_result",
            "record_run",
            "update_status",
            "notification_status",
            "admin_notice_due",
            "notification_metrics",
            "create_manual_dispatch",
            "manual_dispatch",
            "update_manual_dispatch",
            "recent_duplicate",
            "notification_events",
            "export_rows",
        }

        missing = {
            name
            for name in expected_methods
            if not callable(getattr(FirestoreAlertStore, name, None))
        }

        self.assertEqual(missing, set())

    def test_core_document_field_names_remain_compatible(self) -> None:
        client = _FakeFirestoreClient()
        store = FirestoreAlertStore(client=client)
        now = dt.datetime(2026, 8, 27, 1, 0, tzinfo=dt.timezone.utc)

        store.save_state((), "live", now)
        store.save_batch(AlertBatch("batch-1", now, (), "live", "policy-v1"), "NEW")
        store.enqueue_telegram(TelegramOutboxItem(
            id="telegram-1",
            audience=TelegramAudience.USER,
            purpose=TelegramPurpose.USER_PRIMARY,
            created_at=now,
            expires_at=now + dt.timedelta(minutes=30),
            next_attempt_at=now,
        ))
        store.create_manual_dispatch(ManualTelegramDispatch(
            id="manual-1",
            created_at=now,
            category=ManualTelegramCategory.REMINDER,
            operator_label="중앙관제 관리자",
            note="",
            mode="live",
            facility_ids=("F-1",),
            warning_keys=("W-1",),
            messages=(),
            policy_version="policy-v1",
        ))

        self.assertEqual(
            set(client.documents["alert_state/current"]),
            {"initialized", "mode", "updated_at", "impacts"},
        )
        self.assertEqual(
            set(client.documents["alert_batches/batch-1"]),
            {
                "created_at",
                "mode",
                "policy_version",
                "status",
                "transition_count",
                "facility_ids",
                "transitions",
            },
        )
        self.assertEqual(
            set(client.documents["alert_telegram_outbox/telegram-1"]),
            {
                "audience",
                "purpose",
                "created_at",
                "expires_at",
                "next_attempt_at",
                "batch_id",
                "reason",
                "messages",
                "metric_scope",
                "attempt_count",
                "status",
            },
        )
        self.assertEqual(
            set(client.documents["alert_manual_dispatches/manual-1"]),
            {
                "created_at",
                "category",
                "operator_label",
                "note",
                "mode",
                "facility_ids",
                "warning_keys",
                "messages",
                "message_count",
                "policy_version",
                "temporary_policy",
                "fingerprint",
                "status",
            },
        )

    def test_facade_is_composed_from_responsibility_repositories(self) -> None:
        self.assertTrue(issubclass(FirestoreAlertStore, FirestoreAlertStateRepository))
        self.assertTrue(issubclass(FirestoreAlertStore, FirestoreAlertDeliveryRepository))
        self.assertTrue(issubclass(FirestoreAlertStore, FirestoreTelegramOutboxRepository))
        self.assertTrue(issubclass(FirestoreAlertStore, FirestoreAlertAuditRepository))


if __name__ == "__main__":
    unittest.main()
