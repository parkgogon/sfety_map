"""자동 알림 외부 의존성 포트."""

from __future__ import annotations

import datetime as dt
from typing import Mapping, Protocol, Sequence

from safety_dashboard.alerts.domain import (
    AlertBatch,
    AlertTransition,
    ContactDirectory,
    FacilityImpact,
    OutgoingSmsMessage,
    SmsDeliveryResult,
    SolapiBalance,
    TelegramOutboxItem,
)
from safety_dashboard.domain.models import DashboardSnapshot


class MonitoringSnapshotProvider(Protocol):
    def fetch(self) -> DashboardSnapshot: ...


class ContactProvider(Protocol):
    def fetch(self, valid_facility_ids: Sequence[str]) -> ContactDirectory: ...


class SmsNotifier(Protocol):
    def send(self, message: OutgoingSmsMessage) -> SmsDeliveryResult: ...


class SolapiBalanceProvider(Protocol):
    def fetch_balance(self) -> SolapiBalance: ...


class AlertStateStore(Protocol):
    def acquire_lock(self, run_id: str, now: dt.datetime) -> bool: ...

    def release_lock(self, run_id: str, now: dt.datetime) -> None: ...

    def load_state(self) -> tuple[bool, str, tuple[FacilityImpact, ...]]: ...

    def save_state(
        self,
        impacts: Sequence[FacilityImpact],
        mode: str,
        now: dt.datetime,
    ) -> None: ...

    def save_batch(self, batch: AlertBatch, status: str) -> None: ...

    def update_batch_delivery(
        self, batch_id: str, values: Mapping[str, object]
    ) -> None: ...

    def save_pending(
        self,
        transitions: Sequence[AlertTransition],
        expires_at: dt.datetime,
    ) -> None: ...

    def load_pending(self, now: dt.datetime) -> tuple[AlertTransition, ...]: ...

    def resolve_pending(self, transition_ids: Sequence[str], status: str) -> None: ...

    def reserve_delivery(
        self,
        message: OutgoingSmsMessage,
        now: dt.datetime,
        metric_scope: str = "operational",
    ) -> str: ...

    def record_delivery_result(
        self,
        message: OutgoingSmsMessage,
        result: SmsDeliveryResult,
        now: dt.datetime,
    ) -> None: ...

    def sms_count(self, day: dt.date) -> int: ...

    def monthly_sms_count(self, month: dt.date) -> int: ...

    def record_run(
        self,
        day: dt.date,
        counters: Mapping[str, int],
        recipient_hashes: Sequence[str] = (),
    ) -> None: ...

    def update_status(self, values: Mapping[str, object]) -> None: ...

    def notification_status(self) -> Mapping[str, object]: ...

    def admin_notice_due(
        self,
        key: str,
        now: dt.datetime,
        interval: dt.timedelta,
    ) -> bool: ...

    def enqueue_telegram(self, item: TelegramOutboxItem) -> bool: ...

    def due_telegram(
        self, now: dt.datetime, limit: int = 20
    ) -> tuple[TelegramOutboxItem, ...]: ...

    def record_telegram_result(
        self,
        item: TelegramOutboxItem,
        success: bool,
        detail: str,
        now: dt.datetime,
    ) -> None: ...

    def load_batch(self, batch_id: str) -> AlertBatch | None: ...

    def delivery_summary(self, batch_id: str) -> Mapping[str, int]: ...

    def notification_metrics(
        self, start: dt.date, end: dt.date
    ) -> Mapping[str, object]: ...
