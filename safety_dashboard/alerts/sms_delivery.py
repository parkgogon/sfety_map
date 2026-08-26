"""SMS 우선 전달 경로의 준비, 비용 상한과 대체 전파를 관리합니다."""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence

from safety_dashboard.alerts.contacts import ContactDataError
from safety_dashboard.alerts.domain import (
    AlertBatch,
    ContactDirectory,
    OutgoingSmsMessage,
    SmsDeliveryResult,
    SmsDeliveryStatus,
    TelegramPurpose,
)
from safety_dashboard.alerts.messages import (
    build_sms_messages,
    unmapped_facility_ids,
)
from safety_dashboard.alerts.ports import (
    AlertStateStore,
    ContactProvider,
    SmsNotifier,
)
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.alerts.telegram_outbox import TelegramOutboxService


ESTIMATED_LMS_COST_KRW = 45


class SmsPathUnavailable(RuntimeError):
    """SMS 준비 단계에서 전달 경로를 사용할 수 없음을 나타냅니다."""

    def __init__(
        self,
        reason: str,
        status: str,
        status_values: Mapping[str, object],
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.status_values = dict(status_values)


@dataclass(frozen=True)
class SmsPreparation:
    directory: ContactDirectory
    messages: tuple[OutgoingSmsMessage, ...]
    unmapped_facility_ids: tuple[str, ...]

    @property
    def estimated_cost_krw(self) -> int:
        return len(self.messages) * ESTIMATED_LMS_COST_KRW

    @property
    def preview_samples(self) -> list[dict[str, object]]:
        return [
            {
                "recipient_code": item.recipient_hash[:12],
                "facility_count": len(item.facility_ids),
                "text": item.text,
            }
            for item in self.messages[:3]
        ]


@dataclass(frozen=True)
class SmsDispatchOutcome:
    message_count: int
    accepted_count: int
    failed_count: int
    unknown_count: int
    blocked_count: int
    fallback_queued: bool
    counters: Mapping[str, int]
    recipient_hashes: tuple[str, ...]


class SmsDeliveryService:
    """SOLAPI 전달 경로의 외부 조회와 비용 보호 규칙을 집중합니다."""

    def __init__(
        self,
        contacts: ContactProvider,
        notifier: SmsNotifier,
        store: AlertStateStore,
        settings: AlertSettings,
        telegram_outbox: TelegramOutboxService,
    ) -> None:
        self.contacts = contacts
        self.notifier = notifier
        self.store = store
        self.settings = settings
        self.telegram_outbox = telegram_outbox

    def prepare(
        self,
        batch: AlertBatch,
        valid_facility_ids: Sequence[str],
        *,
        contacts_was_unhealthy: bool = False,
    ) -> SmsPreparation:
        try:
            directory = self.contacts.fetch(valid_facility_ids)
        except ContactDataError as exc:
            raise SmsPathUnavailable(
                "연락처 Sheet 오류",
                "CONTACTS_ERROR",
                {"contacts_health": "ERROR", "contacts_detail": str(exc)},
            ) from exc

        if contacts_was_unhealthy:
            self.telegram_outbox.notify_admin(
                "contacts-recovered",
                batch.created_at,
                "✅ 자동 문자 연락처 조회가 정상화됐습니다.",
            )

        try:
            messages = build_sms_messages(
                batch,
                directory,
                self.settings.recipient_hmac_secret,
                self.settings.dashboard_base_url,
            )
        except ValueError as exc:
            raise SmsPathUnavailable(
                "문자 발송 설정 오류",
                "CONFIGURATION_ERROR",
                {"configuration_detail": str(exc)},
            ) from exc

        return SmsPreparation(
            directory=directory,
            messages=messages,
            unmapped_facility_ids=unmapped_facility_ids(
                batch.transitions,
                directory,
            ),
        )

    def dispatch(
        self,
        batch: AlertBatch,
        preparation: SmsPreparation,
        now: dt.datetime,
        day: dt.date,
    ) -> SmsDispatchOutcome:
        messages = preparation.messages
        unmapped = preparation.unmapped_facility_ids
        self.store.save_batch(batch, "PROCESSING")

        sms_today = self.store.sms_count(day)
        sms_month = self.store.monthly_sms_count(day)
        self._warn_if_approaching_caps(
            now,
            day,
            sms_today,
            sms_month,
            len(messages),
        )

        counters: Counter[str] = Counter({
            "unmapped_facilities": len(unmapped),
        })
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
            if reservation != SmsDeliveryStatus.RESERVED.value:
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
                self.store.record_delivery_result(
                    message,
                    SmsDeliveryResult(
                        SmsDeliveryStatus.BLOCKED_CAP,
                        detail=reason,
                    ),
                    now,
                )
                counters["cap_blocked"] += 1
                blocked += 1
                fallback_reasons.append(reason)
                continue
            sendable.append(message)
            attempted += 1

        results = send_messages(self.notifier, tuple(sendable))
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
            self.telegram_outbox.enqueue_user_batch(
                batch,
                now,
                TelegramPurpose.SMS_FALLBACK,
                " · ".join(dict.fromkeys(fallback_reasons)),
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
        self.telegram_outbox.enqueue_batch_summary(
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
            self.telegram_outbox.notify_admin(
                f"daily-cap-blocked-{day.isoformat()}",
                now,
                f"🚫 코드 발송 상한으로 자동 문자 {blocked}건을 차단하고 "
                "사용자 Telegram 대체 전파를 예약했습니다.",
            )

        return SmsDispatchOutcome(
            message_count=len(messages),
            accepted_count=accepted,
            failed_count=failed,
            unknown_count=unknown,
            blocked_count=blocked,
            fallback_queued=fallback_queued,
            counters=dict(counters),
            recipient_hashes=tuple(recipient_hashes),
        )

    def _warn_if_approaching_caps(
        self,
        now: dt.datetime,
        day: dt.date,
        sms_today: int,
        sms_month: int,
        message_count: int,
    ) -> None:
        if (
            sms_today < self.settings.cap_warning
            <= sms_today + message_count
        ):
            self.telegram_outbox.notify_admin(
                f"daily-cap-warning-{day.isoformat()}",
                now,
                f"⚠️ 오늘 자동 문자 발송이 "
                f"{self.settings.cap_warning}건에 도달합니다.",
            )
        if (
            sms_month < self.settings.monthly_cap_warning
            <= sms_month + message_count
        ):
            self.telegram_outbox.notify_admin(
                f"monthly-cap-warning-{day:%Y-%m}",
                now,
                f"⚠️ 이번 달 자동 문자 발송이 "
                f"{self.settings.monthly_cap_warning}건에 도달합니다.",
            )


def send_messages(
    notifier: SmsNotifier,
    messages: tuple[OutgoingSmsMessage, ...],
) -> tuple[SmsDeliveryResult, ...]:
    """SOLAPI 일괄 응답이 부족해도 모든 메시지의 결과를 반환합니다."""

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
