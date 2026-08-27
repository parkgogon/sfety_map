import datetime as dt
import unittest

from safety_dashboard.adapters.firestore_alert_common import _transition_to_dict
from safety_dashboard.adapters.firestore_alerts import FirestoreAlertStore
from safety_dashboard.alerts.domain import (
    AlertTransition,
    AlertTransitionKind,
    FacilityImpact,
)
from safety_dashboard.domain.enums import RiskGrade, WarningLevel


NOW = dt.datetime(2026, 8, 27, 1, 0, tzinfo=dt.timezone.utc)


class _FakeSnapshot:
    def __init__(self, reference, value) -> None:
        self.reference = reference
        self.id = reference.path.rsplit("/", 1)[-1]
        self._value = dict(value)
        self.exists = True

    def to_dict(self):
        return dict(self._value)


class _FakeDocument:
    def __init__(self, client, path: str) -> None:
        self.client = client
        self.path = path

    def get(self, **_kwargs):
        value = self.client.documents.get(self.path)
        if value is None:
            snapshot = _FakeSnapshot(self, {})
            snapshot.exists = False
            return snapshot
        return _FakeSnapshot(self, value)

    def set(self, value, *, merge=False) -> None:
        existing = self.client.documents.get(self.path, {}) if merge else {}
        self.client.documents[self.path] = {**existing, **dict(value)}


class _FakeQuery:
    def __init__(self, client, collection_name: str, filters=()) -> None:
        self.client = client
        self.collection_name = collection_name
        self.filters = tuple(filters)

    def where(self, *, filter):
        condition = (filter.field_path, filter.op_string, filter.value)
        self.client.query_calls.append((self.collection_name, *condition))
        return _FakeQuery(
            self.client,
            self.collection_name,
            (*self.filters, condition),
        )

    def stream(self):
        prefix = f"{self.collection_name}/"
        self.client.streamed_paths = []
        for path, value in self.client.documents.items():
            if not path.startswith(prefix):
                continue
            if any(not _matches(value, condition) for condition in self.filters):
                continue
            self.client.streamed_paths.append(path)
            yield _FakeSnapshot(_FakeDocument(self.client, path), value)


class _FakeCollection(_FakeQuery):
    def __init__(self, client, name: str) -> None:
        super().__init__(client, name)
        self.name = name

    def document(self, name: str) -> _FakeDocument:
        return _FakeDocument(self.client, f"{self.name}/{name}")


class _FakeBatch:
    def __init__(self) -> None:
        self.operations = []

    def set(self, reference, value, *, merge=False) -> None:
        self.operations.append((reference, value, merge))

    def commit(self) -> None:
        for reference, value, merge in self.operations:
            reference.set(value, merge=merge)


class _FakeFirestoreClient:
    def __init__(self, documents) -> None:
        self.documents = {path: dict(value) for path, value in documents.items()}
        self.query_calls = []
        self.streamed_paths = []

    def collection(self, name: str) -> _FakeCollection:
        return _FakeCollection(self, name)

    def batch(self) -> _FakeBatch:
        return _FakeBatch()


def _matches(value, condition) -> bool:
    field, operator, expected = condition
    actual = value.get(field)
    if operator == "==":
        return actual == expected
    raise AssertionError(f"지원하지 않는 가짜 query 조건: {operator}")


def _transition(transition_id: str) -> AlertTransition:
    impact = FacilityImpact(
        key=f"impact-{transition_id}",
        facility_id="F-1",
        facility_name="도개수질측정소",
        warning_key="W-1",
        warning_id="warning-1",
        region_code="47190",
        region="구미시",
        warning_type="호우",
        raw_level="경보",
        warning_level=WarningLevel.WARNING,
        risk_grade=RiskGrade.HIGH,
        issued_at=NOW,
        effective_at=NOW,
        recommended_action="즉시 확인",
    )
    return AlertTransition(
        id=transition_id,
        kind=AlertTransitionKind.ACTIVATED,
        detected_at=NOW,
        previous=None,
        current=impact,
    )


def _telegram_document(
    *,
    status="PENDING",
    next_attempt_at=NOW,
    expires_at=NOW + dt.timedelta(minutes=30),
    audience="user",
):
    return {
        "status": status,
        "audience": audience,
        "purpose": "user_primary" if audience == "user" else "system",
        "created_at": NOW - dt.timedelta(minutes=1),
        "expires_at": expires_at,
        "next_attempt_at": next_attempt_at,
        "batch_id": "",
        "reason": "",
        "messages": [],
        "metric_scope": "operational",
        "attempt_count": 0,
    }


