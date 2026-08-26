"""KMA 변화 감지, 담당자 묶음, 문자·Telegram 전파를 조율합니다."""

from __future__ import annotations

import datetime as dt
import html
import hashlib
import hmac
import logging
import uuid
from dataclasses import dataclass

from safety_dashboard.adapters.telegram import TelegramNotifier
from safety_dashboard.alerts.contacts import ContactDataError
from safety_dashboard.alerts.contacts import normalize_mobile_phone
from safety_dashboard.alerts.cycle import (
    AlertCyclePlanner,
    poll_counter,
    transition_counters,
)
from safety_dashboard.alerts.domain import (
    AlertBatch,
    AlertTransition,
    OutgoingSmsMessage,
    SmsDeliveryResult,
    SmsDeliveryStatus,
    TelegramAudience,
    TelegramPurpose,
)
from safety_dashboard.alerts.messages import (
    build_alert_batch_telegram_payloads,
)
from safety_dashboard.alerts.operations import AlertOperationsService
from safety_dashboard.alerts.ports import (
    AlertStateStore,
    ContactProvider,
    MonitoringSnapshotProvider,
    SmsNotifier,
    SolapiBalanceProvider,
    SystemHealthProbe,
)
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.alerts.sms_delivery import (
    SmsDeliveryService,
    SmsPathUnavailable,
)
from safety_dashboard.alerts.telegram_outbox import TelegramOutboxService
from safety_dashboard.domain.enums import DataHealth, KmaFailureCategory
from safety_dashboard.domain.models import (
    DashboardSnapshot,
    KmaFailureDiagnostic,
    OutgoingTelegramMessage,
)
from safety_dashboard.domain.risk_policy import RiskPolicy
from safety_dashboard.monitoring.ports import MonitoringSnapshotStore
from safety_dashboard.monitoring.snapshot import MonitoringSnapshot


KST = dt.timezone(dt.timedelta(hours=9))
LOGGER = logging.getLogger("safety_dashboard.alerts")


@dataclass(frozen=True)
class DispatchSummary:
    status: str
    mode: str
    transition_count: int = 0
    message_count: int = 0
    accepted_count: int = 0
    blocked_count: int = 0
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "mode": self.mode,
            "transition_count": self.transition_count,
            "message_count": self.message_count,
            "accepted_count": self.accepted_count,
            "blocked_count": self.blocked_count,
            "detail": self.detail,
        }


