import datetime as dt
import unittest

from fastapi.testclient import TestClient

from safety_dashboard.adapters.telegram import TelegramResult
from safety_dashboard.alerts.admin import (
    AlertAdminService,
    ManualDispatchDuplicateError,
    ManualDispatchValidationError,
)
from safety_dashboard.alerts.domain import (
    HealthCheck,
    ManualTelegramCategory,
    ManualTelegramDispatch,
    OperationalHealthReport,
)
from safety_dashboard.alerts.memory_store import InMemoryAlertStore
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.api.app import create_app
from safety_dashboard.application.notifications import build_manual_telegram_payloads
from safety_dashboard.domain.enums import DataHealth, RiskGrade, WarningLevel
from safety_dashboard.domain.models import (
    DashboardSnapshot,
    DashboardSummary,
    Facility,
    GeoPoint,
    OutgoingTelegramMessage,
    RiskAssessment,
    RiskReason,
    Warning,
    WarningFeed,
)


KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime(2026, 8, 17, 14, 0, tzinfo=KST)


class Telegram:
    def __init__(self, success=True, sent_count=None):
        self.success = success
        self.sent_count = sent_count
        self.batches = []

    def send_batch(self, messages):
        messages = tuple(messages)
        self.batches.append(messages)
        sent = (
            len(messages) if self.success else int(self.sent_count or 0)
        )
        return TelegramResult(
            self.success,
            sent,
            len(messages),
            "성공" if self.success else "일시 실패",
        )


class HealthProbe:
    def check(self, now):
        return OperationalHealthReport(now, (
            HealthCheck("사용자 웹", True, "HTTP 200", 80),
            HealthCheck("공개 API", True, "HTTP 200", 40),
            HealthCheck("사용자 Telegram", True, "대화방 접근 가능"),
        ))


class MonitoringApi:
    def monitoring(self, force_refresh=False, simulation=False):
        return {"api_version": "v1", "facilities": []}


def dispatch(
    request_id="manual-request-1",
    category=ManualTelegramCategory.REMINDER,
    note="",
    messages=None,
):
    return ManualTelegramDispatch(
        id=request_id,
        created_at=NOW,
        category=category,
        operator_label="조작된 발송자",
        note=note,
        mode="simulation" if category is ManualTelegramCategory.DRILL else "live",
        facility_ids=("F-1",),
        warning_keys=("L1070300|강풍",),
        messages=messages or (
            OutgoingTelegramMessage("📣 <b>[수동 상황전파][재공지]</b>\n시설 안내"),
        ),
        policy_version="2026.1",
    )


def snapshot():
    facility = Facility(
        "F-1",
        "구미 측정소",
        "대기측정소",
        GeoPoint(36.1, 128.3),
        "경북 구미시",
    )
    warning = Warning(
        "W-1",
        "기상청",
        "L1070000",
        "L1070300",
        "경상북도",
        "구미시",
        "강풍",
        "주의보",
        WarningLevel.ADVISORY,
    )
    assessment = RiskAssessment(
        facility,
        RiskGrade.MEDIUM,
        (RiskReason("W-1", "강풍", "주의보", RiskGrade.MEDIUM, "구미시", "강풍.주의보"),),
        "2026.1",
        NOW,
    )
    return DashboardSnapshot(
        NOW,
        WarningFeed((warning,), DataHealth.LIVE, NOW),
        (facility,),
        (assessment,),
        DashboardSummary(1, 1, 0, 0, WarningLevel.ADVISORY),
        "2026.1",
    )


def admin_service(store, user, admin=None, snapshot_provider=None):
    settings = AlertSettings(
        admin_token="admin-token",
        automation_mode="live",
        user_delivery_mode="telegram",
    )
    return AlertAdminService(
        store,
        settings,
        user_telegram=user,
        admin_telegram=admin,
        health_probe=HealthProbe(),
        manual_snapshot_provider=snapshot_provider,
    )


def test_manual_payload_marks_every_drill_message_and_escapes_note():
    payloads = build_manual_telegram_payloads(
        snapshot(),
        ManualTelegramCategory.DRILL,
        "<현장 확인>",
        scope_label="선택 시설",
        mode="모의훈련",
        dashboard_base_url="https://keco-safety-map.web.app",
    )
    assert payloads
    assert all("[수동 상황전파][훈련]" in item.text for item in payloads)
    assert all("모의훈련" in item.text and "실제 재난" in item.text for item in payloads)
    assert all("&lt;현장 확인&gt;" in item.text for item in payloads)


def test_manual_dispatch_is_audited_idempotent_and_duplicate_protected():
    store = InMemoryAlertStore()
    user = Telegram()
    admin = Telegram()
    service = admin_service(store, user, admin)

    result = service.dispatch_manual(dispatch())
    assert result["status"] == "SENT"
    stored = store.manual_dispatch("manual-request-1")["dispatch"]
    assert stored.operator_label == "중앙관제 관리자"
    assert service.dispatch_manual(dispatch())["idempotent"] is True
    assert len(user.batches) == 1
    assert len(admin.batches) == 1
    assert store.metrics[NOW.date().isoformat()]["telegram_manual_sent"] == 1

    with unittest.TestCase().assertRaises(ManualDispatchDuplicateError):
        service.dispatch_manual(dispatch("manual-request-2"))
    overridden = service.dispatch_manual(
        dispatch("manual-request-2"), allow_duplicate=True
    )
    assert overridden["status"] == "SENT"
    events = service.events(
        NOW - dt.timedelta(minutes=1),
        NOW + dt.timedelta(minutes=1),
        source="manual",
    )
    assert len(events) == 2
    assert all(item["source"] == "manual" for item in events)