class FirestoreAlertQueryTests(unittest.TestCase):
    def test_load_pending_queries_only_pending_and_keeps_expiry_behavior(self) -> None:
        active = _transition("active")
        expired = _transition("expired")
        resolved = _transition("resolved")
        client = _FakeFirestoreClient({
            "alert_pending/active": {
                "status": "PENDING",
                "expires_at": NOW + dt.timedelta(minutes=10),
                "transition": _transition_to_dict(active),
            },
            "alert_pending/expired": {
                "status": "PENDING",
                "expires_at": NOW - dt.timedelta(seconds=1),
                "transition": _transition_to_dict(expired),
            },
            "alert_pending/resolved": {
                "status": "SENT",
                "expires_at": NOW + dt.timedelta(minutes=10),
                "transition": _transition_to_dict(resolved),
            },
        })

        result = FirestoreAlertStore(client=client).load_pending(NOW)

        self.assertEqual(tuple(item.id for item in result), ("active",))
        self.assertEqual(
            client.query_calls,
            [("alert_pending", "status", "==", "PENDING")],
        )
        self.assertEqual(
            set(client.streamed_paths),
            {"alert_pending/active", "alert_pending/expired"},
        )
        self.assertEqual(client.documents["alert_pending/expired"]["status"], "EXPIRED")
        self.assertEqual(
            client.documents["alert_pending/expired"]["delete_after"],
            NOW + dt.timedelta(days=7),
        )
        self.assertNotIn("delete_after", client.documents["alert_pending/active"])
        self.assertEqual(client.documents["alert_pending/resolved"]["status"], "SENT")

    def test_resolve_pending_sets_delete_after_and_resolved_at(self) -> None:
        client = _FakeFirestoreClient({
            "alert_pending/p-1": {
                "status": "PENDING",
                "expires_at": NOW + dt.timedelta(minutes=10),
            }
        })

        FirestoreAlertStore(client=client).resolve_pending(["p-1"], "RESOLVED")

        doc = client.documents["alert_pending/p-1"]
        self.assertEqual(doc["status"], "RESOLVED")
        self.assertIn("resolved_at", doc)
        self.assertEqual(
            doc["delete_after"].date(),
            (NOW + dt.timedelta(days=7)).date(),
        )

    def test_due_telegram_queries_only_pending_and_keeps_due_rules(self) -> None:
        client = _FakeFirestoreClient({
            "alert_telegram_outbox/due": _telegram_document(),
            "alert_telegram_outbox/future": _telegram_document(
                next_attempt_at=NOW + dt.timedelta(minutes=5)
            ),
            "alert_telegram_outbox/expired": _telegram_document(
                expires_at=NOW - dt.timedelta(seconds=1),
                audience="admin",
            ),
            "alert_telegram_outbox/sent": _telegram_document(status="SENT"),
        })

        result = FirestoreAlertStore(client=client).due_telegram(NOW)

        self.assertEqual(tuple(item.id for item in result), ("due",))
        self.assertEqual(
            client.query_calls,
            [("alert_telegram_outbox", "status", "==", "PENDING")],
        )
        self.assertEqual(
            set(client.streamed_paths),
            {
                "alert_telegram_outbox/due",
                "alert_telegram_outbox/future",
                "alert_telegram_outbox/expired",
            },
        )
        self.assertEqual(
            client.documents["alert_telegram_outbox/expired"]["status"],
            "EXPIRED",
        )
        self.assertEqual(
            client.documents["alert_telegram_outbox/expired"]["delete_after"],
            NOW + dt.timedelta(days=7),
        )
        self.assertNotIn("delete_after", client.documents["alert_telegram_outbox/due"])
        self.assertNotIn("delete_after", client.documents["alert_telegram_outbox/future"])
        self.assertEqual(
            client.documents["alert_telegram_outbox/sent"]["status"],
            "SENT",
        )

    def test_record_telegram_result_sets_delete_after_only_on_terminal(self) -> None:
        client = _FakeFirestoreClient({})
        store = FirestoreAlertStore(client=client)

        from safety_dashboard.alerts.domain import TelegramAudience, TelegramOutboxItem, TelegramPurpose

        item = TelegramOutboxItem(
            id="job-1",
            audience=TelegramAudience.ADMIN,
            purpose=TelegramPurpose.SYSTEM,
            created_at=NOW,
            expires_at=NOW + dt.timedelta(minutes=30),
            next_attempt_at=NOW,
            batch_id="",
            reason="test",
            messages=(),
            metric_scope="operational",
            attempt_count=0,
        )

        # 1. Non-terminal: 재시도 대기 (실패했지만 아직 만료되지 않음)
        store.record_telegram_result(item, success=False, detail="네트워크 오류", now=NOW)
        doc_retry = client.documents["alert_telegram_outbox/job-1"]
        self.assertEqual(doc_retry["status"], "PENDING")
        self.assertNotIn("delete_after", doc_retry)
        self.assertNotIn("completed_at", doc_retry)
        self.assertEqual(doc_retry["next_attempt_at"], NOW + dt.timedelta(minutes=5))

        # 2. Terminal: 성공 (SENT)
        store.record_telegram_result(item, success=True, detail="전송 성공", now=NOW)
        doc_sent = client.documents["alert_telegram_outbox/job-1"]
        self.assertEqual(doc_sent["status"], "SENT")
        self.assertEqual(doc_sent["completed_at"], NOW)
        self.assertEqual(doc_sent["delete_after"], NOW + dt.timedelta(days=7))

        # 3. Terminal: 만료 (EXPIRED)
        expired_item = TelegramOutboxItem(
            id="job-2",
            audience=TelegramAudience.ADMIN,
            purpose=TelegramPurpose.SYSTEM,
            created_at=NOW,
            expires_at=NOW + dt.timedelta(minutes=2),
            next_attempt_at=NOW,
            batch_id="",
            reason="test",
            messages=(),
            metric_scope="operational",
            attempt_count=1,
        )
        store.record_telegram_result(
            expired_item,
            success=False,
            detail="네트워크 오류",
            now=NOW,
        )
        doc_expired = client.documents["alert_telegram_outbox/job-2"]
        self.assertEqual(doc_expired["status"], "EXPIRED")
        self.assertEqual(doc_expired["completed_at"], NOW)
        self.assertEqual(doc_expired["delete_after"], NOW + dt.timedelta(days=7))


if __name__ == "__main__":
    unittest.main()
