"""단위 테스트와 로컬 미리보기에 사용하는 메모리 저장소."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Mapping, Sequence

from safety_dashboard.alerts.domain import (
    AlertBatch,
    AlertTransition,
    FacilityImpact,
    ManualDispatchStatus,
    ManualTelegramCategory,
    ManualTelegramDispatch,
    NotificationEvent,
    OutgoingSmsMessage,
    SmsDeliveryResult,
    SmsDeliveryStatus,
    TelegramAudience,
    TelegramOutboxItem,
    TelegramPurpose,
)


class InMemoryAlertStore:
    def __init__(self) -> None:
        self.lock_holder = ""
        self.lock_expires: dt.datetime | None = None
        self.initialized = False
        self.mode = ""
        self.impacts: tuple[FacilityImpact, ...] = ()
        self.batches: dict[str, tuple[AlertBatch, str]] = {}
        self.batch_delivery: dict[str, dict[str, object]] = {}
        self.pending: dict[str, tuple[AlertTransition, dt.datetime, str]] = {}
        self.deliveries: dict[str, dict[str, object]] = {}
        self.metrics: dict[str, dict[str, object]] = defaultdict(dict)
        self.status: dict[str, object] = {}
        self.notices: dict[str, dt.datetime] = {}
        self.telegram_jobs: dict[str, dict[str, object]] = {}
        self.manual_dispatches: dict[str, dict[str, object]] = {}

    def acquire_lock(self, run_id: str, now: dt.datetime) -> bool:
        if self.lock_expires and self.lock_expires > now:
            return False
        self.lock_holder = run_id
        self.lock_expires = now + dt.timedelta(minutes=4)
        return True

    def release_lock(self, run_id: str, now: dt.datetime) -> None:
        if self.lock_holder == run_id:
            self.lock_holder = ""
            self.lock_expires = now

    def load_state(self) -> tuple[bool, str, tuple[FacilityImpact, ...]]:
        return self.initialized, self.mode, self.impacts

    def save_state(
        self, impacts: Sequence[FacilityImpact], mode: str, now: dt.datetime
    ) -> None:
        self.initialized = True
        self.mode = mode
        self.impacts = tuple(impacts)

    def save_batch(self, batch: AlertBatch, status: str) -> None:
        self.batches[batch.id] = (batch, status)

    def update_batch_delivery(
        self, batch_id: str, values: Mapping[str, object]
    ) -> None:
        self.batch_delivery.setdefault(batch_id, {}).update(values)
        if batch_id in self.batches and "status" in values:
            batch, _ = self.batches[batch_id]
            self.batches[batch_id] = (batch, str(values["status"]))

    def save_pending(
        self, transitions: Sequence[AlertTransition], expires_at: dt.datetime
    ) -> None:
        for item in transitions:
            self.pending[item.id] = (item, expires_at, "PENDING")

    def load_pending(self, now: dt.datetime) -> tuple[AlertTransition, ...]:
        result = []
        for key, (item, expires, status) in tuple(self.pending.items()):
            if status != "PENDING":
                continue
            if expires < now:
                self.pending[key] = (item, expires, "EXPIRED")
            else:
                result.append(item)
        return tuple(result)

    def resolve_pending(self, transition_ids: Sequence[str], status: str) -> None:
        for key in transition_ids:
            if key in self.pending:
                item, expires, _ = self.pending[key]
                self.pending[key] = (item, expires, status)

    def reserve_delivery(
        self,
        message: OutgoingSmsMessage,
        now: dt.datetime,
        metric_scope: str = "operational",
    ) -> str:
        if message.id in self.deliveries:
            return "EXISTING_" + str(self.deliveries[message.id]["status"])
        self.deliveries[message.id] = {
            "message": message,
            "status": SmsDeliveryStatus.RESERVED.value,
            "attempted_day": now.date().isoformat(),
            "metric_scope": metric_scope,
        }
        return SmsDeliveryStatus.RESERVED.value

    def record_delivery_result(
        self,
        message: OutgoingSmsMessage,
        result: SmsDeliveryResult,
        now: dt.datetime,
    ) -> None:
        self.deliveries[message.id].update(
            {
                "status": result.status.value,
                "result": result,
                "attempted_at": now,
            }
        )

    def sms_count(self, day: dt.date) -> int:
        return int(self.metrics.get(day.isoformat(), {}).get("sms_attempted", 0))

    def monthly_sms_count(self, month: dt.date) -> int:
        prefix = f"{month.year:04d}-{month.month:02d}-"
        return sum(
            int(values.get("sms_attempted", 0))
            for day, values in self.metrics.items()
            if day.startswith(prefix)
        )

    def record_run(
        self,
        day: dt.date,
        counters: Mapping[str, int],
        recipient_hashes: Sequence[str] = (),
    ) -> None:
        values = self.metrics[day.isoformat()]
        for key, value in counters.items():
            values[key] = int(values.get(key, 0)) + int(value)
        recipients = set(values.get("recipient_hashes", []))
        recipients.update(recipient_hashes)
        values["recipient_hashes"] = sorted(recipients)

    def update_status(self, values: Mapping[str, object]) -> None:
        self.status.update(values)

    def notification_status(self) -> Mapping[str, object]:
        return dict(self.status)

    def admin_notice_due(
        self, key: str, now: dt.datetime, interval: dt.timedelta
    ) -> bool:
        previous = self.notices.get(key)
        if previous and previous + interval > now:
            return False
        self.notices[key] = now
        return True

    def enqueue_telegram(self, item: TelegramOutboxItem) -> bool:
        if item.id in self.telegram_jobs:
            return False
        self.telegram_jobs[item.id] = {"item": item, "status": "PENDING"}
        return True

    def due_telegram(
        self, now: dt.datetime, limit: int = 20
    ) -> tuple[TelegramOutboxItem, ...]:
        result = []
        for values in self.telegram_jobs.values():
            item = values["item"]
            if values["status"] != "PENDING":
                continue
            if item.expires_at < now:
                values["status"] = "EXPIRED"
                if item.purpose is TelegramPurpose.MANUAL and item.batch_id:
                    self.update_manual_dispatch(item.batch_id, {
                        "status": ManualDispatchStatus.FAILED.value,
                        "completed_at": now,
                        "last_detail": "Telegram 재시도 시간이 만료됐습니다.",
                    })
                    counter = (
                        "manual_drill_failed"
                        if item.metric_scope == "drill"
                        else "telegram_manual_failed"
                    )
                    self.record_run(now.date(), {counter: 1})
                elif item.audience is TelegramAudience.USER and item.batch_id:
                    self.update_batch_delivery(item.batch_id, {
                        "telegram_status": "FAILED",
                        "telegram_detail": "Telegram 재시도 시간이 만료됐습니다.",
                        "telegram_completed_at": now,
                    })
                if item.metric_scope == "operational":
                    counter = (
                        "telegram_admin_failed"
                        if item.audience.value == "admin"
                        else "telegram_user_failed"
                    )
                    self.record_run(now.date(), {counter: 1})
                continue
            if item.next_attempt_at <= now:
                result.append(item)
            if len(result) >= limit:
                break
        return tuple(result)

    def record_telegram_result(
        self,
        item: TelegramOutboxItem,
        success: bool,
        detail: str,
        now: dt.datetime,
    ) -> None:
        values = self.telegram_jobs[item.id]
        attempts = item.attempt_count + 1
        if success:
            values.update({"status": "SENT", "detail": detail})
        elif now + dt.timedelta(minutes=5) > item.expires_at:
            values.update({"status": "EXPIRED", "detail": detail})
        else:
            replacement = TelegramOutboxItem(
                **{
                    **item.__dict__,
                    "next_attempt_at": now + dt.timedelta(minutes=5),
                    "attempt_count": attempts,
                }
            )
            values.update({"item": replacement, "detail": detail})
        if item.purpose is TelegramPurpose.MANUAL and item.batch_id:
            terminal = success or values["status"] == "EXPIRED"
            self.update_manual_dispatch(item.batch_id, {
                "status": (
                    ManualDispatchStatus.SENT.value
                    if success
                    else (
                        ManualDispatchStatus.FAILED.value
                        if terminal
                        else ManualDispatchStatus.RETRY_QUEUED.value
                    )
                ),
                "last_detail": detail,
                "last_attempt_at": now,
                **({"completed_at": now} if terminal else {}),
            })
            if success:
                counter = (
                    "manual_drill_sent"
                    if item.metric_scope == "drill"
                    else "telegram_manual_sent"
                )
                self.record_run(now.date(), {counter: 1})
            elif terminal:
                counter = (
                    "manual_drill_failed"
                    if item.metric_scope == "drill"
                    else "telegram_manual_failed"
                )
                self.record_run(now.date(), {counter: 1})
            return
        if item.audience is TelegramAudience.USER and item.batch_id:
            self.update_batch_delivery(item.batch_id, {
                "telegram_status": (
                    "SENT"
                    if success
                    else ("FAILED" if values["status"] == "EXPIRED" else "RETRY_QUEUED")
                ),
                "telegram_detail": detail,
                "telegram_attempt_count": attempts,
                **({"telegram_completed_at": now} if success or values["status"] == "EXPIRED" else {}),
            })
        if item.metric_scope != "operational":
            return
        counter = ""
        if success:
            if item.audience.value == "admin":
                counter = "telegram_admin_sent"
            elif item.purpose.value == "sms_fallback":
                counter = "telegram_user_fallback_sent"
            else:
                counter = "telegram_user_primary_sent"
        elif values["status"] == "EXPIRED":
            counter = (
                "telegram_admin_failed"
                if item.audience.value == "admin"
                else "telegram_user_failed"
            )
        if counter:
            self.record_run(now.date(), {counter: 1})

    def load_batch(self, batch_id: str) -> AlertBatch | None:
        value = self.batches.get(batch_id)
        return value[0] if value else None

    def delivery_summary(self, batch_id: str) -> dict[str, int]:
        counts = {status.value.lower(): 0 for status in SmsDeliveryStatus}
        counts.update({"total": 0, "provider_total": 0})
        for values in self.deliveries.values():
            message = values.get("message")
            if not message or message.batch_id != batch_id:
                continue
            counts["total"] += 1
            status = str(values.get("status", "")).lower()
            if status in counts:
                counts[status] += 1
            result = values.get("result")
            if result and result.provider_message_id:
                counts["provider_total"] += 1
        return counts

    def apply_provider_report(
        self,
        provider_message_id: str,
        status_code: str,
        processed_at: dt.datetime,
        delivery_id_hint: str = "",
    ) -> bool:
        target = (
            SmsDeliveryStatus.DELIVERED
            if status_code == "4000"
            else SmsDeliveryStatus.FAILED
        )
        selected_id = delivery_id_hint
        for delivery_id, values in self.deliveries.items():
            result = values.get("result")
            if result and result.provider_message_id == provider_message_id:
                selected_id = delivery_id
                break
        values = self.deliveries.get(selected_id)
        if not values or values.get("status") in {
            SmsDeliveryStatus.DELIVERED.value,
            SmsDeliveryStatus.FAILED.value,
        }:
            return False
        values["status"] = target.value
        day = str(values.get("attempted_day", ""))
        scope = str(values.get("metric_scope", "operational"))
        message = values.get("message")
        batch_id = message.batch_id if message else ""
        if day:
            prefix = "test_sms" if scope == "test" else "sms"
            field = (
                f"{prefix}_delivered"
                if target is SmsDeliveryStatus.DELIVERED
                else f"{prefix}_delivery_failed"
            )
            self.record_run(dt.date.fromisoformat(day), {field: 1})
        if scope == "operational" and batch_id:
            if target is SmsDeliveryStatus.FAILED:
                self.enqueue_telegram(TelegramOutboxItem(
                    id=f"user-fallback-{batch_id}",
                    audience=TelegramAudience.USER,
                    purpose=TelegramPurpose.SMS_FALLBACK,
                    created_at=processed_at,
                    expires_at=processed_at + dt.timedelta(minutes=30),
                    next_attempt_at=processed_at,
                    batch_id=batch_id,
                    reason=f"통신사 최종 수신 실패 ({status_code})",
                ))
            summary = self.delivery_summary(batch_id)
            terminal = summary.get("delivered", 0) + summary.get("failed", 0)
            if summary.get("provider_total", 0) and terminal >= summary["provider_total"]:
                self.enqueue_telegram(TelegramOutboxItem(
                    id=f"admin-sms-final-{batch_id}",
                    audience=TelegramAudience.ADMIN,
                    purpose=TelegramPurpose.SMS_FINAL,
                    created_at=processed_at,
                    expires_at=processed_at + dt.timedelta(minutes=30),
                    next_attempt_at=processed_at,
                    batch_id=batch_id,
                ))
        return True

    def notification_metrics(
        self, start: dt.date, end: dt.date
    ) -> Mapping[str, object]:
        totals: dict[str, int] = {}
        recipients: set[str] = set()
        current = start
        while current <= end:
            values = self.metrics.get(current.isoformat(), {})
            for key, value in values.items():
                if key == "recipient_hashes":
                    continue
                if isinstance(value, int):
                    totals[key] = totals.get(key, 0) + value
            recipients.update(values.get("recipient_hashes", []))
            current += dt.timedelta(days=1)
        totals["unique_recipients"] = len(recipients)
        delivered = totals.get("sms_delivered", 0)
        terminal = delivered + totals.get("sms_delivery_failed", 0)
        return {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "totals": totals,
            "delivery_success_rate": delivered / terminal * 100 if terminal else None,
        }

    def create_manual_dispatch(self, value: ManualTelegramDispatch) -> bool:
        if value.id in self.manual_dispatches:
            return False
        self.manual_dispatches[value.id] = {
            "dispatch": value,
            "created_at": value.created_at,
            "fingerprint": value.fingerprint,
            "status": ManualDispatchStatus.PENDING.value,
        }
        return True

    def manual_dispatch(self, dispatch_id: str) -> Mapping[str, object] | None:
        value = self.manual_dispatches.get(dispatch_id)
        return dict(value) if value else None

    def update_manual_dispatch(
        self, dispatch_id: str, values: Mapping[str, object]
    ) -> None:
        self.manual_dispatches.setdefault(dispatch_id, {}).update(values)

    def recent_duplicate(
        self, fingerprint: str, since: dt.datetime
    ) -> NotificationEvent | None:
        for dispatch_id, values in self.manual_dispatches.items():
            dispatch = values.get("dispatch")
            if not isinstance(dispatch, ManualTelegramDispatch):
                continue
            if dispatch.created_at >= since and dispatch.fingerprint == fingerprint:
                return _manual_event(dispatch_id, values)
        for batch_id, (batch, batch_status) in self.batches.items():
            if batch.mode != "live" or batch.created_at < since:
                continue
            automatic_fingerprint = _automatic_fingerprint(batch)
            if automatic_fingerprint == fingerprint:
                return _automatic_event(
                    batch_id,
                    batch,
                    batch_status,
                    self.batch_delivery.get(batch_id, {}),
                )
        return None

    def notification_events(
        self,
        start: dt.datetime,
        end: dt.datetime,
        *,
        source: str = "all",
        status: str = "all",
        limit: int = 100,
    ) -> tuple[NotificationEvent, ...]:
        events: list[NotificationEvent] = []
        if source in {"all", "automatic"}:
            for batch_id, (batch, batch_status) in self.batches.items():
                if batch.mode == "live" and start <= batch.created_at < end:
                    events.append(_automatic_event(
                        batch_id,
                        batch,
                        batch_status,
                        self.batch_delivery.get(batch_id, {}),
                    ))
        if source in {"all", "manual"}:
            for dispatch_id, values in self.manual_dispatches.items():
                dispatch = values.get("dispatch")
                if (
                    isinstance(dispatch, ManualTelegramDispatch)
                    and start <= dispatch.created_at < end
                ):
                    events.append(_manual_event(dispatch_id, values))
        if status != "all":
            events = [item for item in events if item.status == status]
        events.sort(key=lambda item: item.occurred_at, reverse=True)
        return tuple(events[:limit])


def _automatic_fingerprint(batch: AlertBatch) -> str:
    value = ManualTelegramDispatch(
        id="fingerprint",
        created_at=batch.created_at,
        category=ManualTelegramCategory.REMINDER,
        operator_label="",
        note="",
        mode=batch.mode,
        facility_ids=tuple(item.impact.facility_id for item in batch.transitions),
        warning_keys=tuple(item.impact.warning_key for item in batch.transitions),
        messages=(),
    )
    return value.fingerprint


def _automatic_event(
    batch_id: str,
    batch: AlertBatch,
    status: str,
    delivery: Mapping[str, object] | None = None,
) -> NotificationEvent:
    kinds = {item.kind.label for item in batch.transitions}
    route = str((delivery or {}).get("delivery_route", "telegram"))
    event_status = str((delivery or {}).get("telegram_status", ""))
    if not event_status:
        event_status = (
            "PREVIEW"
            if status == "PREVIEW"
            else ("PENDING" if route == "telegram" else status)
        )
    return NotificationEvent(
        id=batch_id,
        occurred_at=batch.created_at,
        source="automatic",
        event=next(iter(kinds)) if len(kinds) == 1 else "상황변경",
        status=event_status,
        channel="사용자 Telegram" if route != "sms" else "SOLAPI 문자",
        facility_count=len({item.impact.facility_id for item in batch.transitions}),
        warning_count=len({item.impact.warning_key for item in batch.transitions}),
        detail=str((delivery or {}).get("telegram_detail", "")),
    )


def _manual_event(
    dispatch_id: str, values: Mapping[str, object]
) -> NotificationEvent:
    dispatch = values.get("dispatch")
    if not isinstance(dispatch, ManualTelegramDispatch):
        raise ValueError("수동 전파 기록 형식이 올바르지 않습니다.")
    return NotificationEvent(
        id=dispatch_id,
        occurred_at=dispatch.created_at,
        source="manual",
        event=dispatch.category.label,
        status=str(values.get("status", ManualDispatchStatus.PENDING.value)),
        channel="사용자 Telegram",
        facility_count=len(set(dispatch.facility_ids)),
        warning_count=len(set(dispatch.warning_keys)),
        detail=str(values.get("last_detail", "")),
        category=dispatch.category.value,
        operator_label=dispatch.operator_label,
    )
