"""Firestore 자동알림 기준 상태와 배치를 저장하는 책임."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from google.cloud import firestore

from safety_dashboard.adapters.firestore_alert_common import (
    _aware,
    _impact_from_dict,
    _impact_to_dict,
    _parse_datetime,
    _transition_from_dict,
    _transition_to_dict,
)
from safety_dashboard.alerts.domain import AlertBatch, AlertTransition, FacilityImpact


class FirestoreAlertStateRepository:
    """실행 잠금, 기준 상태, 배치와 보류 전환 저장 기능."""

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
        self.client.collection(self.collections.batches).document(batch.id).set(
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

    def update_batch_delivery(
        self, batch_id: str, values: Mapping[str, object]
    ) -> None:
        self.client.collection(self.collections.batches).document(batch_id).set(
            dict(values), merge=True
        )

    def load_batch(self, batch_id: str) -> AlertBatch | None:
        snapshot = self.client.collection(self.collections.batches).document(
            batch_id
        ).get()
        if not snapshot.exists:
            return None
        values = snapshot.to_dict() or {}
        return AlertBatch(
            id=batch_id,
            created_at=_parse_datetime(values.get("created_at"))
            or dt.datetime.now(dt.timezone.utc),
            transitions=tuple(
                _transition_from_dict(item)
                for item in values.get("transitions", [])
            ),
            mode=str(values.get("mode", "")),
            policy_version=str(values.get("policy_version", "")),
        )

    def save_pending(
        self,
        transitions: Sequence[AlertTransition],
        expires_at: dt.datetime,
    ) -> None:
        batch = self.client.batch()
        for item in transitions:
            ref = self.client.collection(self.collections.pending).document(item.id)
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
        for snapshot in self.client.collection(self.collections.pending).stream():
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
            ref = self.client.collection(self.collections.pending).document(
                transition_id
            )
            batch.set(ref, {"status": status, "resolved_at": now}, merge=True)
        batch.commit()
