"""KMA 변화 감지, 담당자 묶음, 문자·Telegram 전파를 조율합니다."""

from __future__ import annotations

import datetime as dt
import html
import hashlib
import hmac
import uuid
from collections import Counter
from dataclasses import dataclass

from safety_dashboard.adapters.telegram import TelegramNotifier
from safety_dashboard.alerts.contacts import ContactDataError
from safety_dashboard.alerts.contacts import normalize_mobile_phone
from safety_dashboard.alerts.domain import (
    AlertBatch,
    AlertTransition,
    AlertTransitionKind,
    HealthCheck,
    OutgoingSmsMessage,
    SmsDeliveryResult,
    SmsDeliveryStatus,
    SolapiBalance,
    TelegramAudience,
    TelegramOutboxItem,
    TelegramPurpose,
    OperationalHealthReport,
    make_batch_id,
)
from safety_dashboard.alerts.messages import (
    build_alert_batch_telegram_payloads,
    build_sms_messages,
    unmapped_facility_ids,
)
from safety_dashboard.alerts.ports import (
    AlertStateStore,
    ContactProvider,
    MonitoringSnapshotProvider,
    SmsNotifier,
    SolapiBalanceProvider,
    SystemHealthProbe,
)
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.alerts.transitions import (
    deduplicate_transitions,
    detect_transitions,
    filter_impacts_by_warning_type,
    impacts_from_snapshot,
    valid_pending_transitions,
)
from safety_dashboard.domain.enums import DataHealth, KmaFailureCategory
from safety_dashboard.domain.models import (
    KmaFailureDiagnostic,
    OutgoingTelegramMessage,
)
from safety_dashboard.domain.risk_policy import RiskPolicy


