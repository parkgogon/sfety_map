"""Transaction spies test adapter boundaries, not production Firestore IAM/availability."""
import copy
import unittest
from unittest.mock import Mock

from safety_dashboard.adapters.firestore_message_notifications import FirestoreMessageNotificationStore
from safety_dashboard.adapters.firestore_message_records import FirestoreMessageRecordStore
from safety_dashboard.application.message_notification_jobs import MessageNotificationPreparation, MemoryNotificationStore, head_key
from scripts.build_message_review_deploy_config import build_config
from tests.test_message_notification import CATALOG,DIGEST,NOW
from tests.test_message_notification_jobs import Fixture


class AtomicFirestore:
    def __init__(self):
        self.documents={};self.operations=[];self.fail_notification_commit_once=False;self.fail_delivery_claim_once=False

    def collection(self,path):
        client=self
        class Collection:
            def __init__(self):self.filters=[];self.maximum=20;self.order=None;self.descending=False
            def document(self,key):return client.ref(path+'/'+key)
            def where(self,*,filter):
                result=copy.copy(self);result.filters=[*self.filters,filter];return result
            def order_by(self,key,**kwargs):
                result=copy.copy(self);result.order=key;result.descending=kwargs.get('direction')=='DESCENDING';return result
            def limit(self,value):
                result=copy.copy(self);result.maximum=value;return result
            def stream(self,**kwargs):
                client.operations.append(('query',path,[(f.field_path,f.op_string) for f in self.filters],self.order,self.maximum))
                rows=[(key,value) for key,value in client.documents.items() if key.rsplit('/',1)[0]==path]
                for f in self.filters:
                    def accepted(row):
                        v=row[1].get(f.field_path)
                        return v is not None and (v==f.value if f.op_string=='==' else v>=f.value if f.op_string=='>=' else v<=f.value)
                    rows=[row for row in rows if accepted(row)]
                def order_value(row):
                    value = row[1]
                    for field in self.order.split('.'):
                        value = value[field]
                    return value
                rows.sort(key=order_value if self.order else lambda row:row[0],reverse=self.descending)
                return [Mock(id=key.rsplit('/',1)[1],to_dict=lambda v=value:copy.deepcopy(v)) for key,value in rows[:self.maximum]]
        return Collection()

    def ref(self,path):
        client=self
        class Ref:
            def get(self,**kwargs):
                client.operations.append(('get',path))
                value=client.documents.get(path)
                return Mock(exists=value is not None,to_dict=lambda:copy.deepcopy(value))
            def collection(self,name):return client.collection(path+'/'+name)
        result=Ref();result.path=path;return result

    def transaction(self):
        client=self
        class Transaction:
            def __init__(self):self.staged={}
            def set(self,ref,value):
                client.operations.append(('set',ref.path));self.staged[ref.path]=copy.deepcopy(value)
        return Transaction()

    def runner(self,callback):
        def run(transaction):
            result=callback(transaction)
            if self.fail_notification_commit_once and any('/notification-decision-' in key for key in transaction.staged):
                self.fail_notification_commit_once=False
                raise RuntimeError('simulated transaction abort')
            if self.fail_delivery_claim_once and any('/message-delivery-' in key and value.get('state')=='sending' for key,value in transaction.staged.items()):
                self.fail_delivery_claim_once=False
                raise RuntimeError('simulated delivery claim abort')
            self.documents.update(copy.deepcopy(transaction.staged));self.operations.append(('commit',tuple(transaction.staged)))
            return result
        return run


class NotificationStoreTests(unittest.TestCase):
    def firestore_fixture(self):
        f=Fixture();client=AtomicFirestore()
        f.records._store=FirestoreMessageRecordStore(client=client,transaction_runner=client.runner)
        f.repo=FirestoreMessageNotificationStore(client=client,transaction_runner=client.runner)
        f.planner=f.new_planner();f.clock[0]=NOW.replace(hour=9)
        f.planner.activate();f.clock[0]=NOW
        return f,client

    def test_cross_collection_reads_precede_writes_and_ack_does_not_add_human_versions(self):
        f,client=self.firestore_fixture();record=f.analyzed()
        before_versions={k:v for k,v in client.documents.items() if '/versions/' in k}
        before=len(client.operations);result=f.planner.prepare_record(record['id']);ops=client.operations[before:]
        first_set=next(i for i,op in enumerate(ops) if op[0]=='set')
        self.assertFalse(any(op[0]=='get' for op in ops[first_set:]))
        self.assertTrue(any(op[0]=='get' and op[1]==f"disaster_message_reviews/{record['id']}" for op in ops))
        self.assertEqual(f.repo.get(result['job_id'])['state'],'pending')
        self.assertFalse(f.records.get(record['id'])['notification_dirty'])
        self.assertEqual(f.records.get(record['id'])['version'],record['version'])
        self.assertEqual({k:v for k,v in client.documents.items() if '/versions/' in k},before_versions)
        self.assertTrue(all(k.startswith(('disaster_message_pipeline/','disaster_message_reviews/')) for k in client.documents))

    def test_aborted_firestore_plan_transaction_leaves_no_job_and_restarts_without_model(self):
        f,client=self.firestore_fixture();record=f.analyzed()
        client.fail_notification_commit_once=True
        with self.assertRaises(RuntimeError):f.planner.prepare_record(record['id'])
        self.assertTrue(f.records.get(record['id'])['notification_dirty'])
        self.assertIsNone(f.repo.get(head_key(record['id'])))
        self.assertFalse(any('/notification-job-' in key for key in client.documents))
        f.new_planner().run()
        self.assertEqual(f.planner.read_record(record['id'])['state'],'pending')
        self.assertEqual(f.analyzer.analyze.call_count,1)
        query=next(op for op in client.operations if op[0]=='query' and op[1]=='disaster_message_reviews')
        self.assertEqual(query[2], [('notification_dirty','==')])
        self.assertIsNone(query[3])

    def test_memory_transaction_cannot_clear_dirty_on_invalid_write_or_mutate_human_fields(self):
        f=Fixture();record=f.analyzed();before=f.records.get(record['id'])
        with self.assertRaises(ValueError):
            f.repo.run_record(record['id'],['allowed'],lambda current,values:({'other':{}},True,None))
        self.assertEqual(f.records.get(record['id']),before)
        self.assertNotIn('other',f.pipeline.values)
        def update(current,values):
            current['note']='not allowed through notification repository'
            return {},True,None
        f.repo.run_record(record['id'],[],update)
        self.assertEqual(f.records.get(record['id'])['note'],before['note'])
        self.assertEqual(f.records.get(record['id'])['version'],before['version'])

    def test_feature_flag_is_off_by_default_strict_and_does_not_bind_telegram_secrets(self):
        self.assertIn('MESSAGE_NOTIFICATION_PREPARATION_ENABLED=false',build_config({})['MESSAGE_REVIEW_ENV_VARS'])
        config=build_config({'MESSAGE_NOTIFICATION_PREPARATION_ENABLED':'true'})
        self.assertIn('MESSAGE_NOTIFICATION_PREPARATION_ENABLED=true',config['MESSAGE_REVIEW_ENV_VARS'])
        self.assertEqual(config['MESSAGE_REVIEW_SECRET_BINDINGS'],'')
        with self.assertRaises(ValueError):build_config({'MESSAGE_NOTIFICATION_PREPARATION_ENABLED':'live'})
