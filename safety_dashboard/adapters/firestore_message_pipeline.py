"""Message automation state, shared leases and budget; no alert state access."""
from __future__ import annotations
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

class FirestoreMessagePipelineStore:

    def __init__(self, project_id='', *, client=None, transaction_runner=firestore.transactional):
        self.client = client or firestore.Client(project=project_id or None)
        self.collection = self.client.collection('disaster_message_pipeline')
        self.transaction_runner = transaction_runner

    def get(self, key):
        snap = self.collection.document(key).get(timeout=5)
        return snap.to_dict() if snap.exists else None

    def run(self, keys, update):
        refs = {key: self.collection.document(key) for key in dict.fromkeys(keys)}

        def apply(transaction):
            values = {}
            for key, ref in refs.items():
                snap = ref.get(transaction=transaction, timeout=5)
                values[key] = snap.to_dict() if snap.exists else None
            writes, result = update(values)
            if set(writes) - set(refs):
                raise ValueError('transaction_keys')
            for key, value in writes.items():
                transaction.set(refs[key], value)
            return result
        return self.transaction_runner(apply)(self.client.transaction())

    def scan(self, low, high, limit, *, reverse=False):
        query = self.collection.where(filter=FieldFilter('queue_key', '>=', low)).where(filter=FieldFilter('queue_key', '<=', high))
        query = query.order_by('queue_key', direction=firestore.Query.DESCENDING) if reverse else query.order_by('queue_key')
        query = query.limit(limit)
        return [snap.to_dict() for snap in query.stream(timeout=5)]
