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
    OutgoingSmsMessage,
    SmsDeliveryResult,
    SmsDeliveryStatus,
    make_batch_id,
)
from safety_dashboard.alerts.messages import build_sms_messages, unmapped_facility_ids
from safety_dashboard.alerts.ports import (
    AlertStateStore,
    ContactProvider,
    MonitoringSnapshotProvider,
    SmsNotifier,
)
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.alerts.transitions import (
    deduplicate_transitions,
    detect_transitions,
    impacts_from_snapshot,
    valid_pending_transitions,
)
from safety_dashboard.domain.enums import DataHealth
from safety_dashboard.domain.models import OutgoingTelegramMessage
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
    ) -> None:
        self.snapshot_provider = snapshot_provider
        self.contacts = contacts
        self.sms = sms
        self.store = store
        self.policy = policy
        self.settings = settings
        self.telegram = telegram

    def run(self, now: dt.datetime | None = None) -> DispatchSummary:
        current_time = _aware(now or dt.datetime.now(KST))
        run_id = uuid.uuid4().hex
        if not self.store.acquire_lock(run_id, current_time):
            return DispatchSummary("SKIPPED_LOCKED", self.settings.automation_mode)
        try:
            return self._run_locked(current_time)
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
        if self.telegram:
            self.telegram.send_batch((OutgoingTelegramMessage(
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

    def _run_locked(self, now: dt.datetime) -> DispatchSummary:
        mode = self.settings.automation_mode
        state_key = f"{mode}|{self.policy.version}"
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
            return self._kma_error(now, day, f"관제 구성 실패 ({type(exc).__name__})")
        if snapshot.warning_feed.health is not DataHealth.LIVE:
            return self._kma_error(
                now,
                day,
                snapshot.warning_feed.message or "KMA 자료 미수신",
            )
        if previous_status.get("kma_health") == "ERROR":
            self._notify_admin("kma-recovered", now, "✅ KMA 자동 관제 조회가 정상화됐습니다.")

        current_impacts = impacts_from_snapshot(snapshot, self.policy)
        initialized, previous_mode, previous_impacts = self.store.load_state()
        new_transitions = (
            detect_transitions(previous_impacts, current_impacts, now)
            if initialized and previous_mode == state_key
            else ()
        )
        valid_facility_ids = [item.id for item in snapshot.facilities]
        try:
            directory = self.contacts.fetch(valid_facility_ids)
            if previous_status.get("contacts_health") == "ERROR":
                self._notify_admin(
                    "contacts-recovered",
                    now,
                    "✅ 자동 알림 연락처 조회가 정상화됐습니다.",
                )
        except ContactDataError as exc:
            if initialized and previous_mode == state_key and new_transitions:
                self.store.save_pending(
                    new_transitions,
                    now + dt.timedelta(seconds=self.settings.pending_seconds),
                )
                self.store.save_state(current_impacts, state_key, now)
                batch = _batch(new_transitions, now, mode, self.policy.version)
                self.store.save_batch(batch, "BLOCKED_CONTACTS")
            counters = {
                _poll_counter(mode): 1,
                "kma_success": 1,
                (
                    "preview_contact_errors"
                    if mode == "preview"
                    else "contact_errors"
                ): 1,
            }
            if mode == "preview":
                counters["preview_transition_count"] = len(new_transitions)
            else:
                counters.update(_transition_counters(new_transitions))
            self.store.record_run(day, counters)
            self.store.update_status({
                "mode": mode,
                "policy_version": self.policy.version,
                "last_run_at": now,
                "last_result": "CONTACTS_ERROR",
                "kma_health": "LIVE",
                "contacts_health": "ERROR",
                "contacts_detail": str(exc),
                "active_impact_count": len(current_impacts),
            })
            self._notify_admin(
                "contacts-error",
                now,
                "⚠️ 자동 문자 발송 중단: Google Sheet 연락처를 확인해 주세요.",
            )
            return DispatchSummary(
                "CONTACTS_ERROR",
                mode,
                transition_count=len(new_transitions),
                detail="연락처 검증 실패로 발송하지 않았습니다.",
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
                "kma_health": "LIVE",
                "contacts_health": "LIVE",
                "contact_revision": directory.revision,
                "contact_count": len(directory.recipients),
                "unique_contact_count": directory.unique_phone_count,
                "active_impact_count": len(current_impacts),
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
                "kma_health": "LIVE",
                "contacts_health": "LIVE",
                "contact_revision": directory.revision,
                "active_impact_count": len(current_impacts),
            })
            return DispatchSummary("NO_CHANGE", mode)

        batch = _batch(transitions, now, mode, self.policy.version)
        try:
            messages = build_sms_messages(
                batch,
                directory,
                self.settings.recipient_hmac_secret,
                self.settings.dashboard_base_url,
            )
        except ValueError as exc:
            if mode == "live":
                self.store.save_pending(
                    transitions,
                    now + dt.timedelta(seconds=self.settings.pending_seconds),
                )
            self.store.save_state(current_impacts, state_key, now)
            self.store.save_batch(batch, "BLOCKED_CONFIGURATION")
            counters = {
                _poll_counter(mode): 1,
                "kma_success": 1,
                (
                    "preview_configuration_errors"
                    if mode == "preview"
                    else "configuration_errors"
                ): 1,
            }
            if mode == "preview":
                counters["preview_transition_count"] = len(transitions)
            else:
                counters.update(_transition_counters(new_transitions))
            self.store.record_run(day, counters)
            self.store.update_status({
                "mode": mode,
                "policy_version": self.policy.version,
                "last_run_at": now,
                "last_result": "CONFIGURATION_ERROR",
                "configuration_detail": str(exc),
            })
            self._notify_admin(
                "configuration-error",
                now,
                "⚠️ 자동 문자 발송 설정이 완전하지 않아 발송을 중단했습니다.",
            )
            return DispatchSummary("CONFIGURATION_ERROR", mode, len(transitions))

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
                "kma_health": "LIVE",
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
                "active_impact_count": len(current_impacts),
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
        if sms_today < self.settings.cap_warning <= sms_today + len(messages):
            self._notify_admin(
                f"daily-cap-warning-{day.isoformat()}",
                now,
                f"⚠️ 오늘 자동 문자 발송이 {self.settings.cap_warning}건에 도달합니다.",
            )

        recipient_hashes: list[str] = []
        accepted = 0
        blocked = 0
        attempted = 0
        sendable: list[OutgoingSmsMessage] = []
        for message in messages:
            reservation = self.store.reserve_delivery(message, now)
            if reservation not in {SmsDeliveryStatus.RESERVED.value}:
                continue
            if sms_today + attempted >= self.settings.daily_cap:
                result = SmsDeliveryResult(
                    SmsDeliveryStatus.BLOCKED_CAP,
                    detail="일일 발송 상한 초과",
                )
                self.store.record_delivery_result(message, result, now)
                counters["cap_blocked"] += 1
                blocked += 1
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
            else:
                counters["sms_unknown"] += 1

        self.store.save_state(current_impacts, state_key, now)
        self.store.resolve_pending(
            [item.id for item in transitions],
            "DISPATCHED",
        )
        self.store.save_batch(batch, "DISPATCHED")
        self.store.record_run(day, counters, recipient_hashes)
        self.store.update_status({
            "mode": mode,
            "policy_version": self.policy.version,
            "last_run_at": now,
            "last_result": "DISPATCHED",
            "kma_health": "LIVE",
            "contacts_health": "LIVE",
            "contact_revision": directory.revision,
            "transition_count": len(transitions),
            "message_count": len(messages),
            "accepted_count": accepted,
            "blocked_count": blocked,
            "unmapped_facility_count": len(unmapped),
            "active_impact_count": len(current_impacts),
        })
        self._send_batch_summary(batch, len(messages), accepted, blocked, len(unmapped))
        if blocked:
            self._notify_admin(
                f"daily-cap-blocked-{day.isoformat()}",
                now,
                f"🚫 일일 {self.settings.daily_cap}건 상한으로 자동 문자 {blocked}건을 차단했습니다.",
            )
        return DispatchSummary(
            "DISPATCHED",
            mode,
            transition_count=len(transitions),
            message_count=len(messages),
            accepted_count=accepted,
            blocked_count=blocked,
        )

    def _kma_error(
        self,
        now: dt.datetime,
        day: dt.date,
        detail: str,
    ) -> DispatchSummary:
        mode = self.settings.automation_mode
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
            "kma_detail": detail,
        })
        self._notify_admin(
            "kma-error",
            now,
            "⚠️ KMA 자동 관제 조회 실패: 이전 특보 상태를 보존하고 문자 발송을 중단했습니다.",
        )
        return DispatchSummary(
            "KMA_ERROR",
            mode,
            detail="KMA 자료 미수신으로 상태를 변경하지 않았습니다.",
        )

    def _notify_admin(self, key: str, now: dt.datetime, text: str) -> None:
        if not self.telegram:
            return
        if not self.store.admin_notice_due(key, now, dt.timedelta(hours=1)):
            return
        self.telegram.send_batch((OutgoingTelegramMessage(text=html.escape(text)),))

    def _send_batch_summary(
        self,
        batch: AlertBatch,
        messages: int,
        accepted: int,
        blocked: int,
        unmapped: int,
    ) -> None:
        if not self.telegram:
            return
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
            f"발효 {warning_counts[AlertTransitionKind.ACTIVATED]} · "
            f"격상 {warning_counts[AlertTransitionKind.ESCALATED]} · "
            f"해제 {warning_counts[AlertTransitionKind.CLEARED]}\n"
            f"영향시설 {affected_facilities}곳 · "
            f"문자 대상 {messages}명 · 정상 접수 {accepted} · "
            f"상한 차단 {blocked} · 연락처 미매핑 시설 {unmapped}\n"
            f"정책 {html.escape(batch.policy_version)}"
        )
        self.telegram.send_batch((OutgoingTelegramMessage(text=text),))


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