KST = dt.timezone(dt.timedelta(hours=9))
ESTIMATED_LMS_COST_KRW = 45


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
    ) -> None:
        self.snapshot_provider = snapshot_provider
        self.contacts = contacts
        self.sms = sms
        self.store = store
        self.policy = policy
        self.settings = settings
        self.admin_telegram = telegram
        self.user_telegram = user_telegram
        self.balance_provider = balance_provider
        self.health_probe = health_probe
        self.kma_diagnoser = kma_diagnoser

    def run(self, now: dt.datetime | None = None) -> DispatchSummary:
        current_time = _aware(now or dt.datetime.now(KST))
        run_id = uuid.uuid4().hex
        if not self.store.acquire_lock(run_id, current_time):
            return DispatchSummary("SKIPPED_LOCKED", self.settings.automation_mode)
        try:
            self._drain_telegram_outbox(current_time)
            self._check_solapi_balance(current_time)
            result = self._run_locked(current_time)
            self._enqueue_scheduled_reports(current_time)
            self._drain_telegram_outbox(current_time)
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
                "🧪 <b>K-ECO Telegram 채널 시험</b>\n"
                f"대상 · {'관리자방' if audience is TelegramAudience.ADMIN else '사용자 채널'}\n"
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
        message = self._operational_report_message(
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
        state_key = (
            f"{mode}|{self.policy.version}|"
            f"{_warning_filter_fingerprint(self.settings)}"
        )
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
        if previous_status.get("kma_health") == "ERROR":
            started = _parse_datetime(previous_status.get("kma_failure_started_at"))
            duration = _duration_text(now - started) if started else "지속시간 미확인"
            previous_category = str(
                previous_status.get("kma_failure_category", "UNKNOWN")
            )
            self._notify_admin(
                "kma-recovered",
                now,
                "✅ KMA 자동 관제 조회가 정상화됐습니다.\n"
                f"이전 분류 · {_category_label(previous_category)}\n"
                f"장애 지속 · {duration}",
                force=True,
            )

        current_impacts = filter_impacts_by_warning_type(
            impacts_from_snapshot(snapshot, self.policy),
            self.settings.included_warning_types,
            self.settings.excluded_warning_types,
        )
        initialized, previous_mode, previous_impacts = self.store.load_state()
        new_transitions = (
            detect_transitions(previous_impacts, current_impacts, now)
            if initialized and previous_mode == state_key
            else ()
        )

        if not initialized or previous_mode != state_key:
            pending = self.store.load_pending(now)
            self.store.resolve_pending(
                [item.id for item in pending],
                "BASELINE_RESET",
            )
            self.store.save_state(current_impacts, state_key, now)
            self.store.record_run(day, {_poll_counter(mode): 1, "kma_success": 1})
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

        pending = self.store.load_pending(now) if mode == "live" else ()
        valid_pending = valid_pending_transitions(pending, current_impacts)
        valid_pending_ids = {item.id for item in valid_pending}
        stale_pending_ids = [item.id for item in pending if item.id not in valid_pending_ids]
        self.store.resolve_pending(stale_pending_ids, "STALE")
        transitions = deduplicate_transitions((*new_transitions, *valid_pending))

        if not transitions:
            self.store.save_state(current_impacts, state_key, now)
            self.store.record_run(day, {_poll_counter(mode): 1, "kma_success": 1})
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

        batch = _batch(transitions, now, mode, self.policy.version)
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
            directory = self.contacts.fetch(valid_facility_ids)
            if previous_status.get("contacts_health") == "ERROR":
                self._notify_admin(
                    "contacts-recovered",
                    now,
                    "✅ 자동 문자 연락처 조회가 정상화됐습니다.",
                )
        except ContactDataError as exc:
            return self._fallback_without_sms(
                batch,
                current_impacts,
                state_key,
                new_transitions,
                now,
                day,
                "연락처 Sheet 오류",
                "CONTACTS_ERROR",
                {"contacts_health": "ERROR", "contacts_detail": str(exc)},
                len(snapshot.warning_feed.warnings),
            )

        try:
            messages = build_sms_messages(
                batch,
                directory,
                self.settings.recipient_hmac_secret,
                self.settings.dashboard_base_url,
            )
        except ValueError as exc:
            return self._fallback_without_sms(
                batch,
                current_impacts,
                state_key,
                new_transitions,
                now,
                day,
                "문자 발송 설정 오류",
                "CONFIGURATION_ERROR",
                {"configuration_detail": str(exc)},
                len(snapshot.warning_feed.warnings),
            )

        unmapped = unmapped_facility_ids(transitions, directory)
        if mode == "preview":
            estimated_cost = len(messages) * ESTIMATED_LMS_COST_KRW
            self.store.save_batch(batch, "PREVIEW")
            self.store.save_state(current_impacts, state_key, now)
            self.store.record_run(day, {
                "preview_poll_runs": 1,
                "kma_success": 1,
                "preview_transition_count": len(transitions),
                "preview_messages": len(messages),
                "preview_estimated_cost_krw": estimated_cost,
                "preview_unmapped_facilities": len(unmapped),
            })
            self.store.update_status({
                "mode": mode,
                "policy_version": self.policy.version,
                "last_run_at": now,
                "last_result": "PREVIEW",
                "user_delivery_mode": "sms",
                "contacts_health": "LIVE",
                "contact_revision": directory.revision,
                "preview_transition_count": len(transitions),
                "preview_message_count": len(messages),
                "preview_estimated_cost_krw": estimated_cost,
                "preview_samples": [
                    {
                        "recipient_code": item.recipient_hash[:12],
                        "facility_count": len(item.facility_ids),
                        "text": item.text,
                    }
                    for item in messages[:3]
                ],
                "unmapped_facility_count": len(unmapped),
                **self._live_kma_status(
                    now, current_impacts, len(snapshot.warning_feed.warnings)
                ),
            })
            return DispatchSummary(
                "PREVIEW",
                mode,
                transition_count=len(transitions),
                message_count=len(messages),
                detail="실제 문자는 발송하지 않았습니다.",
            )

        self.store.save_batch(batch, "PROCESSING")
        counters: Counter[str] = Counter({
            "poll_runs": 1,
            "kma_success": 1,
            "unmapped_facilities": len(unmapped),
            **_transition_counters(new_transitions),
        })
        sms_today = self.store.sms_count(day)
        sms_month = self.store.monthly_sms_count(day)
        if sms_today < self.settings.cap_warning <= sms_today + len(messages):
            self._notify_admin(
                f"daily-cap-warning-{day.isoformat()}",
                now,
                f"⚠️ 오늘 자동 문자 발송이 {self.settings.cap_warning}건에 도달합니다.",
            )
        if (
            sms_month < self.settings.monthly_cap_warning
            <= sms_month + len(messages)
        ):
            self._notify_admin(
                f"monthly-cap-warning-{day:%Y-%m}",
                now,
                f"⚠️ 이번 달 자동 문자 발송이 "
                f"{self.settings.monthly_cap_warning}건에 도달합니다.",
            )

        recipient_hashes: list[str] = []
        accepted = 0
        blocked = 0
        attempted = 0
        failed = 0
        unknown = 0
        fallback_reasons: list[str] = []
        sendable: list[OutgoingSmsMessage] = []
        for message in messages:
            reservation = self.store.reserve_delivery(message, now)
            if reservation not in {SmsDeliveryStatus.RESERVED.value}:
                continue
            if (
                sms_today + attempted >= self.settings.daily_cap
                or sms_month + attempted >= self.settings.monthly_cap
            ):
                reason = (
                    "일일 발송 상한 초과"
                    if sms_today + attempted >= self.settings.daily_cap
                    else "월간 발송 상한 초과"
                )
                result = SmsDeliveryResult(
                    SmsDeliveryStatus.BLOCKED_CAP,
                    detail=reason,
                )
                self.store.record_delivery_result(message, result, now)
                counters["cap_blocked"] += 1
                blocked += 1
                fallback_reasons.append(reason)
                continue
            sendable.append(message)
            attempted += 1

        results = _send_messages(self.sms, tuple(sendable))
        for message, result in zip(sendable, results, strict=True):
            self.store.record_delivery_result(message, result, now)
            counters["sms_attempted"] += 1
            recipient_hashes.append(message.recipient_hash)
            if result.status is SmsDeliveryStatus.ACCEPTED:
                counters["sms_accepted"] += 1
                accepted += 1
            elif result.status is SmsDeliveryStatus.FAILED:
                counters["sms_failed"] += 1
                failed += 1
                fallback_reasons.append(result.detail or "SOLAPI 접수 실패")
            else:
                counters["sms_unknown"] += 1
                unknown += 1
                fallback_reasons.append("SOLAPI 결과 확인 불가")

        if unmapped:
            fallback_reasons.append(f"연락처 미등록 시설 {len(unmapped)}곳")
        fallback_queued = bool(fallback_reasons)
        if fallback_queued:
            self._enqueue_user_batch(
                batch,
                now,
                TelegramPurpose.SMS_FALLBACK,
                " · ".join(dict.fromkeys(fallback_reasons)),
            )

        self.store.save_state(current_impacts, state_key, now)
        self.store.resolve_pending(
            [item.id for item in transitions],
            "DISPATCHED",
        )
        self.store.save_batch(batch, "DISPATCHED")
        self.store.update_batch_delivery(batch.id, {
            "delivery_route": "sms",
            "sms_message_count": len(messages),
            "sms_accepted_count": accepted,
            "sms_failed_count": failed,
            "sms_unknown_count": unknown,
            "sms_blocked_count": blocked,
            "telegram_fallback_queued": fallback_queued,
        })
        self.store.record_run(day, counters, recipient_hashes)
        self.store.update_status({
            "mode": mode,
            "policy_version": self.policy.version,
            "last_run_at": now,
            "last_result": "DISPATCHED",
            "user_delivery_mode": "sms",
            "contacts_health": "LIVE",
            "contact_revision": directory.revision,
            "transition_count": len(transitions),
            "message_count": len(messages),
            "accepted_count": accepted,
            "blocked_count": blocked,
            "failed_count": failed,
            "unknown_count": unknown,
            "telegram_fallback_queued": fallback_queued,
            "unmapped_facility_count": len(unmapped),
            **self._live_kma_status(
                now, current_impacts, len(snapshot.warning_feed.warnings)
            ),
        })
        self._send_batch_summary(
            batch,
            "SMS 우선",
            len(messages),
            accepted,
            failed,
            unknown,
            blocked,
            len(unmapped),
            fallback_queued,
        )
        if blocked:
            self._notify_admin(
                f"daily-cap-blocked-{day.isoformat()}",
                now,
                f"🚫 코드 발송 상한으로 자동 문자 {blocked}건을 차단하고 "
                "사용자 Telegram 대체 전파를 예약했습니다.",
            )
        return DispatchSummary(
            "DISPATCHED",
            mode,
            transition_count=len(transitions),
            message_count=len(messages),
            accepted_count=accepted,
            blocked_count=blocked,
        )

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
        self._enqueue_user_batch(
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
            **_transition_counters(new_transitions),
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
        self._send_batch_summary(
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
            _poll_counter(mode): 1,
            "kma_success": 1,
            ("preview_sms_blocked" if mode == "preview" else "sms_path_blocked"): 1,
        }
        if mode == "preview":
            counters["preview_transition_count"] = len(batch.transitions)
        else:
            counters.update(_transition_counters(new_transitions))
            counters["telegram_fallback_queued"] = 1
            self._enqueue_user_batch(
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
        self._notify_admin(
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
            _poll_counter(mode): 1,
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
        self._notify_admin(
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

    def _notify_admin(
        self,
        key: str,
        now: dt.datetime,
        text: str,
        *,
        force: bool = False,
    ) -> None:
        due = self.store.admin_notice_due(key, now, dt.timedelta(hours=1))
        if not due and not force:
            return
        time_key = now.astimezone(KST).strftime(
            "%Y%m%d%H%M%S" if force else "%Y%m%d%H"
        )
        self.store.enqueue_telegram(TelegramOutboxItem(
            id=f"admin-{hashlib.sha256(f'{key}|{time_key}'.encode()).hexdigest()[:24]}",
            audience=TelegramAudience.ADMIN,
            purpose=TelegramPurpose.SYSTEM,
            created_at=now,
            expires_at=now + dt.timedelta(seconds=self.settings.telegram_retry_seconds),
            next_attempt_at=now,
            messages=(OutgoingTelegramMessage(text=html.escape(text)),),
        ))

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

    def _enqueue_user_batch(
        self,
        batch: AlertBatch,
        now: dt.datetime,
        purpose: TelegramPurpose,
        reason: str,
        payloads: tuple[OutgoingTelegramMessage, ...] = (),
    ) -> None:
        prefix = "user-primary" if purpose is TelegramPurpose.USER_PRIMARY else "user-fallback"
        self.store.enqueue_telegram(TelegramOutboxItem(
            id=f"{prefix}-{batch.id}",
            audience=TelegramAudience.USER,
            purpose=purpose,
            created_at=now,
            expires_at=now + dt.timedelta(seconds=self.settings.telegram_retry_seconds),
            next_attempt_at=now,
            batch_id=batch.id,
            reason=reason,
            messages=payloads,
        ))

    def _drain_telegram_outbox(self, now: dt.datetime) -> None:
        # 사용자 전파 결과로 새로 생긴 관리자 알림도
        # 같은 Scheduler 회차에 발송한다. 실패 작업은 다음 시도
        # 시각이 5분 후로 바뀌므로 반복 루프에 걸리지 않는다.
        for _ in range(5):
            due = self.store.due_telegram(now)
            if not due:
                return
            for item in due:
                self._deliver_telegram_item(item, now)

    def _deliver_telegram_item(
        self,
        item: TelegramOutboxItem,
        now: dt.datetime,
    ) -> None:
        messages = item.messages
        if not messages and item.batch_id:
            if item.purpose in {
                TelegramPurpose.USER_PRIMARY,
                TelegramPurpose.SMS_FALLBACK,
            }:
                batch = self.store.load_batch(item.batch_id)
                if batch is not None:
                    messages = build_alert_batch_telegram_payloads(
                        batch,
                        self.settings.dashboard_base_url,
                        item.reason
                        if item.purpose is TelegramPurpose.SMS_FALLBACK
                        else "",
                    )
            elif item.purpose is TelegramPurpose.SMS_FINAL:
                summary = self.store.delivery_summary(item.batch_id)
                messages = (OutgoingTelegramMessage(text=(
                    "📬 <b>문자 최종 전달 결과</b>\n"
                    f"수신 완료 {summary.get('delivered', 0)} · "
                    f"실패 {summary.get('failed', 0)} · "
                    f"결과 대기 {summary.get('accepted', 0)}\n"
                    f"배치 {html.escape(item.batch_id)}"
                )),)
        notifier = (
            self.admin_telegram
            if item.audience is TelegramAudience.ADMIN
            else self.user_telegram
        )
        if notifier is None:
            success = False
            detail = f"{item.audience.value} Telegram 설정값이 없습니다."
        elif not messages:
            success = False
            detail = "Telegram 발송 내용을 구성하지 못했습니다."
        else:
            result = notifier.send_batch(messages)
            success = bool(getattr(result, "success", True))
            detail = str(getattr(result, "message", "Telegram 발송 완료"))
        self.store.record_telegram_result(item, success, detail, now)
        self.store.update_status({
            f"last_{item.audience.value}_telegram_at": now,
            f"last_{item.audience.value}_telegram_result": (
                "SENT" if success else "FAILED"
            ),
            f"last_{item.audience.value}_telegram_detail": detail,
        })
        if item.audience is TelegramAudience.USER:
            final_failure = (
                not success
                and _aware(now) + dt.timedelta(minutes=5)
                > _aware(item.expires_at)
            )
            if success or final_failure:
                self._enqueue_user_delivery_result(
                    item,
                    now,
                    success,
                    detail,
                )

    def _enqueue_user_delivery_result(
        self,
        item: TelegramOutboxItem,
        now: dt.datetime,
        success: bool,
        detail: str,
    ) -> None:
        route = (
            "SMS 대체 전파"
            if item.purpose is TelegramPurpose.SMS_FALLBACK
            else (
                "관리자 수동 전파"
                if item.purpose is TelegramPurpose.MANUAL
                else "주경로 전파"
            )
        )
        state = "성공" if success else "30분 재시도 후 실패"
        text = (
            f"{'✅' if success else '🚨'} <b>사용자 Telegram {state}</b>\n"
            f"경로 · {route}\n"
            f"배치 · {html.escape(item.batch_id or item.id)}\n"
            f"결과 · {html.escape(detail)}"
        )
        self.store.enqueue_telegram(TelegramOutboxItem(
            id=f"admin-user-result-{item.id}",
            audience=TelegramAudience.ADMIN,
            purpose=TelegramPurpose.SYSTEM,
            created_at=now,
            expires_at=now
            + dt.timedelta(seconds=self.settings.telegram_retry_seconds),
            next_attempt_at=now,
            batch_id=item.batch_id,
            messages=(OutgoingTelegramMessage(text=text, silent=success),),
        ))

    def _check_solapi_balance(self, now: dt.datetime) -> None:
        if self.settings.user_delivery_mode != "sms":
            return
        if self.balance_provider is None:
            return
        status = dict(self.store.notification_status())
        previous_at = _parse_datetime(status.get("solapi_balance_checked_at"))
        if previous_at and _aware(previous_at) + dt.timedelta(hours=1) > now:
            return
        try:
            balance = self.balance_provider.fetch_balance()
        except Exception as exc:
            self.store.update_status({
                "solapi_balance_checked_at": now,
                "solapi_balance_health": "ERROR",
                "solapi_balance_detail": type(exc).__name__,
            })
            self._notify_admin(
                "solapi-balance-error",
                now,
                "⚠️ SOLAPI 잔액 조회 실패. 문자 시도는 계속합니다.",
            )
            return
        level = _balance_level(balance, self.settings)
        previous_level = str(status.get("solapi_balance_level", ""))
        self.store.update_status({
            "solapi_balance_checked_at": now,
            "solapi_balance_health": "LIVE",
            "solapi_balance": balance.balance,
            "solapi_point": balance.point,
            "solapi_available": balance.available,
            "solapi_balance_level": level,
        })
        if level != previous_level:
            if level == "CRITICAL":
                self._notify_admin(
                    "solapi-balance-critical",
                    now,
                    f"🚨 SOLAPI 사용 가능 금액이 {balance.available:,}원입니다. "
                    "3천원 미만이므로 충전해 주세요.",
                )
            elif level == "WARNING":
                self._notify_admin(
                    "solapi-balance-warning",
                    now,
                    f"⚠️ SOLAPI 사용 가능 금액이 {balance.available:,}원입니다. "
                    "1만원 미만이므로 충전을 준비해 주세요.",
                )
            elif previous_level in {"WARNING", "CRITICAL"}:
                self._notify_admin(
                    "solapi-balance-recovered",
                    now,
                    f"✅ SOLAPI 사용 가능 금액이 {balance.available:,}원으로 회복됐습니다.",
                )

    def _enqueue_scheduled_reports(self, now: dt.datetime) -> None:
        local = now.astimezone(KST)
        if local.hour not in {9, 18}:
            return
        slot = "09" if local.hour == 9 else "18"
        key = f"operational-health-{local.date().isoformat()}-{slot}"
        if not self.store.admin_notice_due(key, now, dt.timedelta(days=2)):
            return
        message = self._operational_report_message(
            now,
            include_metrics=slot == "09",
        )
        self.store.enqueue_telegram(TelegramOutboxItem(
            id=f"admin-health-{local.date().isoformat()}-{slot}",
            audience=TelegramAudience.ADMIN,
            purpose=TelegramPurpose.HEARTBEAT,
            created_at=now,
            expires_at=now
            + dt.timedelta(seconds=self.settings.telegram_retry_seconds),
            next_attempt_at=now,
            messages=(message,),
        ))

    def _operational_report_message(
        self,
        now: dt.datetime,
        *,
        include_metrics: bool,
        test: bool = False,
    ) -> OutgoingTelegramMessage:
        local = now.astimezone(KST)
        status = dict(self.store.notification_status())
        if self.health_probe is None:
            probe = OperationalHealthReport(now, ())
        else:
            try:
                probe = self.health_probe.check(now)
            except Exception as exc:
                probe = OperationalHealthReport(
                    now,
                    (HealthCheck("운영 경로 점검", False, type(exc).__name__),),
                )

        kma_ok = status.get("kma_health") == "LIVE"
        mode_ok = self.settings.automation_mode == "live"
        healthy = probe.healthy and kma_ok and mode_ok
        title = (
            "자동 알림 일일 요약 + 운영 상태"
            if include_metrics
            else "운영 상태 보고"
        )
        if test:
            title = "[시험] " + title
        icon = "✅" if healthy else "⚠️"
        lines = [
            f"{icon} <b>{html.escape(title)}</b>",
            f"기준 · {local:%Y-%m-%d %H:%M}",
        ]
        if include_metrics:
            report_day = local.date() - dt.timedelta(days=1)
            metrics = self.store.notification_metrics(report_day, report_day)
            totals = metrics.get("totals", {})
            if not isinstance(totals, dict):
                totals = {}
            lines.extend((
                f"\n<b>{report_day:%Y-%m-%d} 전날 실적</b>",
                f"자동 관제 · {int(totals.get('poll_runs', 0))}회",
                f"특보 변화 · 발효 {int(totals.get('warning_activated', 0))} · "
                f"격상 {int(totals.get('warning_escalated', 0))} · "
                f"해제 {int(totals.get('warning_cleared', 0))}",
                f"문자 · 시도 {int(totals.get('sms_attempted', 0))} · "
                f"수신완료 {int(totals.get('sms_delivered', 0))} · "
                f"실패 {int(totals.get('sms_delivery_failed', 0)) + int(totals.get('sms_failed', 0))}",
                f"사용자 Telegram · 주경로 {int(totals.get('telegram_user_primary_sent', 0))} · "
                f"대체 {int(totals.get('telegram_user_fallback_sent', 0))} · "
                f"실패 {int(totals.get('telegram_user_failed', 0))}",
            ))
        lines.append("\n<b>현재 시스템</b>")
        if probe.checks:
            for check in probe.checks:
                latency = (
                    f" · {check.latency_ms}ms"
                    if check.latency_ms is not None
                    else ""
                )
                lines.append(
                    f"{_health_icon(check.healthy)} {html.escape(check.name)} · "
                    f"{html.escape(check.detail)}{latency}"
                )
        lines.extend((
            f"{_health_icon(mode_ok)} 자동 관제 · "
            f"{html.escape(self.settings.automation_mode)} · "
            f"최근 {html.escape(_format_status_time(status.get('last_run_at')))}",
            f"{_health_icon(kma_ok)} KMA · "
            f"{html.escape(str(status.get('kma_health', '미확인')))} · "
            f"최근 정상 {html.escape(_format_status_time(status.get('kma_last_success_at')))} · "
            f"연속 실패 {int(status.get('kma_consecutive_errors', 0))}회",
            f"특보·시설 · 활성 {int(status.get('active_warning_count', 0))}건 · "
            f"영향 {int(status.get('affected_facility_count', 0))}곳",
            f"사용자 Telegram 최근 발송 · "
            f"{html.escape(str(status.get('last_user_telegram_result', '기록 없음')))} · "
            f"{html.escape(_format_status_time(status.get('last_user_telegram_at')))}",
            f"배포 · {html.escape(self.settings.app_revision)}",
        ))
        return OutgoingTelegramMessage(
            text="\n".join(lines),
            silent=healthy,
        )

    def _send_batch_summary(
        self,
        batch: AlertBatch,
        route: str,
        messages: int,
        accepted: int,
        failed: int,
        unknown: int,
        blocked: int,
        unmapped: int,
        fallback_queued: bool,
    ) -> None:
        warning_counts = {
            kind: len({
                item.impact.warning_key
                for item in batch.transitions
                if item.kind is kind
            })
            for kind in AlertTransitionKind
        }
        affected_facilities = len({
            item.impact.facility_id for item in batch.transitions
        })
        text = (
            "📨 <b>자동 재난특보 알림 처리</b>\n"
            f"전달 경로 · {html.escape(route)}\n"
            f"발효 {warning_counts[AlertTransitionKind.ACTIVATED]} · "
            f"격상 {warning_counts[AlertTransitionKind.ESCALATED]} · "
            f"해제 {warning_counts[AlertTransitionKind.CLEARED]}\n"
            f"영향시설 {affected_facilities}곳 · "
            f"메시지 {messages}건 · 문자 접수 {accepted} · "
            f"접수 실패 {failed} · 확인 불가 {unknown} · "
            f"상한 차단 {blocked} · 연락처 미매핑 시설 {unmapped}\n"
            f"사용자 Telegram 대체 · {'예약' if fallback_queued else '없음'}\n"
            f"정책 {html.escape(batch.policy_version)}"
        )
        self.store.enqueue_telegram(TelegramOutboxItem(
            id=f"admin-batch-{batch.id}",
            audience=TelegramAudience.ADMIN,
            purpose=TelegramPurpose.SYSTEM,
            created_at=batch.created_at,
            expires_at=batch.created_at
            + dt.timedelta(seconds=self.settings.telegram_retry_seconds),
            next_attempt_at=batch.created_at,
            batch_id=batch.id,
            messages=(OutgoingTelegramMessage(text=text),),
        ))


def _warning_filter_fingerprint(settings: AlertSettings) -> str:
    """필터 변경 시 현재 상태를 다시 기준화해 거짓 해제 알림을 막습니다."""

    included = ",".join(sorted(
        item.strip().casefold()
        for item in settings.included_warning_types
        if item.strip()
    ))
    excluded = ",".join(sorted(
        item.strip().casefold()
        for item in settings.excluded_warning_types
        if item.strip()
    ))
    digest = hashlib.sha256(
        f"include={included}|exclude={excluded}".encode("utf-8")
    ).hexdigest()[:12]
    return f"alerts-{digest}"


def _batch(
    transitions: tuple[AlertTransition, ...],
    now: dt.datetime,
    mode: str,
    policy_version: str,
) -> AlertBatch:
    return AlertBatch(
        id=make_batch_id(transitions),
        created_at=now,
        transitions=transitions,
        mode=mode,
        policy_version=policy_version,
    )


def _transition_counters(transitions: tuple[AlertTransition, ...]) -> dict[str, int]:
    counts = Counter(item.kind for item in transitions)
    warning_counts = {
        kind: len({
            item.impact.warning_key
            for item in transitions
            if item.kind is kind
        })
        for kind in AlertTransitionKind
    }
    return {
        "transition_activated": counts[AlertTransitionKind.ACTIVATED],
        "transition_escalated": counts[AlertTransitionKind.ESCALATED],
        "transition_cleared": counts[AlertTransitionKind.CLEARED],
        "warning_activated": warning_counts[AlertTransitionKind.ACTIVATED],
        "warning_escalated": warning_counts[AlertTransitionKind.ESCALATED],
        "warning_cleared": warning_counts[AlertTransitionKind.CLEARED],
        "affected_facility_events": len({
            item.impact.facility_id for item in transitions
        }),
    }


def _poll_counter(mode: str) -> str:
    return "preview_poll_runs" if mode == "preview" else "poll_runs"


def _send_messages(
    notifier: SmsNotifier,
    messages: tuple[OutgoingSmsMessage, ...],
) -> tuple[SmsDeliveryResult, ...]:
    if not messages:
        return ()
    send_many = getattr(notifier, "send_many", None)
    try:
        if callable(send_many):
            results = tuple(send_many(messages))
        else:
            results = tuple(notifier.send(item) for item in messages)
    except Exception as exc:
        results = ()
        error_name = type(exc).__name__
    else:
        error_name = "InvalidBatchResponse"
    if len(results) == len(messages):
        return results
    unknown = SmsDeliveryResult(
        SmsDeliveryStatus.UNKNOWN,
        detail=f"SOLAPI 일괄 응답 확인 불가 ({error_name})",
    )
    return tuple(
        results[index] if index < len(results) else unknown
        for index in range(len(messages))
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


def _balance_level(balance: SolapiBalance, settings: AlertSettings) -> str:
    if balance.available < settings.balance_critical:
        return "CRITICAL"
    if balance.available < settings.balance_warning:
        return "WARNING"
    return "NORMAL"


def _health_icon(healthy: bool) -> str:
    return "✅" if healthy else "❌"


def _format_status_time(value: object) -> str:
    parsed = _parse_datetime(value)
    return parsed.astimezone(KST).strftime("%m-%d %H:%M") if parsed else "기록 없음"


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
