"""단위 테스트와 로컬 미리보기에 사용하는 메모리 저장소."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Mapping, Sequence

from safety_dashboard.alerts.domain import (
    AlertBatch,
    AlertTransition,
    FacilityImpact,
    OutgoingSmsMessage,
    SmsDeliveryResult,
    SmsDeliveryStatus,
)


class InMemoryAlertStore:
    def __init__(self) -> None:
        self.lock_holder = ""
        self.lock_expires: dt.datetime | None = None
        self.initialized = False
        self.mode = ""
        self.impacts: tuple[FacilityImpact, ...] = ()
        self.batches: dict[str, tuple[AlertBatch, str]] = {}
        self.pending: dict[str, tuple[AlertTransition, dt.datetime, str]] = {}
        self.deliveries: dict[str, dict[str, object]] = {}
        self.metrics: dict[str, dict[str, object]] = defaultdict(dict)
        self.status: dict[str, object] = {}
        self.notices: dict[str, dt.datetime] = {}

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
