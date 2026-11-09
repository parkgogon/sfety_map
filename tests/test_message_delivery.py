import copy
import datetime as dt
import threading
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from safety_dashboard.adapters.telegram import TelegramDeliveryResult
from safety_dashboard.admin.access import AdminAccessSettings, AdminAccessVerifier
from safety_dashboard.api.app import create_app
from safety_dashboard.application.message_delivery import MessageDelivery, CONTROL, delivery_key
from safety_dashboard.application.message_notification_jobs import head_key
from safety_dashboard.application.message_pipeline import stamp
from safety_dashboard.application.message_records import AnalyzeRecord, RecordConflict, SaveRecordNote
from tests.test_message_notification import NOW
from tests.test_message_notification_jobs import Fixture
from tests import test_message_notification_store as notification_store_tests
from safety_dashboard.application.message_automation import MessageAutomationSettings
from safety_dashboard.application.message_runtime import MessageRuntime
from safety_dashboard.operations.message_worker import create_app as worker_app


class Sender:
    configured=True
    def __init__(self):self.calls=[];self.results=[]
    def send_once(self,text):
        self.calls.append(text)
        return self.results.pop(0) if self.results else TelegramDeliveryResult('sent',message_id=len(self.calls),detail='receipt_confirmed')


class DeliveryFixture(Fixture):
    def __init__(self, *, start=True):
        super().__init__()
        self.planner.delivery_tracking_enabled=True
        self.staff,self.admin=Sender(),Sender()
        self.delivery=self.service()
        if start:
            self.clock[0]=NOW-dt.timedelta(minutes=6)
            self.delivery.configure('start',None)
            self.clock[0]=NOW

    def service(self, **kwargs):
        return MessageDelivery(self.planner,{'staff_group':self.staff,'admin_group':self.admin},
            enabled=kwargs.pop('enabled',True),binding=kwargs.pop('binding','fake-binding'),
            revision=kwargs.pop('revision','fake-revision'),now=lambda:self.clock[0],**kwargs)

    def ready(self,identifier='SN-stage2'):
        record=self.analyzed(identifier)
        result=self.planner.prepare_record(record['id'])
        return record,result['job_id']

    def outbox(self,jid):return self.repo.get(delivery_key(jid))


