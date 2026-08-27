"""Firestore Telegram outbox와 재시도 결과 저장 책임."""

from __future__ import annotations

import datetime as dt
from typing import Any

from google.api_core.exceptions import AlreadyExists

from safety_dashboard.adapters.firestore_alert_common import (
    KST,
    _aware,
    _parse_datetime,
    _telegram_job_from_dict,
    _telegram_message_to_dict,
    _telegram_metric,
)
from safety_dashboard.alerts.domain import (
    ManualDispatchStatus,
    TelegramAudience,
    TelegramOutboxItem,
    TelegramPurpose,
)


class FirestoreTelegramOutboxRepository:
    """Telegram 작업 등록·재시도·완료 상태 저장 기능."""

    def enqueue_telegram(self, item: TelegramOutboxItem) -> bool:
        ref = self.client.collection(self.collections.telegram_outbox).document(item.id)
        try:
            ref.create({
                "audience": item.audience.value,
                "purpose": item.purpose.value,
                "created_at": item.created_at,
                "expires_at": item.expires_at,
                "next_attempt_at": item.next_attempt_at,
                "batch_id": item.batch_id,
                "reason": item.reason,
                "messages": [_telegram_message_to_dict(value) for value in item.messages],
                "metric_scope": item.metric_scope,
                "attempt_count": item.attempt_count,
                "status": "PENDING",
            })
            return True
        except AlreadyExists:
            return False

    def due_telegram(
        self, now: dt.datetime, limit: int = 20
    ) -> tuple[TelegramOutboxItem, ...]:
        due: list[TelegramOutboxItem] = []
        expired: list[tuple[Any, str, str, str, str]] = []
        for snapshot in self.client.collection(self.collections.telegram_outbox).stream():
            values = snapshot.to_dict() or {}
            if values.get("status") != "PENDING":
                continue
            expires_at = _parse_datetime(values.get("expires_at"))
            next_attempt_at = _parse_datetime(values.get("next_attempt_at"))
            if expires_at and _aware(expires_at) < _aware(now):
                expired.append((
                    snapshot.reference,
                    str(values.get("audience", TelegramAudience.USER.value)),
                    str(values.get("purpose", "")),
                    str(values.get("batch_id", "")),
                    str(values.get("metric_scope", "operational")),
                ))
                continue
            if next_attempt_at and _aware(next_attempt_at) > _aware(now):
                continue
            due.append(_telegram_job_from_dict(snapshot.id, values))
            if len(due) >= limit:
                break
        if expired:
            batch = self.client.batch()
            for ref, _, _, _, _ in expired:
                batch.set(
                    ref,
                    {"status": "EXPIRED", "completed_at": now},
                    merge=True,
                )
            batch.commit()
            counters: dict[str, int] = {}
            for _, audience, purpose, dispatch_id, scope in expired:
                if purpose == TelegramPurpose.MANUAL.value and dispatch_id:
                    self.update_manual_dispatch(dispatch_id, {
                        "status": ManualDispatchStatus.FAILED.value,
                        "completed_at": now,
                        "last_detail": "Telegram 재시도 시간이 만료됐습니다.",
                    })
                    manual_counter = (
                        "manual_drill_failed"
                        if scope == "drill"
                        else "telegram_manual_failed"
                    )
                    counters[manual_counter] = counters.get(manual_counter, 0) + 1
                    continue
                if audience == TelegramAudience.USER.value and dispatch_id:
                    self.update_batch_delivery(dispatch_id, {
                        "telegram_status": "FAILED",
                        "telegram_detail": "Telegram 재시도 시간이 만료됐습니다.",
                        "telegram_completed_at": now,
                    })
                counter = (
                    "telegram_admin_failed"
                    if audience == TelegramAudience.ADMIN.value
                    else "telegram_user_failed"
                )
                counters[counter] = counters.get(counter, 0) + 1
            if counters:
                self.record_run(now.astimezone(KST).date(), counters)
        return tuple(due)

    def record_telegram_result(
        self,
        item: TelegramOutboxItem,
        success: bool,
        detail: str,
        now: dt.datetime,
    ) -> None:
        attempts = item.attempt_count + 1
        expired = _aware(now) + dt.timedelta(minutes=5) > _aware(item.expires_at)
        status = "SENT" if success else ("EXPIRED" if expired else "PENDING")
        values: dict[str, object] = {
            "status": status,
            "attempt_count": attempts,
            "last_detail": detail,
            "last_attempt_at": now,
        }
        if success or expired:
            values["completed_at"] = now
        else:
            values["next_attempt_at"] = now + dt.timedelta(minutes=5)
        self.client.collection(self.collections.telegram_outbox).document(item.id).set(
            values, merge=True
        )
        if item.purpose is TelegramPurpose.MANUAL and item.batch_id:
            terminal = success or expired
            self.update_manual_dispatch(item.batch_id, {
                "status": (
                    ManualDispatchStatus.SENT.value
                    if success
                    else (
                        ManualDispatchStatus.FAILED.value
                        if expired
                        else ManualDispatchStatus.RETRY_QUEUED.value
                    )
                ),
                "last_detail": detail,
                "last_attempt_at": now,
                **({"completed_at": now} if terminal else {}),
            })
            if terminal:
                prefix = (
                    "manual_drill"
                    if item.metric_scope == "drill"
                    else "telegram_manual"
                )
                suffix = "sent" if success else "failed"
                self.record_run(
                    now.astimezone(KST).date(), {f"{prefix}_{suffix}": 1}
                )
            return
        if item.audience is TelegramAudience.USER and item.batch_id:
            self.update_batch_delivery(item.batch_id, {
                "telegram_status": (
                    "SENT" if success else ("FAILED" if expired else "RETRY_QUEUED")
                ),
                "telegram_detail": detail,
                "telegram_attempt_count": attempts,
                **({"telegram_completed_at": now} if success or expired else {}),
            })
        if item.metric_scope != "operational":
            return
        counter = _telegram_metric(item, success, expired)
        if counter:
            self.record_run(now.astimezone(KST).date(), {counter: 1})