class AlertDispatcher:
    def __init__(
        self,
        snapshot_provider: MonitoringSnapshotProvider,
        contacts: ContactProvider,
        sms: SmsNotifier,
        store: AlertStateStore,
        policy: RiskPolicy,
        settings: AlertSettings,
        telegram: TelegramNotifier | None = None,
        user_telegram: TelegramNotifier | None = None,
        balance_provider: SolapiBalanceProvider | None = None,
        health_probe: SystemHealthProbe | None = None,
        kma_diagnoser: object | None = None,
        monitoring_snapshot_store: MonitoringSnapshotStore | None = None,
    ) -> None:
        self.snapshot_provider = snapshot_provider
        self.contacts = contacts
        self.sms = sms
        self.store = store
        self.policy = policy
        self.settings = settings
        self.admin_telegram = telegram
        self.user_telegram = user_telegram
        self.kma_diagnoser = kma_diagnoser
        self.monitoring_snapshot_store = monitoring_snapshot_store
        self.cycle_planner = AlertCyclePlanner(policy, settings)
        self.telegram_outbox = TelegramOutboxService(
            store,
            settings,
            telegram,
            user_telegram,
        )
        self.sms_delivery = SmsDeliveryService(
            contacts,
            sms,
            store,
            settings,
            self.telegram_outbox,
        )
        self.operations = AlertOperationsService(
            store,
            settings,
            self.telegram_outbox,
            balance_provider,
            health_probe,
        )

    def run(self, now: dt.datetime | None = None) -> DispatchSummary:
        current_time = _aware(now or dt.datetime.now(KST))
        run_id = uuid.uuid4().hex
        if not self.store.acquire_lock(run_id, current_time):
            return DispatchSummary("SKIPPED_LOCKED", self.settings.automation_mode)
        try:
            self.telegram_outbox.drain(current_time)
            self.operations.check_solapi_balance(current_time)
            result = self._run_locked(current_time)
            self.operations.enqueue_scheduled_report(current_time)
            self.telegram_outbox.drain(current_time)
            return result
        finally:
            self.store.release_lock(run_id, current_time)

    def send_test(self, now: dt.datetime | None = None) -> DispatchSummary:
        """비공개 작업자에서 지정 시험번호로만 한 건을 발송합니다."""

        current_time = _aware(now or dt.datetime.now(KST))
        if not self.settings.recipient_hmac_secret:
            return DispatchSummary(
                "TEST_NOT_CONFIGURED",
                self.settings.automation_mode,
                detail="수신자 익명화 비밀값이 설정되지 않았습니다.",
            )
        try:
            phone = normalize_mobile_phone(self.settings.test_phone)
        except ContactDataError:
            return DispatchSummary(
                "TEST_NOT_CONFIGURED",
                self.settings.automation_mode,
                detail="시험 수신번호가 설정되지 않았습니다.",
            )
        recipient_hash = hmac.new(
            self.settings.recipient_hmac_secret.encode("utf-8"),
            phone.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        message = OutgoingSmsMessage(
            id=f"test-{uuid.uuid4().hex[:20]}",
            batch_id=f"test-{current_time:%Y%m%d%H%M%S}",
            recipient_hash=recipient_hash,
            phone=phone,
            text=(
                f"[K-ECO 재난안전][시험] {current_time:%m/%d %H:%M}\n"
                "자동 재난특보 문자 연동 시험입니다. 실제 재난 알림이 아닙니다."
            ),
            facility_ids=(),
            transition_ids=(),
        )
        reservation = self.store.reserve_delivery(
            message,
            current_time,
            metric_scope="test",
        )
        if reservation != SmsDeliveryStatus.RESERVED.value:
            return DispatchSummary(
                "TEST_SKIPPED",
                self.settings.automation_mode,
                detail="동일 시험 발송이 이미 처리됐습니다.",
            )
        result = self.sms.send(message)
        self.store.record_delivery_result(message, result, current_time)
        counters = {"test_sms_attempted": 1}
        if result.status is SmsDeliveryStatus.ACCEPTED:
            counters["test_sms_accepted"] = 1
        elif result.status is SmsDeliveryStatus.FAILED:
            counters["test_sms_failed"] = 1
        else:
            counters["test_sms_unknown"] = 1
        self.store.record_run(current_time.astimezone(KST).date(), counters)
        if self.admin_telegram:
            self.admin_telegram.send_batch((OutgoingTelegramMessage(
                text=(
                    "🧪 <b>자동 재난특보 알림 시험</b>\n"
                    f"문자 결과 · {html.escape(result.status.value)}"
                )
            ),))
        return DispatchSummary(
            "TEST_SENT" if result.status is SmsDeliveryStatus.ACCEPTED else "TEST_FAILED",
            self.settings.automation_mode,
            message_count=1,
            accepted_count=int(result.status is SmsDeliveryStatus.ACCEPTED),
            detail=result.detail,
        )

    def send_telegram_test(
        self,
        audience: TelegramAudience,
        now: dt.datetime | None = None,
    ) -> DispatchSummary:
        current_time = _aware(now or dt.datetime.now(KST))
        notifier = (
            self.admin_telegram
            if audience is TelegramAudience.ADMIN
            else self.user_telegram
        )
        if notifier is None:
            return DispatchSummary(
                "TELEGRAM_TEST_NOT_CONFIGURED",
                self.settings.automation_mode,
                detail=f"{audience.value} Telegram 설정값이 없습니다.",
            )
        result = notifier.send_batch((OutgoingTelegramMessage(
            text=(
                "🧪 <b>K-ECO Telegram 연결 시험</b>\n"
                f"대상 · {'관리자방' if audience is TelegramAudience.ADMIN else '시설담당자 그룹'}\n"
                f"시각 · {current_time:%Y-%m-%d %H:%M}\n"
                "실제 재난 알림이 아닙니다."
            ),
            silent=True,
        ),))
        return DispatchSummary(
            "TELEGRAM_TEST_SENT" if result.success else "TELEGRAM_TEST_FAILED",
            self.settings.automation_mode,
            message_count=1,
            accepted_count=int(result.success),
            detail=result.message,
        )

    def send_heartbeat_test(
        self,
        now: dt.datetime | None = None,
    ) -> DispatchSummary:
        """운영 실적과 정기 보고 중복키에 영향을 주지 않는 즉시 점검."""

        current_time = _aware(now or dt.datetime.now(KST))
        if self.admin_telegram is None:
            return DispatchSummary(
                "HEARTBEAT_TEST_NOT_CONFIGURED",
                self.settings.automation_mode,
                detail="관리자 Telegram 설정값이 없습니다.",
            )
        message = self.operations.report_message(
            current_time,
            include_metrics=False,
            test=True,
        )
        result = self.admin_telegram.send_batch((message,))
        return DispatchSummary(
            "HEARTBEAT_TEST_SENT" if result.success else "HEARTBEAT_TEST_FAILED",
            self.settings.automation_mode,
            message_count=1,
            accepted_count=int(result.success),
            detail=result.message,
        )

    def _run_locked(self, now: dt.datetime) -> DispatchSummary:
        mode = self.settings.automation_mode
        day = now.astimezone(KST).date()
        if mode == "paused":
            self.store.record_run(day, {"paused_poll_runs": 1})
            self.store.update_status({
                "mode": mode,
                "policy_version": self.policy.version,
                "last_run_at": now,
                "last_result": "PAUSED",
            })
            return DispatchSummary("PAUSED", mode)

        previous_status = dict(self.store.notification_status())
        try:
            snapshot = self.snapshot_provider.fetch()
        except Exception as exc:
            return self._kma_error(
                now,
                day,
                KmaFailureDiagnostic(
                    KmaFailureCategory.UNKNOWN,
                    "관제 snapshot을 구성하지 못함",
                    type(exc).__name__,
                    cause_type=type(exc).__name__,
                ),
            )
        if snapshot.warning_feed.health is not DataHealth.LIVE:
            return self._kma_error(
                now,
                day,
                snapshot.warning_feed.diagnostic
                or KmaFailureDiagnostic(
                    KmaFailureCategory.UNKNOWN,
                    "KMA 자료를 수신하지 못함",
                    snapshot.warning_feed.message or "세부 근거 없음",
                ),
            )
        self._save_monitoring_snapshot(snapshot, now)
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

        initialized, previous_mode, previous_impacts = self.store.load_state()
        baseline_required = (
            not initialized or previous_mode != self.cycle_planner.state_key
        )
        pending = (
            self.store.load_pending(now)
            if baseline_required or mode == "live"
            else ()
        )
        plan = self.cycle_planner.plan(
            snapshot,
            initialized=initialized,
            previous_mode=previous_mode,
            previous_impacts=previous_impacts,
            pending=pending,
            now=now,
        )
        current_impacts = plan.current_impacts
        state_key = plan.state_key
        new_transitions = plan.new_transitions

        if plan.baseline_required:
            self.store.resolve_pending(
                plan.stale_pending_ids,
                "BASELINE_RESET",
            )
            self.store.save_state(current_impacts, state_key, now)
            self.store.record_run(day, {poll_counter(mode): 1, "kma_success": 1})
            self.store.update_status({
                "mode": mode,
                "policy_version": self.policy.version,
                "last_run_at": now,
                "last_result": "BASELINED",
                "user_delivery_mode": self.settings.user_delivery_mode,
                **self._live_kma_status(
                    now, current_impacts, len(snapshot.warning_feed.warnings)
                ),
            })
            return DispatchSummary(
                "BASELINED",
                mode,
                detail="현재 특보를 기준 상태로 등록했습니다.",
            )

        self.store.resolve_pending(plan.stale_pending_ids, "STALE")
        transitions = plan.transitions

        if not transitions:
            self.store.save_state(current_impacts, state_key, now)
            self.store.record_run(day, {poll_counter(mode): 1, "kma_success": 1})
            self.store.update_status({
                "mode": mode,
                "policy_version": self.policy.version,
                "last_run_at": now,
                "last_result": "NO_CHANGE",
                "user_delivery_mode": self.settings.user_delivery_mode,
                **self._live_kma_status(
                    now, current_impacts, len(snapshot.warning_feed.warnings)
                ),
            })
            return DispatchSummary("NO_CHANGE", mode)

        batch = self.cycle_planner.batch(transitions, now)
        if self.settings.user_delivery_mode == "telegram":
            return self._dispatch_telegram_primary(
                batch,
                current_impacts,
                state_key,
                new_transitions,
                now,
                day,
                len(snapshot.warning_feed.warnings),
            )

        valid_facility_ids = [item.id for item in snapshot.facilities]
        try:
            preparation = self.sms_delivery.prepare(
                batch,
                valid_facility_ids,
                contacts_was_unhealthy=(
                    previous_status.get("contacts_health") == "ERROR"
                ),
            )
        except SmsPathUnavailable as exc:
            return self._fallback_without_sms(
                batch,
                current_impacts,
                state_key,
                new_transitions,
                now,
                day,
                exc.reason,
                exc.status,
                exc.status_values,
                len(snapshot.warning_feed.warnings),
            )

        if mode == "preview":
            self.store.save_batch(batch, "PREVIEW")
            self.store.save_state(current_impacts, state_key, now)
            self.store.record_run(day, {
                "preview_poll_runs": 1,
                "kma_success": 1,
                "preview_transition_count": len(transitions),
                "preview_messages": len(preparation.messages),
                "preview_estimated_cost_krw": preparation.estimated_cost_krw,
                "preview_unmapped_facilities": len(
                    preparation.unmapped_facility_ids
                ),
            })
            self.store.update_status({
                "mode": mode,
                "policy_version": self.policy.version,
                "last_run_at": now,
                "last_result": "PREVIEW",
                "user_delivery_mode": "sms",
                "contacts_health": "LIVE",
                "contact_revision": preparation.directory.revision,
                "preview_transition_count": len(transitions),
                "preview_message_count": len(preparation.messages),
                "preview_estimated_cost_krw": preparation.estimated_cost_krw,
                "preview_samples": preparation.preview_samples,
                "unmapped_facility_count": len(
                    preparation.unmapped_facility_ids
                ),
                **self._live_kma_status(
                    now, current_impacts, len(snapshot.warning_feed.warnings)
                ),
            })
            return DispatchSummary(
                "PREVIEW",
                mode,
                transition_count=len(transitions),
                message_count=len(preparation.messages),
                detail="실제 문자는 발송하지 않았습니다.",
            )

        outcome = self.sms_delivery.dispatch(batch, preparation, now, day)
        counters = {
            "poll_runs": 1,
            "kma_success": 1,
            **transition_counters(new_transitions),
            **outcome.counters,
        }

        self.store.save_state(current_impacts, state_key, now)
        self.store.resolve_pending(
            [item.id for item in transitions],
            "DISPATCHED",
        )
        self.store.record_run(day, counters, outcome.recipient_hashes)
        self.store.update_status({
            "mode": mode,
            "policy_version": self.policy.version,
            "last_run_at": now,
            "last_result": "DISPATCHED",
            "user_delivery_mode": "sms",
            "contacts_health": "LIVE",
            "contact_revision": preparation.directory.revision,
            "transition_count": len(transitions),
            "message_count": outcome.message_count,
            "accepted_count": outcome.accepted_count,
            "blocked_count": outcome.blocked_count,
            "failed_count": outcome.failed_count,
            "unknown_count": outcome.unknown_count,
            "telegram_fallback_queued": outcome.fallback_queued,
            "unmapped_facility_count": len(
                preparation.unmapped_facility_ids
            ),
            **self._live_kma_status(
                now, current_impacts, len(snapshot.warning_feed.warnings)
            ),
        })
        return DispatchSummary(
            "DISPATCHED",
            mode,
            transition_count=len(transitions),
            message_count=outcome.message_count,
            accepted_count=outcome.accepted_count,
            blocked_count=outcome.blocked_count,
        )

    def _save_monitoring_snapshot(
        self, dashboard: DashboardSnapshot, now: dt.datetime
    ) -> None:
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
            self.store.update_status({
                "monitoring_snapshot_health": "ERROR",
                "monitoring_snapshot_error_type": type(exc).__name__,
                "monitoring_snapshot_attempted_at": now,
            })
            return
        self.store.update_status({
            "monitoring_snapshot_health": "LIVE",
            "latest_monitoring_snapshot_id": snapshot.id,
            "latest_monitoring_snapshot_generated_at": snapshot.generated_at,
            "latest_monitoring_snapshot_kma_fetched_at": snapshot.kma_fetched_at,
            "monitoring_snapshot_stored_at": snapshot.stored_at,
            "monitoring_snapshot_error_type": "",
        })

    def _dispatch_telegram_primary(
        self,
        batch: AlertBatch,
        current_impacts: tuple,
        state_key: str,
        new_transitions: tuple[AlertTransition, ...],
        now: dt.datetime,
        day: dt.date,
        active_warning_count: int,
    ) -> DispatchSummary:
        payloads = build_alert_batch_telegram_payloads(
            batch,
            self.settings.dashboard_base_url,
        )
        if self.settings.automation_mode == "preview":
            self.store.save_batch(batch, "PREVIEW")
            self.store.save_state(current_impacts, state_key, now)
            self.store.record_run(day, {
                "preview_poll_runs": 1,
                "kma_success": 1,
                "preview_transition_count": len(batch.transitions),
                "preview_telegram_messages": len(payloads),
            })
            self.store.update_status({
                "mode": "preview",
                "user_delivery_mode": "telegram",
                "policy_version": self.policy.version,
                "last_run_at": now,
                "last_result": "PREVIEW",
                "preview_transition_count": len(batch.transitions),
                "preview_message_count": len(payloads),
                "preview_samples": [{"text": item.text} for item in payloads[:3]],
                **self._live_kma_status(now, current_impacts, active_warning_count),
            })
            return DispatchSummary(
                "PREVIEW",
                "preview",
                transition_count=len(batch.transitions),
                message_count=len(payloads),
                detail="실제 사용자 Telegram은 발송하지 않았습니다.",
            )

        self.store.save_batch(batch, "DISPATCHED")
        self.store.update_batch_delivery(batch.id, {
            "delivery_route": "telegram",
            "telegram_primary_queued": True,
        })
        self.telegram_outbox.enqueue_user_batch(
            batch,
            now,
            TelegramPurpose.USER_PRIMARY,
            "",
            payloads,
        )
        self.store.save_state(current_impacts, state_key, now)
        self.store.resolve_pending(
            [item.id for item in batch.transitions], "DISPATCHED"
        )
        self.store.record_run(day, {
            "poll_runs": 1,
            "kma_success": 1,
            **transition_counters(new_transitions),
        })
        self.store.update_status({
            "mode": "live",
            "user_delivery_mode": "telegram",
            "policy_version": self.policy.version,
            "last_run_at": now,
            "last_result": "DISPATCHED",
            "transition_count": len(batch.transitions),
            "message_count": len(payloads),
            **self._live_kma_status(now, current_impacts, active_warning_count),
        })
        self.telegram_outbox.enqueue_batch_summary(
            batch,
            "Telegram 전용",
            len(payloads),
            0,
            0,
            0,
            0,
            0,
            False,
        )
        return DispatchSummary(
            "DISPATCHED",
            "live",
            transition_count=len(batch.transitions),
            message_count=len(payloads),
        )

    def _fallback_without_sms(
        self,
        batch: AlertBatch,
        current_impacts: tuple,
        state_key: str,
        new_transitions: tuple[AlertTransition, ...],
        now: dt.datetime,
        day: dt.date,
        reason: str,
        status: str,
        status_values: dict[str, object],
        active_warning_count: int,
    ) -> DispatchSummary:
        mode = self.settings.automation_mode
        self.store.save_batch(
            batch, "PREVIEW_BLOCKED" if mode == "preview" else "FALLBACK_QUEUED"
        )
        self.store.save_state(current_impacts, state_key, now)
        counters = {
            poll_counter(mode): 1,
            "kma_success": 1,
            ("preview_sms_blocked" if mode == "preview" else "sms_path_blocked"): 1,
        }
        if mode == "preview":
            counters["preview_transition_count"] = len(batch.transitions)
        else:
            counters.update(transition_counters(new_transitions))
            counters["telegram_fallback_queued"] = 1
            self.telegram_outbox.enqueue_user_batch(
                batch, now, TelegramPurpose.SMS_FALLBACK, reason
            )
            self.store.resolve_pending(
                [item.id for item in batch.transitions], "FALLBACK_QUEUED"
            )
        self.store.record_run(day, counters)
        self.store.update_status({
            "mode": mode,
            "user_delivery_mode": "sms",
            "policy_version": self.policy.version,
            "last_run_at": now,
            "last_result": status,
            "telegram_fallback_queued": mode == "live",
            **self._live_kma_status(now, current_impacts, active_warning_count),
            **status_values,
        })
        self.telegram_outbox.notify_admin(
            f"sms-path-{status.lower()}",
            now,
            f"⚠️ 자동 문자 경로 사용 불가: {reason}. "
            + (
                "사용자 Telegram 대체 전파를 예약했습니다."
                if mode == "live"
                else "미리보기에서는 실제 대체 전파하지 않습니다."
            ),
        )
        return DispatchSummary(
            status,
            mode,
            transition_count=len(batch.transitions),
            detail=reason,
        )

    def _kma_error(
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
        self.store.record_run(day, {
            poll_counter(mode): 1,
            "preview_kma_errors" if mode == "preview" else "kma_errors": 1,
        })
        self.store.update_status({
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
        })
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
    def _live_kma_status(
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
            "affected_facility_count": len({item.facility_id for item in current_impacts}),
        }


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
