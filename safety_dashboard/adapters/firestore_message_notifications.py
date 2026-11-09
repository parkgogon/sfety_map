"""Atomic notification planning and dirty-marker acknowledgement across message collections."""
from __future__ import annotations

import copy

from safety_dashboard.adapters.firestore_message_pipeline import FirestoreMessagePipelineStore
from safety_dashboard.application.message_notification_jobs import validate_writes


class FirestoreMessageNotificationStore(FirestoreMessagePipelineStore):
    def run_record(self, identifier, keys, update):
        refs = {key: self.collection.document(key) for key in dict.fromkeys(keys)}
        record_ref = self.client.collection("disaster_message_reviews").document(identifier)

        def apply(transaction):
            snap = record_ref.get(transaction=transaction, timeout=5)
            current = snap.to_dict() if snap.exists else None
            values = {}
            for key, ref in refs.items():
                snap = ref.get(transaction=transaction, timeout=5)
                values[key] = snap.to_dict() if snap.exists else None
            writes, acknowledge, result = update(copy.deepcopy(current), values)
            validate_writes(keys, writes)
            # All record and notification reads precede every write.
            for key, value in writes.items():
                transaction.set(refs[key], value)
            if acknowledge and current:
                transaction.set(record_ref, {**current, "notification_dirty": False})
            return result

        return self.transaction_runner(apply)(self.client.transaction())
