"""공통 관제 snapshot을 Firestore에 원자적으로 저장합니다."""

from __future__ import annotations

import json
from typing import Any

from google.cloud import firestore

from safety_dashboard.monitoring.snapshot import (
    MonitoringSnapshot,
    MonitoringSnapshotError,
)


MAX_DOCUMENT_BYTES = 900_000


class FirestoreMonitoringSnapshotStore:
    def __init__(self, project_id: str = "", *, client: Any | None = None) -> None:
        self.client = client or firestore.Client(project=project_id or None)
        self.snapshots = self.client.collection("monitoring_snapshots")
        self.latest_ref = self.client.collection("monitoring_state").document("latest")

    def save_latest(self, snapshot: MonitoringSnapshot) -> None:
        document = snapshot.to_document()
        size = len(
            json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        if size > MAX_DOCUMENT_BYTES:
            raise MonitoringSnapshotError(
                f"관제 snapshot이 Firestore 안전 크기를 초과했습니다: {size} bytes"
            )
        snapshot_ref = self.snapshots.document(snapshot.id)
        batch = self.client.batch()
        batch.set(snapshot_ref, document)
        batch.set(
            self.latest_ref,
            {
                "snapshot_id": snapshot.id,
                "schema_version": snapshot.schema_version,
                "stored_at": snapshot.stored_at,
                "generated_at": snapshot.generated_at,
                "kma_fetched_at": snapshot.kma_fetched_at,
                "policy_version": snapshot.policy_version,
                "health": snapshot.health.value,
                "document_path": snapshot_ref.path,
            },
        )
        batch.commit()

    def load_latest(self) -> MonitoringSnapshot | None:
        pointer = self.latest_ref.get()
        if not pointer.exists:
            return None
        pointer_values = pointer.to_dict() or {}
        snapshot_id = str(pointer_values.get("snapshot_id", ""))
        if not snapshot_id:
            raise MonitoringSnapshotError("최신 관제 snapshot ID가 비어 있습니다.")
        stored = self.snapshots.document(snapshot_id).get()
        if not stored.exists:
            raise MonitoringSnapshotError(
                f"최신 관제 snapshot 문서를 찾을 수 없습니다: {snapshot_id}"
            )
        return MonitoringSnapshot.from_document(stored.to_dict() or {})
