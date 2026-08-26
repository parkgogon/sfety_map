import dataclasses
import datetime as dt
import unittest

from safety_dashboard.adapters.firestore_monitoring import (
    FirestoreMonitoringSnapshotStore,
)
from safety_dashboard.application.contacts import public_contact
from safety_dashboard.domain import (
    DashboardSnapshot,
    DashboardSummary,
    DataHealth,
    Facility,
    GeoPoint,
    RiskAssessment,
    RiskGrade,
    RiskReason,
    Warning,
    WarningFeed,
    WarningLevel,
)
from safety_dashboard.monitoring.snapshot import (
    MONITORING_SNAPSHOT_SCHEMA_VERSION,
    MonitoringSnapshot,
    MonitoringSnapshotError,
)


KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime(2026, 8, 26, 14, 0, tzinfo=KST)


def _dashboard(*, health=DataHealth.LIVE) -> DashboardSnapshot:
    first = Facility(
        "F-1",
        "도개수질측정소",
        "수질측정소",
        GeoPoint(36.2, 128.3),
        "경북 구미시",
        "환경서비스부",
        "홍길동 과장(010-1234-5678)",
        metadata={"내부전화": "010-9999-8888", "비고": "원본 전용"},
    )
    second = Facility(
        "F-2",
        "구미대기측정소",
        "대기측정소",
        GeoPoint(36.1, 128.4),
        "경북 구미시",
        "환경관리부",
        "김담당 대리",
    )
    warning = Warning(
        "W-1",
        "기상청",
        "L1000000",
        "L1070300",
        "경상북도",
        "구미시",
        "호우",
        "경보",
        WarningLevel.WARNING,
        command="발표",
        issued_at=NOW - dt.timedelta(minutes=10),
        effective_at=NOW - dt.timedelta(minutes=5),
    )
    reason = RiskReason(
        warning.id,
        warning.warning_type,
        warning.raw_level,
        RiskGrade.HIGH,
        warning.region,
        "호우.WARNING",
    )
    assessments = (
        RiskAssessment(first, RiskGrade.HIGH, (reason,), "2026.1", NOW),
        RiskAssessment(second, RiskGrade.NONE, (), "2026.1", NOW),
    )
    return DashboardSnapshot(
        NOW,
        WarningFeed((warning,), health, NOW - dt.timedelta(minutes=1)),
        (first, second),
        assessments,
        DashboardSummary(1, 1, 1, 0, WarningLevel.WARNING),
        "2026.1",
        ("정상 관제",),
    )


class _FakeDocumentSnapshot:
    def __init__(self, value):
        self._value = value
        self.exists = value is not None

    def to_dict(self):
        return dict(self._value or {})


class _FakeDocument:
    def __init__(self, client, path):
        self.client = client
        self.path = path

    def get(self):
        return _FakeDocumentSnapshot(self.client.documents.get(self.path))


class _FakeCollection:
    def __init__(self, client, name):
        self.client = client
        self.name = name

    def document(self, name):
        return _FakeDocument(self.client, f"{self.name}/{name}")


class _FakeBatch:
    def __init__(self, client):
        self.client = client
        self.operations = []

    def set(self, reference, value):
        self.operations.append((reference.path, dict(value)))

    def commit(self):
        self.client.batch_commits.append(tuple(path for path, _ in self.operations))
        for path, value in self.operations:
            self.client.documents[path] = value


class _FakeFirestoreClient:
    def __init__(self):
        self.documents = {}
        self.batch_commits = []

    def collection(self, name):
        return _FakeCollection(self, name)

    def batch(self):
        return _FakeBatch(self)


def test_monitoring_snapshot_round_trip_and_data_minimization():
    dashboard = _dashboard()
    first = MonitoringSnapshot.capture(dashboard, stored_at=NOW)
    repeated = MonitoringSnapshot.capture(
        dashboard, stored_at=NOW + dt.timedelta(seconds=30)
    )
    assert first.id == repeated.id
    assert first.schema_version == MONITORING_SNAPSHOT_SCHEMA_VERSION

    document = first.to_document()
    serialized = str(document)
    assert "010-1234-5678" not in serialized
    assert "010-9999-8888" not in serialized
    assert "원본 전용" not in serialized

    restored = MonitoringSnapshot.from_document(document)
    assert restored.id == first.id
    assert restored.dashboard.warning_feed.warnings == dashboard.warning_feed.warnings
    assert restored.dashboard.summary == dashboard.summary
    assert tuple(item.grade for item in restored.dashboard.assessments) == (
        RiskGrade.HIGH,
        RiskGrade.NONE,
    )
    assert public_contact(restored.dashboard.facilities[0]) == "환경서비스부 · 홍길동 과장"


def test_monitoring_snapshot_rejects_non_live_and_inconsistent_results():
    with _raises(MonitoringSnapshotError):
        MonitoringSnapshot.capture(_dashboard(health=DataHealth.STALE))

    source = _dashboard()
    invalid = dataclasses.replace(
        source,
        summary=dataclasses.replace(source.summary, affected_facility_count=2),
    )
    with _raises(MonitoringSnapshotError):
        MonitoringSnapshot.capture(invalid)


def test_firestore_monitoring_store_writes_snapshot_and_pointer_atomically():
    client = _FakeFirestoreClient()
    store = FirestoreMonitoringSnapshotStore(client=client)
    assert store.load_latest() is None

    expected = MonitoringSnapshot.capture(_dashboard(), stored_at=NOW)
    store.save_latest(expected)

    assert client.batch_commits == [(
        f"monitoring_snapshots/{expected.id}",
        "monitoring_state/latest",
    )]
    restored = store.load_latest()
    assert restored is not None
    assert restored.id == expected.id
    assert restored.dashboard.summary == expected.dashboard.summary


class _raises:
    def __init__(self, error_type):
        self.error_type = error_type

    def __enter__(self):
        return self

    def __exit__(self, error_type, error, _traceback):
        if error_type is None:
            raise AssertionError(f"{self.error_type.__name__} 예외가 발생하지 않았습니다.")
        return issubclass(error_type, self.error_type)


class MonitoringSnapshotTests(unittest.TestCase):
    test_monitoring_snapshot_round_trip_and_data_minimization = staticmethod(
        test_monitoring_snapshot_round_trip_and_data_minimization
    )
    test_monitoring_snapshot_rejects_non_live_and_inconsistent_results = staticmethod(
        test_monitoring_snapshot_rejects_non_live_and_inconsistent_results
    )
    test_firestore_monitoring_store_writes_snapshot_and_pointer_atomically = staticmethod(
        test_firestore_monitoring_store_writes_snapshot_and_pointer_atomically
    )
