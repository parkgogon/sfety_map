"""Firestore 자동알림 운영 상태·실적·감사 이력 저장 책임."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from safety_dashboard.adapters.firestore_alert_common import (
    _automatic_event_from_dict,
    _aware,
    _iso,
    _json_safe,
    _manual_event_from_dict,
    _telegram_message_to_dict,
    _transition_fingerprint,
)
from safety_dashboard.alerts.domain import (
    ManualDispatchStatus,
    ManualTelegramDispatch,
    NotificationEvent,
)


class FirestoreAlertAuditRepository:
    """운영 상태, 집계, 수동 전파와 비식별 이력 저장 기능."""

    def record_run(
        self,
        day: dt.date,
        counters: Mapping[str, int],
        recipient_hashes: Sequence[str] = (),
    ) -> None:
        values: dict[str, object] = {
            key: firestore.Increment(int(value))
            for key, value in counters.items()
            if value
        }
        values["updated_at"] = firestore.SERVER_TIMESTAMP
        if recipient_hashes:
            values["recipient_hashes"] = firestore.ArrayUnion(list(recipient_hashes))
        self.client.collection(self.collections.metrics).document(day.isoformat()).set(
            values,
            merge=True,
        )

    def update_status(self, values: Mapping[str, object]) -> None:
        self.status_ref.set(dict(values), merge=True)

    def notification_status(self) -> dict[str, object]:
        snapshot = self.status_ref.get()
        value = _json_safe(snapshot.to_dict() if snapshot.exists else {})
        return dict(value) if isinstance(value, Mapping) else {}

    def admin_notice_due(
        self,
        key: str,
        now: dt.datetime,
        interval: dt.timedelta,
    ) -> bool:
        ref = self.client.collection(self.collections.admin_notices).document(key)
        transaction = self.client.transaction()

        @firestore.transactional
        def reserve(txn: Any) -> bool:
            snapshot = ref.get(transaction=txn)
            values = snapshot.to_dict() if snapshot.exists else {}
            last_at = values.get("last_at")
            if last_at and _aware(last_at) + interval > _aware(now):
                return False
            txn.set(ref, {"last_at": now}, merge=True)
            return True

        return bool(reserve(transaction))

    def notification_metrics(self, start: dt.date, end: dt.date) -> dict[str, object]:
        totals: dict[str, int] = {}
        recipients: set[str] = set()
        current = start
        while current <= end:
            snapshot = self.client.collection(self.collections.metrics).document(
                current.isoformat()
            ).get()
            values = snapshot.to_dict() if snapshot.exists else {}
            for key, value in values.items():
                if key in {"recipient_hashes", "updated_at"}:
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
            "delivery_success_rate": (
                round(delivered / terminal * 100, 1) if terminal else None
            ),
        }

    def create_manual_dispatch(self, value: ManualTelegramDispatch) -> bool:
        ref = self.client.collection(self.collections.manual_dispatches).document(
            value.id
        )
        try:
            ref.create({
                "created_at": value.created_at,
                "category": value.category.value,
                "operator_label": value.operator_label,
                "note": value.note,
                "mode": value.mode,
                "facility_ids": sorted(set(value.facility_ids)),
                "warning_keys": sorted(set(value.warning_keys)),
                "messages": [
                    _telegram_message_to_dict(item) for item in value.messages
                ],
                "message_count": len(value.messages),
                "policy_version": value.policy_version,
                "temporary_policy": value.temporary_policy,
                "fingerprint": value.fingerprint,
                "status": ManualDispatchStatus.PENDING.value,
            })
            return True
        except AlreadyExists:
            return False

    def manual_dispatch(self, dispatch_id: str) -> Mapping[str, object] | None:
        snapshot = self.client.collection(self.collections.manual_dispatches).document(
            dispatch_id
        ).get()
        return dict(snapshot.to_dict() or {}) if snapshot.exists else None

    def update_manual_dispatch(
        self, dispatch_id: str, values: Mapping[str, object]
    ) -> None:
        self.client.collection(self.collections.manual_dispatches).document(
            dispatch_id
        ).set(dict(values), merge=True)

    def recent_duplicate(
        self, fingerprint: str, since: dt.datetime
    ) -> NotificationEvent | None:
        manual_query = self.client.collection(self.collections.manual_dispatches).where(
            filter=FieldFilter("created_at", ">=", since)
        )
        for snapshot in manual_query.stream():
            values = snapshot.to_dict() or {}
            if values.get("fingerprint") == fingerprint:
                return _manual_event_from_dict(snapshot.id, values)
        batch_query = self.client.collection(self.collections.batches).where(
            filter=FieldFilter("created_at", ">=", since)
        )
        for snapshot in batch_query.stream():
            values = snapshot.to_dict() or {}
            if values.get("mode") != "live":
                continue
            if _transition_fingerprint(values.get("transitions", [])) == fingerprint:
                return _automatic_event_from_dict(snapshot.id, values)
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
            query = self.client.collection(self.collections.batches).where(
                filter=FieldFilter("created_at", ">=", start)
            ).where(filter=FieldFilter("created_at", "<", end))
            for snapshot in query.stream():
                values = snapshot.to_dict() or {}
                if values.get("mode") == "live":
                    events.append(_automatic_event_from_dict(snapshot.id, values))
        if source in {"all", "manual"}:
            query = self.client.collection(self.collections.manual_dispatches).where(
                filter=FieldFilter("created_at", ">=", start)
            ).where(filter=FieldFilter("created_at", "<", end))
            for snapshot in query.stream():
                events.append(_manual_event_from_dict(
                    snapshot.id, snapshot.to_dict() or {}
                ))
        if status != "all":
            events = [item for item in events if item.status == status]
        events.sort(key=lambda item: item.occurred_at, reverse=True)
        return tuple(events[:limit])

    def export_rows(self, start: dt.datetime, end: dt.datetime) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        batch_query = self.client.collection(self.collections.batches).where(
            filter=FieldFilter("created_at", ">=", start)
        ).where(filter=FieldFilter("created_at", "<", end))
        for snapshot in batch_query.stream():
            values = snapshot.to_dict() or {}
            if values.get("mode") != "live":
                continue
            for transition in values.get("transitions", []):
                impact = transition.get("current") or transition.get("previous") or {}
                rows.append({
                    "record_type": "transition",
                    "source": "automatic",
                    "timestamp": _iso(values.get("created_at")),
                    "event": transition.get("kind", ""),
                    "facility_id": impact.get("facility_id", ""),
                    "facility_name": impact.get("facility_name", ""),
                    "warning": (
                        f"{impact.get('warning_type', '')} "
                        f"{impact.get('raw_level', '')}"
                    ).strip(),
                    "recipient_code": "",
                    "delivery_status": values.get("status", ""),
                    "category": "",
                    "operator_label": "",
                })
        delivery_query = self.client.collection(self.collections.deliveries).where(
            filter=FieldFilter("attempted_at", ">=", start)
        ).where(filter=FieldFilter("attempted_at", "<", end))
        for snapshot in delivery_query.stream():
            values = snapshot.to_dict() or {}
            if values.get("metric_scope", "operational") != "operational":
                continue
            rows.append({
                "record_type": "sms",
                "source": "automatic",
                "timestamp": _iso(values.get("attempted_at")),
                "event": "",
                "facility_id": ",".join(values.get("facility_ids", [])),
                "facility_name": "",
                "warning": "",
                "recipient_code": str(values.get("recipient_hash", ""))[:12],
                "delivery_status": values.get("status", ""),
                "category": "",
                "operator_label": "",
            })
        manual_query = self.client.collection(self.collections.manual_dispatches).where(
            filter=FieldFilter("created_at", ">=", start)
        ).where(filter=FieldFilter("created_at", "<", end))
        for snapshot in manual_query.stream():
            values = snapshot.to_dict() or {}
            rows.append({
                "record_type": "telegram",
                "source": "manual",
                "timestamp": _iso(values.get("created_at")),
                "event": values.get("category", ""),
                "facility_id": ",".join(values.get("facility_ids", [])),
                "facility_name": "",
                "warning": ",".join(values.get("warning_keys", [])),
                "recipient_code": "",
                "delivery_status": values.get("status", ""),
                "category": values.get("category", ""),
                "operator_label": values.get("operator_label", ""),
            })
        rows.sort(key=lambda item: str(item.get("timestamp", "")))
        return rows