class DeliveryTests(unittest.TestCase):
    def test_receipt_is_persisted_once_without_changing_human_review_or_preview_permission(self):
        f=DeliveryFixture();record,jid=f.ready();before=f.records.store.history(record['id'],None,100)
        result=f.delivery.run()
        f.service().run()
        self.assertEqual(result['sent'],1)
        self.assertEqual(len(f.staff.calls),1)
        self.assertTrue(f.staff.calls[0].startswith('[재난문자 기반 시설 참고 안내]'))
        self.assertNotIn('미발송',f.staff.calls[0].splitlines()[0])
        self.assertEqual(f.outbox(jid)['state'],'sent')
        self.assertEqual(f.outbox(jid)['message_id'],1)
        self.assertFalse(f.repo.get(jid)['dispatch_enabled'])
        self.assertEqual(f.repo.get(jid)['phase'],'preview')
        self.assertEqual(f.records.store.history(record['id'],None,100),before)
        self.assertEqual(f.records.get(record['id'])['review_state'],'unreviewed')

    def test_old_preview_is_excluded_even_if_issued_in_future_or_created_in_same_clock_tick(self):
        f=DeliveryFixture(start=False)
        f.message={**f.message,'issued_at':stamp(NOW+dt.timedelta(minutes=1))}
        record,jid=f.ready()
        f.delivery.configure('start',None)
        f.clock[0]+=dt.timedelta(minutes=1)
        f.delivery.run()
        self.assertEqual(f.staff.calls,[])
        self.assertIsNone(f.outbox(jid))
        self.assertIsNone(f.repo.get(jid)['delivery_generation'])

    def test_paused_start_never_arms_previously_prepared_jobs_and_new_sources_can_deliver(self):
        f=DeliveryFixture();record,jid=f.ready()
        old=f.delivery.status()
        paused=f.delivery.configure('pause',old['generation'])
        f.delivery.run();self.assertEqual(f.staff.calls,[])
        f.clock[0]+=dt.timedelta(minutes=1)
        f.delivery.configure('start',paused['generation'])
        f.delivery.run();self.assertEqual(f.staff.calls,[])
        f.message={**f.message,'issued_at':stamp(f.clock[0])}
        newer,new_jid=f.ready('SN-new')
        f.delivery.run();self.assertEqual(len(f.staff.calls),1)
        self.assertEqual(f.outbox(new_jid)['state'],'sent')

    def test_new_deployment_or_different_bound_destinations_require_new_activation(self):
        for kwargs in ({'revision':'new-revision'},{'binding':'new-targets'},{'ready':False},{'enabled':False}):
            with self.subTest(kwargs=kwargs):
                f=DeliveryFixture();f.ready();other=f.service(**kwargs)
                self.assertFalse(other.status()['active'])
                other.run()
                self.assertEqual(f.staff.calls,[])

    def test_source_or_basis_changed_before_request_prevents_transport(self):
        for change in ('source','note','catalog','expired'):
            with self.subTest(change=change):
                f=DeliveryFixture();record,jid=f.ready();f.delivery.consider_staff(jid)
                if change=='source':
                    f.register(message={**f.message,'text':f.message['text']+' 통제 구간 안내를 정정합니다.'})
                elif change=='note':
                    f.records.save_note(record['id'],SaveRecordNote(expected_version=record['version'],note='근거 재확인',review_state='needs_confirmation'))
                elif change=='catalog':f.planner.catalog=lambda:('changed',())
                else:f.clock[0]+=dt.timedelta(hours=1)
                f.delivery.run()
                self.assertEqual(f.staff.calls,[])
                self.assertEqual(f.outbox(jid)['state'],'cancelled')

    def test_two_worker_instances_cannot_send_the_same_source_twice(self):
        f=DeliveryFixture();_,jid=f.ready();barrier=threading.Barrier(2);errors=[]
        def run():
            try:barrier.wait();f.service().run()
            except Exception as error:errors.append(error)
        threads=[threading.Thread(target=run) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(5)
        self.assertEqual(errors,[])
        self.assertEqual(len(f.staff.calls),1)
        self.assertEqual(f.outbox(jid)['attempts'],1)

    def test_unknown_outcome_is_not_retried_and_admin_receives_a_separate_incident(self):
        f=DeliveryFixture();_,jid=f.ready()
        f.staff.results=[TelegramDeliveryResult('unknown',detail='outcome_unknown')]
        f.delivery.run();f.delivery.run();f.delivery.run()
        self.assertEqual(len(f.staff.calls),1)
        self.assertEqual(f.outbox(jid)['state'],'unknown')
        self.assertIsNone(f.outbox(jid).get('message_id'))
        self.assertEqual(len(f.admin.calls),1)
        self.assertIn('수신 결과가 미상',f.admin.calls[0])
        self.assertNotIn(f.message['text'],f.admin.calls[0])

    def test_definite_rejection_does_not_auto_retry_and_acknowledgement_does_not_mark_api_success(self):
        f=DeliveryFixture();_,jid=f.ready()
        f.staff.results=[TelegramDeliveryResult('rejected',detail='provider_rejected')]
        f.delivery.run();f.delivery.run()
        identifier=delivery_key(jid)
        f.delivery.acknowledge(identifier,'handled_separately')
        self.assertEqual(f.outbox(jid)['state'],'rejected')
        self.assertEqual(f.outbox(jid)['resolution'],'handled_separately')
        f.delivery.run();self.assertEqual(len(f.staff.calls),1)

    def test_only_explicit_rate_limit_is_retried_with_delay_and_three_attempt_ceiling(self):
        f=DeliveryFixture();_,jid=f.ready()
        f.staff.results=[TelegramDeliveryResult('rate_limited',retry_after=1,detail='provider_rate_limit')]*3
        for i in range(3):
            f.delivery.run()
            self.assertEqual(len(f.staff.calls),i+1)
            f.delivery.run();self.assertEqual(len(f.staff.calls),i+1)
            f.clock[0]+=dt.timedelta(seconds=61)
        self.assertEqual(f.outbox(jid)['state'],'rejected')
        self.assertEqual(f.outbox(jid)['attempts'],3)

    def test_crash_after_transport_or_lost_settlement_stays_unknown_without_second_send(self):
        f=DeliveryFixture();_,jid=f.ready()
        with patch.object(f.delivery,'_finish',side_effect=RuntimeError('simulated settlement outage')):
            with self.assertRaises(Exception):f.delivery.run()
        self.assertEqual(f.outbox(jid)['state'],'sending')
        f.clock[0]+=dt.timedelta(minutes=6)
        f.delivery.run();f.delivery.run()
        self.assertEqual(f.outbox(jid)['state'],'unknown')
        self.assertEqual(len(f.staff.calls),1)

    def test_stop_during_prepare_and_atomic_claim_failure_do_not_call_transport(self):
        f=DeliveryFixture();_,jid=f.ready();original=f.repo.run_record
        def paused(*args,**kwargs):
            control=f.repo.get(CONTROL)
            if f.outbox(jid) and control['mode']=='active':f.delivery.configure('pause',control['generation'])
            return original(*args,**kwargs)
        with patch.object(f.repo,'run_record',side_effect=paused):f.delivery.run()
        self.assertEqual(f.staff.calls,[])
        f=DeliveryFixture();_,jid=f.ready()
        with patch.object(f.repo,'run_record',side_effect=RuntimeError('atomic store failed')):
            with self.assertRaises(RuntimeError):f.delivery.run()
        self.assertEqual(f.staff.calls,[])

    def test_control_generation_conflict_does_not_reset_activation(self):
        f=DeliveryFixture();before=f.repo.get(CONTROL)
        with self.assertRaises(RecordConflict):f.delivery.configure('start',None)
        self.assertEqual(f.repo.get(CONTROL),before)

    def test_history_and_decision_pages_are_read_only_and_latest_first(self):
        f=DeliveryFixture()
        for i in range(3):
            f.ready('SN-'+str(i));f.delivery.run();f.clock[0]+=dt.timedelta(seconds=1)
        before=copy.deepcopy(f.pipeline.values)
        first=f.delivery.page('deliveries',limit=2)
        self.assertEqual(len(first['items']),2)
        second=f.delivery.page('deliveries',before=first['next_cursor'],limit=2)
        self.assertEqual(len(second['items']),1)
        self.assertFalse(set(r['id'] for r in first['items'])&set(r['id'] for r in second['items']))
        self.assertTrue(f.delivery.page('decisions')['items'][0]['decision']['snapshot'])
        self.assertEqual(f.pipeline.values,before)
        with self.assertRaises(ValueError):f.delivery.page('deliveries','NE|outside')

    def test_admin_rejection_does_not_create_an_infinite_incident_loop(self):
        f=DeliveryFixture();_,jid=f.ready()
        f.staff.results=[TelegramDeliveryResult('unknown',detail='outcome_unknown')]
        f.admin.results=[TelegramDeliveryResult('unknown',detail='outcome_unknown')]
        for _ in range(5):f.delivery.run()
        self.assertEqual(len(f.staff.calls),1)
        self.assertEqual(len(f.admin.calls),1)
        self.assertEqual(len(f.delivery.page('exceptions')['items']),1)

    def test_protected_routes_are_read_only_and_never_expose_delivery_execution(self):
        f=DeliveryFixture();f.ready();f.delivery.run()
        client=TestClient(create_app(message_record_service=f.records,message_notification_preparation_service=f.planner,
            message_delivery_service=f.delivery,admin_access_service=AdminAccessVerifier(AdminAccessSettings('local-test-password'))))
        base='/internal/v1/message-records/notifications'
        self.assertEqual(client.get(base).status_code,403)
        token=client.post('/internal/v1/admin/access',json={'password':'local-test-password'}).json()['token']
        headers={'X-Alert-Admin-Token':token}
        before=copy.deepcopy(f.pipeline.values)
        for path in ('','/status','?kind=decisions','?kind=exceptions'):
            result=client.get(base+path,headers=headers)
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.headers['cache-control'],'private, no-store')
        self.assertEqual(f.pipeline.values,before)
        self.assertEqual(client.post(base+'/send',headers=headers).status_code,404)
        self.assertEqual(client.post(base+'/control',headers=headers,json={'action':'pause','expected_generation':None}).status_code,409)
        self.assertEqual(client.post(base+'/control',headers=headers,json={'action':'pause','expected_generation':f.delivery.status()['generation']}).status_code,200)
        self.assertEqual(len(f.staff.calls),1)

    def test_manual_reconsideration_can_only_rearm_a_fresh_never_attempted_source(self):
        f=DeliveryFixture();record,jid=f.ready()
        f.planner.prepare_record(record['id'])
        record=f.records.save_note(record['id'],SaveRecordNote(expected_version=record['version'],note='시설 근거 확인',review_state='needs_confirmation'))
        f.planner.prepare_record(record['id'])
        self.assertEqual(f.repo.get(jid)['state'],'invalidated')
        result=f.delivery.reconsider(record['id'],record['version'],f.delivery.status()['generation'])
        self.assertFalse(result['sent'])
        f.planner.prepare_record(record['id'])
        f.delivery.run()
        self.assertEqual(len(f.staff.calls),1)
        with self.assertRaises(RecordConflict):f.delivery.reconsider(record['id'],record['version'],f.delivery.status()['generation'])
        self.assertEqual(f.records.get(record['id'])['review_state'],'needs_confirmation')

    def test_reconsideration_does_not_allow_old_sources_manual_examples_or_unknown_attempts(self):
        for scenario in ('old','manual','unknown'):
            with self.subTest(scenario=scenario):
                f=DeliveryFixture();record,jid=f.ready()
                if scenario=='old':
                    current=f.delivery.status();f.clock[0]+=dt.timedelta(minutes=1)
                    f.delivery.configure('start',current['generation'])
                elif scenario=='manual':
                    # The server's origin check is independent of caller-provided identifiers.
                    f.records.store.records[record['id']]['origin']='manual'
                else:
                    f.staff.results=[TelegramDeliveryResult('unknown',detail='outcome_unknown')]
                    f.delivery.run()
                with self.assertRaises(RecordConflict):f.delivery.reconsider(record['id'],record['version'],f.delivery.status()['generation'])

    def test_new_exception_after_activation_can_trigger_one_summary_without_promoting_old_exceptions(self):
        f=DeliveryFixture(start=False);f.planner.fallback_enabled=True;f.planner.failure_check=lambda record:'ai_daily_limit'
        old=f.register('old',message={**f.message,'text':'대구 전역에 폭염이 예상됩니다. 건강관리에 유의하세요.'})
        f.planner.prepare_record(old['id'])
        f.clock[0]+=dt.timedelta(minutes=1)
        f.delivery.configure('start',None);f.delivery.run()
        self.assertEqual(f.admin.calls,[])
        new=f.register('new',message={**f.message,'text':'부산 전역에 폭염이 예상됩니다. 건강관리에 유의하세요.','issued_at':stamp(f.clock[0])})
        f.planner.prepare_record(new['id']);f.delivery.run();f.delivery.run()
        self.assertEqual(len(f.admin.calls),1)
        self.assertIn('2건',f.admin.calls[0])
        self.assertEqual(f.staff.calls,[])

    def test_worker_processes_delivery_before_daily_analysis_limit_and_exposes_no_dispatch_route(self):
        f=DeliveryFixture();record,jid=f.ready()
        f.pipeline.values['usage-'+NOW.date().isoformat()]={'attempts':20}
        settings=MessageAutomationSettings(enabled=True,contract_verified=True,notification_preparation_enabled=True,delivery_enabled=True)
        runtime=MessageRuntime(f.analyzer,f.records,Mock(configured=True),Mock(),lambda:f.pipeline,settings,f.planner,f.delivery)
        client=TestClient(worker_app(runtime))
        result=client.post('/internal/v1/analyze-next')
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['state'],'daily_limit')
        self.assertEqual(result.json()['notification_delivery']['sent'],1)
        self.assertEqual(f.analyzer.analyze.call_count,1)
        self.assertEqual(client.post('/internal/v1/dispatch').status_code,404)

    def test_firestore_claim_commits_all_reads_before_writes_and_aborted_claim_cannot_send(self):
        f,client=notification_store_tests.NotificationStoreTests().firestore_fixture()
        f.planner.delivery_tracking_enabled=True
        staff,admin=Sender(),Sender()
        service=MessageDelivery(f.planner,{'staff_group':staff,'admin_group':admin},enabled=True,binding='fake',revision='fake',now=lambda:f.clock[0])
        f.clock[0]=NOW-dt.timedelta(minutes=6);service.configure('start',None);f.clock[0]=NOW
        record=f.analyzed();jid=f.planner.prepare_record(record['id'])['job_id']
        service.consider_staff(jid)
        client.fail_delivery_claim_once=True
        with self.assertRaises(RuntimeError):service.run()
        self.assertEqual(staff.calls,[])
        self.assertEqual(f.repo.get(delivery_key(jid))['state'],'pending')
        before=len(client.operations)
        claimed=service._claim(delivery_key(jid))
        ops=client.operations[before:]
        last_commit=next(i for i,op in enumerate(ops) if op[0]=='commit')
        first_set=next(i for i,op in enumerate(ops) if op[0]=='set')
        self.assertFalse(any(op[0]=='get' for op in ops[first_set:last_commit]))
        self.assertEqual(staff.calls,[])
        service._finish(claimed,'sent','receipt_confirmed',message_id=77)
        self.assertEqual(service.page('deliveries')['items'][0]['message_id'],77)
        self.assertFalse(any(key.startswith('alert_') for key in client.documents))

    def test_stale_worker_is_visible_without_claiming_delivery_is_healthy(self):
        f=DeliveryFixture();f.clock[0]+=dt.timedelta(minutes=4)
        self.assertTrue(f.delivery.status()['worker_stale'])
        f.delivery.run()
        self.assertFalse(f.delivery.status()['worker_stale'])
        f.service(binding='wrong-worker-binding').run()
        self.assertTrue(f.delivery.status()['worker_stale'])

    def test_admin_exception_is_not_held_behind_a_full_staff_batch(self):
        f=DeliveryFixture()
        for i in range(21):
            _,jid=f.ready('queued-'+str(i));f.delivery.consider_staff(jid)
        f.planner.fallback_enabled=True;f.planner.failure_check=lambda record:'ai_daily_limit'
        record=f.register('admin-exception',message={**f.message,'text':'대구 전역에 폭염이 예상됩니다. 건강관리에 유의하세요.'})
        f.planner.prepare_record(record['id']);f.delivery.run()
        self.assertEqual(len(f.staff.calls),1)
        self.assertEqual(len(f.admin.calls),1)
