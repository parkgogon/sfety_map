"""재난문자 전용 컬렉션. 현재 기록과 버전 이력을 하나의 트랜잭션으로 저장."""
from __future__ import annotations

import json
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from safety_dashboard.application.message_records import RecordConflict, RecordStorageUnavailable, preserve_observation, newer_observation


class FirestoreMessageRecordStore:
    def __init__(self, project_id="", *, client=None, transaction_runner=firestore.transactional):
        self.client = client or firestore.Client(project=project_id or None)
        self.records = self.client.collection("disaster_message_reviews")
        self.transaction_runner = transaction_runner

    def get(self, identifier):
        snapshot = self.records.document(identifier).get(timeout=5)
        return snapshot.to_dict() if snapshot.exists else None

    def get_many(self, identifiers):
        return {snap.id: snap.to_dict() for snap in self.client.get_all(
            [self.records.document(key) for key in identifiers], timeout=5) if snap.exists}

    def list_page(self, before, limit):
        query = self.records.order_by("sort_key", direction=firestore.Query.DESCENDING)
        if before:
            query = query.start_after({"sort_key": before})
        return [snap.to_dict() for snap in query.limit(limit).stream(timeout=5)]

    def commit(self, record, expected, event):
        value = {**record, "version": expected + 1, "notification_dirty": True}
        if len(json.dumps(value, ensure_ascii=False).encode()) > 800_000:
            raise RecordStorageUnavailable("검토 기록이 저장 크기 한도를 넘었습니다.")
        ref = self.records.document(record["id"])

        def write(transaction):
            snapshot = ref.get(transaction=transaction, timeout=5)
            current = snapshot.to_dict() if snapshot.exists else None
            if (current["version"] if current else 0) != expected:
                raise RecordConflict("기록이 변경됐습니다. 다시 불러온 뒤 진행해 주세요.")
            saved = preserve_observation(value, current)
            transaction.set(ref, saved)
            transaction.set(ref.collection("versions").document(f"{expected + 1:010d}"), {"event": event, "record": saved})
            return saved

        return self.transaction_runner(write)(self.client.transaction())

    def list_notification_dirty(self, limit=20):
        query = self.records.where(filter=FieldFilter("notification_dirty", "==", True)).limit(limit)
        return [snap.to_dict() for snap in query.stream(timeout=5)]

    def observe_official(self, identifier, digest, fetched_at):
        ref = self.records.document(identifier)

        def observe(transaction):
            snapshot = ref.get(transaction=transaction, timeout=5)
            current = snapshot.to_dict() if snapshot.exists else None
            if not current or current["content_hash"] != digest:
                return None
            if newer_observation(fetched_at, current.get("official_fetched_at")):
                current["official_fetched_at"] = fetched_at
                transaction.set(ref, current)
            return current

        return self.transaction_runner(observe)(self.client.transaction())

    def history(self, identifier, before, limit):
        query = self.records.document(identifier).collection("versions").order_by("record.version", direction=firestore.Query.DESCENDING)
        if before is not None:
            query = query.start_after({"record.version": before})
        return [snap.to_dict() for snap in query.limit(limit).stream(timeout=5)]
