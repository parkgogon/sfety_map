"""자동 알림 상태·발송·실적을 Firestore에 저장합니다."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from safety_dashboard.alerts.domain import (
    AlertBatch,
    AlertTransition,
    AlertTransitionKind,
    FacilityImpact,
    OutgoingSmsMessage,
    SmsDeliveryResult,
    SmsDeliveryStatus,
)
from safety_dashboard.domain.enums import RiskGrade, WarningLevel


KST = dt.timezone(dt.timedelta(hours=9))


class FirestoreAlertStore:
    def __init__(self, project_id: str = "", *, client: Any | None = None) -> None:
        self.client = client or firestore.Client(project=project_id or None)
        self.state_ref = self.client.collection("alert_state").document("current")
        self.lock_ref = self.client.collection("alert_state").document("dispatch_lock")
        self.status_ref = self.client.collection("alert_state").document("status")

    def acquire_lock(self, run_id: str, now: dt.datetime) -> bool:
        transaction = self.client.transaction()

        @firestore.transactional
        def acquire(txn: Any) -> bool:
            snapshot = self.lock_ref.get(transaction=txn)
            values = snapshot.to_dict() if snapshot.exists else {}
            expires_at = values.get("expires_at")
            if expires_at and _aware(expires_at) > _aware(now):
                return False
            txn.set(
                self.lock_ref,
                {
                    "holder": run_id,
                    "acquired_at": now,
                    "expires_at": now + dt.timedelta(minutes=4),
                },
            )
            return True

        return bool(acquire(transaction))

    def release_lock(self, run_id: str, now: dt.datetime) -> None:
        snapshot = self.lock_ref.get()
        values = snapshot.to_dict() if snapshot.exists else {}
        if values.get("holder") == run_id:
            self.lock_ref.set(
                {"holder": "", "released_at": now, "expires_at": now},
                merge=True,
            )

    def load_state(self) -> tuple[bool, str, tuple[FacilityImpact, ...]]:
        snapshot = self.state_ref.get()
        if not snapshot.exists:
            return False, "", ()
        values = snapshot.to_dict() or {}
        impacts = tuple(_impact_from_dict(item) for item in values.get("impacts", []))
        return bool(values.get("initialized")), str(values.get("mode", "")), impacts

    def save_state(
        self,
        impacts: Sequence[FacilityImpact],
        mode: str,
        now: dt.datetime,
    ) -> None:
        self.state_ref.set(
            {
                "initialized": True,
                "mode": mode,
                "updated_at": now,
                "impacts": [_impact_to_dict(item) for item in impacts],
            }
        )

    def save_batch(self, batch: AlertBatch, status: str) -> None:
        self.client.collection("alert_batches").document(batch.id).set(
            {
                "created_at": batch.created_at,
                "mode": batch.mode,
                "policy_version": batch.policy_version,
                "status": status,
                "transition_count": len(batch.transitions),
                "facility_ids": sorted({
                    item.impact.facility_id for item in batch.transitions
                }),
                "transitions": [_transition_to_dict(item) for item in batch.transitions],
            },
            merge=True,
        )

    def save_pending(
        self,
        transitions: Sequence[AlertTransition],
        expires_at: dt.datetime,
    ) -> None:
        batch = self.client.batch()
        for item in transitions:
            ref = self.client.collection("alert_pending").document(item.id)
            batch.set(
                ref,
                {
                    "status": "PENDING",
                    "expires_at": expires_at,
                    "transition": _transition_to_dict(item),
                },
                merge=True,
            )
        batch.commit()

    def load_pending(self, now: dt.datetime) -> tuple[AlertTransition, ...]:
        result = []
        expired = []
        for snapshot in self.client.collection("alert_pending").stream():
            values = snapshot.to_dict() or {}
            if values.get("status") != "PENDING":
                continue
            expires_at = values.get("expires_at")
            if expires_at and _aware(expires_at) < _aware(now):
                expired.append(snapshot.reference)
                continue
            result.append(_transition_from_dict(values["transition"]))
        if expired:
            batch = self.client.batch()
            for ref in expired:
                batch.set(ref, {"status": "EXPIRED", "resolved_at": now}, merge=True)
            batch.commit()
        return tuple(result)

    def resolve_pending(self, transition_ids: Sequence[str], status: str) -> None:
        if not transition_ids:
            return
        batch = self.client.batch()
        now = dt.datetime.now(dt.timezone.utc)
        for transition_id in transition_ids:
            ref = self.client.collection("alert_pending").document(transition_id)
            batch.set(ref, {"status": status, "resolved_at": now}, merge=True)
        batch.commit()

    def reserve_delivery(
        self,
        message: OutgoingSmsMessage,
        now: dt.datetime,
        metric_scope: str = "operational",
    ) -> str:
        ref = self.client.collection("alert_deliveries").document(message.id)
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
        ref = self.client.collection("alert_deliveries").document(message.id)
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
            self.client.collection("alert_provider_messages").document(
                result.provider_message_id
            ).set({"delivery_id": message.id})

    def sms_count(self, day: dt.date) -> int:
        snapshot = self.client.collection("alert_metrics").document(day.isoformat()).get()
        values = snapshot.to_dict() if snapshot.exists else {}
        return int(values.get("sms_attempted", 0))

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
        self.client.collection("alert_metrics").document(day.isoformat()).set(
            values,
            merge=True,
        )

    def update_status(self, values: Mapping[str, object]) -> None:
        self.status_ref.set(dict(values), merge=True)

    def admin_notice_due(
        self,
        key: str,
        now: dt.datetime,
        interval: dt.timedelta,
    ) -> bool:
        ref = self.client.collection("alert_admin_notices").document(key)
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

    def notification_status(self) -> dict[str, object]:
        snapshot = self.status_ref.get()
        return _json_safe(snapshot.to_dict() if snapshot.exists else {})

    def notification_metrics(self, start: dt.date, end: dt.date) -> dict[str, object]:
        totals: dict[str, int] = {}
        recipients: set[str] = set()
        current = start
        while current <= end:
            snapshot = self.client.collection("alert_metrics").document(
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
        terminal = delivered + totals.get("sms_failed", 0)
        return {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "totals": totals,
            "delivery_success_rate": round(delivered / terminal * 100, 1) if terminal else None,
        }

    def export_rows(self, start: dt.datetime, end: dt.datetime) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        batch_query = self.client.collection("alert_batches").where(
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
                    "timestamp": _iso(values.get("created_at")),
                    "event": transition.get("kind", ""),
                    "facility_id": impact.get("facility_id", ""),
                    "facility_name": impact.get("facility_name", ""),
                    "warning": f"{impact.get('warning_type', '')} {impact.get('raw_level', '')}".strip(),
                    "recipient_code": "",
                    "delivery_status": values.get("status", ""),
                })
        delivery_query = self.client.collection("alert_deliveries").where(
            filter=FieldFilter("attempted_at", ">=", start)
        ).where(filter=FieldFilter("attempted_at", "<", end))
        for snapshot in delivery_query.stream():
            values = snapshot.to_dict() or {}
            if values.get("metric_scope", "operational") != "operational":
                continue
            rows.append({
                "record_type": "sms",
                "timestamp": _iso(values.get("attempted_at")),
                "event": "",
                "facility_id": ",".join(values.get("facility_ids", [])),
                "facility_name": "",
                "warning": "",
                "recipient_code": str(values.get("recipient_hash", ""))[:12],
                "delivery_status": values.get("status", ""),
            })
        rows.sort(key=lambda item: str(item.get("timestamp", "")))
        return rows

    def apply_provider_report(
        self,
        provider_message_id: str,
        status_code: str,
        processed_at: dt.datetime,
        delivery_id_hint: str = "",
    ) -> bool:
        mapping_ref = self.client.collection("alert_provider_messages").document(
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
        delivery_ref = self.client.collection("alert_deliveries").document(delivery_id)
        target = _provider_status(status_code)
        transaction = self.client.transaction()

        @firestore.transactional
        def update(txn: Any) -> tuple[bool, str, str]:
            snapshot = delivery_ref.get(transaction=txn)
            if not snapshot.exists:
                return False, "", "operational"
            values = snapshot.to_dict() or {}
            previous = str(values.get("status", ""))
            metric_scope = str(values.get("metric_scope", "operational"))
            if previous == target.value or previous in {
                SmsDeliveryStatus.DELIVERED.value,
                SmsDeliveryStatus.FAILED.value,
            }:
                return False, str(values.get("attempted_day", "")), metric_scope
            txn.set(
                delivery_ref,
                {
                    "status": target.value,
                    "provider_status_code": status_code,
                    "provider_reported_at": processed_at,
                },
                merge=True,
            )
            return True, str(values.get("attempted_day", "")), metric_scope

        changed, day, scope = update(transaction)
        if changed and day and target in {
            SmsDeliveryStatus.DELIVERED,
            SmsDeliveryStatus.FAILED,
        }:
            prefix = "test_sms" if scope == "test" else "sms"
            field = (
                f"{prefix}_delivered"
                if target is SmsDeliveryStatus.DELIVERED
                else f"{prefix}_failed"
            )
            self.client.collection("alert_metrics").document(day).set(
                {field: firestore.Increment(1), "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        return bool(changed)


def _impact_to_dict(value: FacilityImpact) -> dict[str, object]:
    return {
        "key": value.key,
        "facility_id": value.facility_id,
        "facility_name": value.facility_name,
        "warning_key": value.warning_key,
        "warning_id": value.warning_id,
        "region_code": value.region_code,
        "region": value.region,
        "warning_type": value.warning_type,
        "raw_level": value.raw_level,
        "warning_level": value.warning_level.value,
        "risk_grade": value.risk_grade.value,
        "issued_at": _iso(value.issued_at),
        "effective_at": _iso(value.effective_at),
        "recommended_action": value.recommended_action,
    }


def _impact_from_dict(value: Mapping[str, object]) -> FacilityImpact:
    return FacilityImpact(
        key=str(value["key"]),
        facility_id=str(value["facility_id"]),
        facility_name=str(value["facility_name"]),
        warning_key=str(value["warning_key"]),
        warning_id=str(value["warning_id"]),
        region_code=str(value["region_code"]),
        region=str(value["region"]),
        warning_type=str(value["warning_type"]),
        raw_level=str(value["raw_level"]),
        warning_level=WarningLevel(str(value["warning_level"])),
        risk_grade=RiskGrade(str(value["risk_grade"])),
        issued_at=_parse_datetime(value.get("issued_at")),
        effective_at=_parse_datetime(value.get("effective_at")),
        recommended_action=str(value.get("recommended_action", "")),
    )


def _transition_to_dict(value: AlertTransition) -> dict[str, object]:
    return {
        "id": value.id,
        "kind": value.kind.value,
        "detected_at": value.detected_at.isoformat(),
        "previous": _impact_to_dict(value.previous) if value.previous else None,
        "current": _impact_to_dict(value.current) if value.current else None,
        "delayed": value.delayed,
    }


def _transition_from_dict(value: Mapping[str, object]) -> AlertTransition:
    previous = value.get("previous")
    current = value.get("current")
    return AlertTransition(
        id=str(value["id"]),
        kind=AlertTransitionKind(str(value["kind"])),
        detected_at=_parse_datetime(value.get("detected_at")) or dt.datetime.now(dt.timezone.utc),
        previous=_impact_from_dict(previous) if isinstance(previous, Mapping) else None,
        current=_impact_from_dict(current) if isinstance(current, Mapping) else None,
        delayed=bool(value.get("delayed", False)),
    )


def _provider_status(code: str) -> SmsDeliveryStatus:
    # SINGLE-REPORT 웹훅은 개별 메시지 처리가 끝난 뒤 호출된다.
    # SOLAPI에서 4000만 '수신 완료'이며, 나머지 최종 코드는 실패로 집계한다.
    if code == "4000":
        return SmsDeliveryStatus.DELIVERED
    return SmsDeliveryStatus.FAILED


def _parse_datetime(value: object) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _iso(value: object) -> str:
    return value.isoformat() if isinstance(value, (dt.datetime, dt.date)) else str(value or "")


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return value
