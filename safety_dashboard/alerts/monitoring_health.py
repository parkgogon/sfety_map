from __future__ import annotations
import datetime as dt
import logging
from safety_dashboard.alerts.cycle import poll_counter
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.alerts.telegram_outbox import TelegramOutboxService
from safety_dashboard.domain.enums import KmaFailureCategory
from safety_dashboard.domain.models import DashboardSnapshot, KmaFailureDiagnostic
from safety_dashboard.domain.risk_policy import RiskPolicy
from safety_dashboard.monitoring.ports import MonitoringSnapshotStore
from safety_dashboard.monitoring.snapshot import MonitoringSnapshot

from typing import Mapping
from safety_dashboard.alerts.domain import DispatchSummary
from safety_dashboard.alerts.ports import AlertAuditRepository

KST = dt.timezone(dt.timedelta(hours=9))
LOGGER = logging.getLogger("safety_dashboard.alerts")


class MonitoringHealthService:
    """KMA 장애·복구와 공통 snapshot 저장 상태. 알림 기준 상태는 갱신하지 않는다."""

    def __init__(
        self,
        store: AlertAuditRepository,
        settings: AlertSettings,
        policy: RiskPolicy,
        telegram_outbox: TelegramOutboxService,
        kma_diagnoser: object | None = None,
        monitoring_snapshot_store: MonitoringSnapshotStore | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.policy = policy
        self.telegram_outbox = telegram_outbox
        self.kma_diagnoser = kma_diagnoser
        self.monitoring_snapshot_store = monitoring_snapshot_store

    def save_snapshot(self, dashboard: DashboardSnapshot, now: dt.datetime) -> None:
        """공통 snapshot 저장 실패를 기존 자동 알림 흐름과 격리합니다."""

        if self.monitoring_snapshot_store is None:
            return
        try:
            snapshot = MonitoringSnapshot.capture(dashboard, stored_at=now)
            self.monitoring_snapshot_store.save_latest(snapshot)
        except Exception as exc:
            LOGGER.warning(
                "monitoring_snapshot_save_failed type=%s",
                type(exc).__name__,
            )
            self.store.update_status(
                {
                    "monitoring_snapshot_health": "ERROR",
                    "monitoring_snapshot_error_type": type(exc).__name__,
                    "monitoring_snapshot_attempted_at": now,
                }
            )
            return
        self.store.update_status(
            {
                "monitoring_snapshot_health": "LIVE",
                "latest_monitoring_snapshot_id": snapshot.id,
                "latest_monitoring_snapshot_generated_at": snapshot.generated_at,
                "latest_monitoring_snapshot_kma_fetched_at": snapshot.kma_fetched_at,
                "monitoring_snapshot_stored_at": snapshot.stored_at,
                "monitoring_snapshot_error_type": "",
            }
        )

    def record_error(
        self,
        now: dt.datetime,
        day: dt.date,
        diagnostic: KmaFailureDiagnostic,
    ) -> DispatchSummary:
        mode = self.settings.automation_mode
        diagnose = getattr(self.kma_diagnoser, "diagnose", None)
        if callable(diagnose):
            try:
                diagnostic = diagnose(diagnostic)
            except Exception:
                # 제어 점검 실패로 본래 KMA 장애 처리를 중단하지 않는다.
                pass
        previous = dict(self.store.notification_status())
        was_error = previous.get("kma_health") == "ERROR"
        previous_category = str(previous.get("kma_failure_category", ""))
        category_changed = was_error and previous_category != diagnostic.category.value
        started = (
            _parse_datetime(previous.get("kma_failure_started_at"))
            if was_error
            else now
        ) or now
        consecutive = int(previous.get("kma_consecutive_errors", 0)) + 1
        self.store.record_run(
            day,
            {
                poll_counter(mode): 1,
                "preview_kma_errors" if mode == "preview" else "kma_errors": 1,
            },
        )
        self.store.update_status(
            {
                "mode": mode,
                "policy_version": self.policy.version,
                "last_run_at": now,
                "last_result": "KMA_ERROR",
                "kma_health": "ERROR",
                "kma_detail": diagnostic.summary,
                "kma_failure_category": diagnostic.category.value,
                "kma_failure_summary": diagnostic.summary,
                "kma_failure_evidence": diagnostic.evidence,
                "kma_failure_started_at": started,
                "kma_consecutive_errors": consecutive,
                "kma_next_retry_at": now + dt.timedelta(minutes=5),
            }
        )
        last_success = _parse_datetime(previous.get("kma_last_success_at"))
        last_success_text = (
            last_success.astimezone(KST).strftime("%m-%d %H:%M")
            if last_success
            else "기록 없음"
        )
        self.telegram_outbox.notify_admin(
            f"kma-error-{diagnostic.category.value}",
            now,
            "⚠️ KMA 자동 관제 조회 실패\n"
            f"추정 원인 · {diagnostic.category.label}\n"
            f"판단 · {diagnostic.summary}\n"
            f"근거 · {diagnostic.evidence}\n"
            f"최근 정상 · {last_success_text}\n"
            f"연속 실패 · {consecutive}회\n"
            "조치 · 이전 특보 보존, 해제·사용자 알림 중단\n"
            "다음 재시도 · 5분 이내",
            force=not was_error or category_changed,
        )
        return DispatchSummary(
            "KMA_ERROR",
            mode,
            detail="KMA 자료 미수신으로 상태를 변경하지 않았습니다.",
        )

    @staticmethod
    def live_status(
        now: dt.datetime,
        current_impacts: tuple,
        active_warning_count: int | None = None,
    ) -> dict[str, object]:
        return {
            "kma_health": "LIVE",
            "kma_last_success_at": now,
            "kma_consecutive_errors": 0,
            "kma_failure_category": "",
            "kma_failure_summary": "",
            "kma_failure_evidence": "",
            "kma_failure_started_at": "",
            "active_impact_count": len(current_impacts),
            "active_warning_count": (
                active_warning_count
                if active_warning_count is not None
                else len({item.warning_key for item in current_impacts})
            ),
            "affected_facility_count": len(
                {item.facility_id for item in current_impacts}
            ),
        }

    def record_recovery(
        self, previous_status: Mapping[str, object], now: dt.datetime
    ) -> None:
        if previous_status.get("kma_health") == "ERROR":
            started = _parse_datetime(previous_status.get("kma_failure_started_at"))
            duration = _duration_text(now - started) if started else "지속시간 미확인"
            previous_category = str(
                previous_status.get("kma_failure_category", "UNKNOWN")
            )
            self.telegram_outbox.notify_admin(
                "kma-recovered",
                now,
                "✅ KMA 자동 관제 조회가 정상화됐습니다.\n"
                f"이전 분류 · {_category_label(previous_category)}\n"
                f"장애 지속 · {duration}",
                force=True,
            )


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=KST)


def _parse_datetime(value: object) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return _aware(parsed)


def _duration_text(value: dt.timedelta) -> str:
    seconds = max(0, int(value.total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}시간 {minutes}분"
    return f"{minutes}분"


def _category_label(value: str) -> str:
    try:
        return KmaFailureCategory(value).label
    except ValueError:
        return KmaFailureCategory.UNKNOWN.label
