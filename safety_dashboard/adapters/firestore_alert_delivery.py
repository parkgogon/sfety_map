"""Firestore SMS 발송과 SOLAPI 최종 결과 저장 책임."""

from __future__ import annotations

import datetime as dt
from typing import Any

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from safety_dashboard.adapters.firestore_alert_common import KST, _provider_status
from safety_dashboard.alerts.domain import (
    OutgoingSmsMessage,
    SmsDeliveryResult,
    SmsDeliveryStatus,
    TelegramAudience,
    TelegramOutboxItem,
    TelegramPurpose,
)


class FirestoreAlertDeliveryRepository:
    """SMS 예약·접수·최종 수신 결과와 대체 전파 상태 저장 기능."""

    def reserve_delivery(
        self,
        message: OutgoingSmsMessage,
        now: dt.datetime,
        metric_scope: str = "operational",
    ) -> str:
        ref = self.client.collection(self.collections.deliveries).document(message.id)
        try:
            ref.create(
                {
                    "batch_id": message.batch_id,
                    "recipient_hash": message.recipient_hash,
                    "facility_ids": list(message.facility_ids),
                    "transition_ids": list(message.transition_ids),
                    "status": SmsDeliveryStatus.RESERVED.value,
                    "reserved_at": now,
                    "attempted_day": now.astimezone(KST).date().isoformat(),
                    "metric_scope": metric_scope,
                    "provider": "SOLAPI",
                }
            )
            return SmsDeliveryStatus.RESERVED.value
        except AlreadyExists:
            snapshot = ref.get()
            values = snapshot.to_dict() if snapshot.exists else {}
            return "EXISTING_" + str(
                values.get("status", SmsDeliveryStatus.UNKNOWN.value)
            )

    def record_delivery_result(
        self,
        message: OutgoingSmsMessage,
        result: SmsDeliveryResult,
        now: dt.datetime,
    ) -> None:
        ref = self.client.collection(self.collections.deliveries).document(message.id)
        transaction = self.client.transaction()

        @firestore.transactional
        def update(txn: Any) -> None:
            snapshot = ref.get(transaction=txn)
            values = snapshot.to_dict() if snapshot.exists else {}
            terminal = str(values.get("status", "")) in {
                SmsDeliveryStatus.DELIVERED.value,
                SmsDeliveryStatus.FAILED.value,
            }
            update_values = {
                "provider_message_id": result.provider_message_id,
                "provider_group_id": result.provider_group_id,
                "provider_detail": result.detail,
                "attempted_at": now,
            }
            if not terminal:
                update_values["status"] = result.status.value
            txn.set(ref, update_values, merge=True)

        update(transaction)
        if result.provider_message_id:
            self.client.collection(self.collections.provider_messages).document(
                result.provider_message_id
            ).set({"delivery_id": message.id})

    def sms_count(self, day: dt.date) -> int:
        snapshot = self.client.collection(self.collections.metrics).document(
            day.isoformat()
        ).get()
        values = snapshot.to_dict() if snapshot.exists else {}
        return int(values.get("sms_attempted", 0))

    def monthly_sms_count(self, month: dt.date) -> int:
        current = month.replace(day=1)
        if current.month == 12:
            end = dt.date(current.year + 1, 1, 1)
        else:
            end = dt.date(current.year, current.month + 1, 1)
        total = 0
        while current < end:
            total += self.sms_count(current)
            current += dt.timedelta(days=1)
        return total

    def delivery_summary(self, batch_id: str) -> dict[str, int]:
        counts: dict[str, int] = {status.value.lower(): 0 for status in SmsDeliveryStatus}
        counts["total"] = 0
        counts["provider_total"] = 0
        query = self.client.collection(self.collections.deliveries).where(
            filter=FieldFilter("batch_id", "==", batch_id)
        )
        for snapshot in query.stream():
            values = snapshot.to_dict() or {}
            if values.get("metric_scope", "operational") != "operational":
                continue
            counts["total"] += 1
            status = str(values.get("status", "")).lower()
            if status in counts:
                counts[status] += 1
            if values.get("provider_message_id"):
                counts["provider_total"] += 1
        return counts

    def apply_provider_report(
        self,
        provider_message_id: str,
        status_code: str,
        processed_at: dt.datetime,
        delivery_id_hint: str = "",
    ) -> bool:
        mapping_ref = self.client.collection(self.collections.provider_messages).document(
            provider_message_id
        )
        mapping = mapping_ref.get()
        delivery_id = (
            str((mapping.to_dict() or {}).get("delivery_id", ""))
            if mapping.exists
            else delivery_id_hint
        )
        if not delivery_id:
            return False
        delivery_ref = self.client.collection(self.collections.deliveries).document(
            delivery_id
        )
        target = _provider_status(status_code)
        transaction = self.client.transaction()

        @firestore.transactional
        def update(txn: Any) -> tuple[bool, str, str, str]:
            snapshot = delivery_ref.get(transaction=txn)
            if not snapshot.exists:
                return False, "", "operational", ""
            values = snapshot.to_dict() or {}
            previous = str(values.get("status", ""))
            metric_scope = str(values.get("metric_scope", "operational"))
            if previous == target.value or previous in {
                SmsDeliveryStatus.DELIVERED.value,
                SmsDeliveryStatus.FAILED.value,
            }:
                return (
                    False,
                    str(values.get("attempted_day", "")),
                    metric_scope,
                    str(values.get("batch_id", "")),
                )
            txn.set(
                delivery_ref,
                {
                    "status": target.value,
                    "provider_status_code": status_code,
                    "provider_reported_at": processed_at,
                },
                merge=True,
            )
            return (
                True,
                str(values.get("attempted_day", "")),
                metric_scope,
                str(values.get("batch_id", "")),
            )

        changed, day, scope, batch_id = update(transaction)
        if changed and day and target in {
            SmsDeliveryStatus.DELIVERED,
            SmsDeliveryStatus.FAILED,
        }:
            prefix = "test_sms" if scope == "test" else "sms"
            field = (
                f"{prefix}_delivered"
                if target is SmsDeliveryStatus.DELIVERED
                else f"{prefix}_delivery_failed"
            )
            self.client.collection(self.collections.metrics).document(day).set(
                {field: firestore.Increment(1), "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        if changed and scope == "operational" and batch_id:
            now = processed_at
            if target is SmsDeliveryStatus.FAILED:
                self.enqueue_telegram(TelegramOutboxItem(
                    id=f"user-fallback-{batch_id}",
                    audience=TelegramAudience.USER,
                    purpose=TelegramPurpose.SMS_FALLBACK,
                    created_at=now,
                    expires_at=now + dt.timedelta(minutes=30),
                    next_attempt_at=now,
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
                    created_at=now,
                    expires_at=now + dt.timedelta(minutes=30),
                    next_attempt_at=now,
                    batch_id=batch_id,
                ))
        return bool(changed)