def test_manual_failure_queues_only_unsent_messages_and_retry_updates_audit():
    store = InMemoryAlertStore()
    service = admin_service(store, Telegram(False, sent_count=1))
    messages = (
        OutgoingTelegramMessage("[수동 상황전파] 첫 메시지"),
        OutgoingTelegramMessage("[수동 상황전파] 둘째 메시지"),
    )
    result = service.dispatch_manual(dispatch(messages=messages))
    assert result["status"] == "RETRY_QUEUED"
    due = store.due_telegram(NOW + dt.timedelta(minutes=5))
    assert len(due) == 1
    assert due[0].messages == (messages[1],)

    store.record_telegram_result(
        due[0], True, "재시도 성공", NOW + dt.timedelta(minutes=5)
    )
    record = store.manual_dispatch("manual-request-1")
    assert record["status"] == "SENT"
    assert store.metrics[NOW.date().isoformat()]["telegram_manual_sent"] == 1


def test_manual_validation_requires_note_and_training_markers():
    service = admin_service(InMemoryAlertStore(), Telegram())
    with unittest.TestCase().assertRaisesRegex(ManualDispatchValidationError, "메모"):
        service.dispatch_manual(dispatch(category=ManualTelegramCategory.CORRECTION))
    with unittest.TestCase().assertRaisesRegex(
        ManualDispatchValidationError, "모의훈련"
    ):
        service.dispatch_manual(dispatch(
            category=ManualTelegramCategory.DRILL,
            messages=(OutgoingTelegramMessage("[수동 상황전파] 훈련"),),
        ))
    with unittest.TestCase().assertRaisesRegex(
        ManualDispatchValidationError, "전화번호"
    ):
        service.dispatch_manual(dispatch(
            "manual-phone-request",
            note="문의 010-1234-5678",
        ))


def test_manual_scope_must_match_current_affected_facilities_and_warnings():
    service = admin_service(
        InMemoryAlertStore(),
        Telegram(),
        snapshot_provider=lambda **_: snapshot(),
    )
    service.dispatch_manual(dispatch())
    invalid = ManualTelegramDispatch(
        **{
            **dispatch("manual-request-3").__dict__,
            "facility_ids": ("UNKNOWN",),
        }
    )
    with unittest.TestCase().assertRaisesRegex(
        ManualDispatchValidationError, "영향시설"
    ):
        service.dispatch_manual(invalid)


def test_manual_api_requires_token_and_accepts_valid_request():
    service = admin_service(InMemoryAlertStore(), Telegram())
    client = TestClient(create_app(
        service=MonitoringApi(),
        alert_admin_service=service,
    ))
    body = {
        "request_id": "manual-api-request",
        "category": "REMINDER",
        "mode": "live",
        "note": "",
        "facility_ids": ["F-1"],
        "warning_keys": ["L1070300|강풍"],
        "messages": [{
            "text": "📣 [수동 상황전파][재공지] 시설 안내",
            "silent": True,
        }],
        "policy_version": "2026.1",
    }
    assert client.post("/internal/v1/notifications/manual", json=body).status_code == 403
    response = client.post(
        "/internal/v1/notifications/manual",
        headers={"X-Alert-Admin-Token": "admin-token"},
        json=body,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SENT"


def test_overview_reports_worker_and_external_paths_without_secrets():
    store = InMemoryAlertStore()
    store.update_status({
        "mode": "live",
        "last_run_at": NOW,
        "kma_health": "LIVE",
        "kma_last_success_at": NOW,
        "kma_consecutive_errors": 0,
        "app_revision": "abcdef123456",
    })
    overview = admin_service(store, Telegram()).overview(NOW)
    assert overview["healthy"] is True
    assert overview["worker_fresh"] is True
    assert len(overview["checks"]) == 3
    assert "admin-token" not in str(overview)


class ManualNotificationUnittest(unittest.TestCase):
    """GitHub Actions의 unittest discover에서도 같은 시나리오를 실행한다."""

    test_manual_payload_marks_every_drill_message_and_escapes_note = staticmethod(
        test_manual_payload_marks_every_drill_message_and_escapes_note
    )
    test_manual_dispatch_is_audited_idempotent_and_duplicate_protected = staticmethod(
        test_manual_dispatch_is_audited_idempotent_and_duplicate_protected
    )
    test_manual_failure_queues_only_unsent_messages_and_retry_updates_audit = staticmethod(
        test_manual_failure_queues_only_unsent_messages_and_retry_updates_audit
    )
    test_manual_validation_requires_note_and_training_markers = staticmethod(
        test_manual_validation_requires_note_and_training_markers
    )
    test_manual_scope_must_match_current_affected_facilities_and_warnings = staticmethod(
        test_manual_scope_must_match_current_affected_facilities_and_warnings
    )
    test_manual_api_requires_token_and_accepts_valid_request = staticmethod(
        test_manual_api_requires_token_and_accepts_valid_request
    )
    test_overview_reports_worker_and_external_paths_without_secrets = staticmethod(
        test_overview_reports_worker_and_external_paths_without_secrets
    )
