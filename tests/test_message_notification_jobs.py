import copy
from dataclasses import replace
import datetime as dt
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from safety_dashboard.admin.access import AdminAccessSettings, AdminAccessVerifier
from safety_dashboard.api.app import create_app
from safety_dashboard.application.message_automation import MessageAutomationSettings
from safety_dashboard.application.message_notification_jobs import (
    MessageNotificationPreparation, MemoryNotificationStore, CONFIG_KEY, head_key, job_key, source_key,
)
from safety_dashboard.application.message_pipeline import MemoryPipelineStore, MessageAnalysisQueue, stamp
from safety_dashboard.application.message_records import AnalyzeRecord, MemoryRecordStore, MessageRecordService, SaveRecordNote
from safety_dashboard.application.message_runtime import MessageRuntime, build_message_runtime
from safety_dashboard.operations.message_worker import create_app as worker_app
from tests.test_message_notification import point_case, NOW, ISSUED, CATALOG, DIGEST


class Fixture:
    def __init__(self, *, enabled=True, repository=None):
        template, _ = point_case()
        self.template = template
        self.message = template["message"]
        self.clock = [NOW-dt.timedelta(minutes=10)]
        self.analyzer = Mock()
        self.analyzer.analyze.side_effect = lambda req: {**copy.deepcopy(self.template["analysis"]), "input": req.model_dump(mode="json")}
        self.records = MessageRecordService(lambda: MemoryRecordStore(), self.analyzer, storage_mode="memory",
            facility_digest=lambda:DIGEST, now=lambda:self.clock[0])
        self.pipeline = MemoryPipelineStore()
        self.repo = repository or MemoryNotificationStore(self.records.store, self.pipeline)
        self.planner = self.new_planner(enabled=enabled)
        if enabled:
            self.planner.activate()
        self.clock[0] = NOW

    def new_planner(self, **kwargs):
        return MessageNotificationPreparation(self.records, lambda:self.repo, lambda:(DIGEST,CATALOG),
            enabled=kwargs.pop("enabled", True), now=lambda:self.clock[0], base_url="https://example.test", **kwargs)

    def register(self, identifier="SN-stage2", *, message=None):
        return self.records.register_official(message or self.message, identifier, self.clock[0].isoformat())["record"]

    def analyzed(self, identifier="SN-stage2"):
        record = self.register(identifier)
        return self.records.analyze(record["id"], AnalyzeRecord(expected_version=record["version"]))

    def jobs(self):
        return [v for k,v in self.pipeline.values.items() if k.startswith("notification-job-")]


class NotificationJobTests(unittest.TestCase):
    def test_restart_and_repeated_preparation_keep_one_source_job_and_do_not_change_human_history(self):
        f=Fixture();record=f.analyzed();history=f.records.store.history(record["id"],None,100)
        first=f.planner.prepare_record(record["id"])
        snapshot=copy.deepcopy(f.repo.get(first["decision_id"]))
        again=f.new_planner().prepare_record(record["id"])
        self.assertEqual(first["job_id"],again["job_id"])
        self.assertFalse(again["first_evaluation"])
        self.assertEqual(len(f.jobs()),1)
        self.assertEqual(f.analyzer.analyze.call_count,1)
        self.assertEqual(f.records.get(record["id"])["version"],record["version"])
        self.assertEqual(f.records.get(record["id"])["review_state"],"unreviewed")
        self.assertEqual(f.records.store.history(record["id"],None,100),history)
        self.assertFalse(f.records.get(record["id"])["notification_dirty"])
        self.assertEqual(f.repo.get(first["decision_id"]),snapshot)
        self.assertFalse(f.jobs()[0]["dispatch_enabled"])

    def test_analysis_not_finished_is_provisional_and_can_finalize_afterwards(self):
        f=Fixture();record=f.register()
        provisional=f.planner.prepare_record(record["id"])
        self.assertIsNone(provisional["job_id"])
        self.assertFalse(f.repo.get(source_key(record))["finalized"])
        done=f.records.analyze(record["id"],AnalyzeRecord(expected_version=record["version"]))
        ready=f.planner.prepare_record(done["id"])
        self.assertEqual(ready["state"],"pending")
        self.assertTrue(ready["first_finalization"])
        self.assertEqual(len(f.jobs()),1)

    def test_failure_before_atomic_commit_leaves_dirty_for_free_recovery(self):
        f=Fixture();record=f.analyzed();original=f.repo.run_record
        with patch.object(f.repo,"run_record",side_effect=RuntimeError("simulated interruption")):
            with self.assertRaises(RuntimeError):f.planner.prepare_record(record["id"])
        self.assertTrue(f.records.get(record["id"])["notification_dirty"])
        self.assertEqual(f.jobs(),[])
        f.new_planner().run()
        self.assertEqual(len(f.jobs()),1)
        self.assertEqual(f.analyzer.analyze.call_count,1)

    def test_response_lost_after_commit_does_not_create_a_second_job(self):
        f=Fixture();record=f.analyzed();original=f.repo.run_record
        def lost(*args,**kwargs):
            original(*args,**kwargs)
            raise RuntimeError("simulated lost acknowledgement")
        with patch.object(f.repo,"run_record",side_effect=lost):
            with self.assertRaises(RuntimeError):f.planner.prepare_record(record["id"])
        self.assertFalse(f.records.get(record["id"])["notification_dirty"])
        f.new_planner().run()
        self.assertEqual(len(f.jobs()),1)
        self.assertEqual(f.analyzer.analyze.call_count,1)
        self.assertEqual(f.jobs()[0]["state"],"pending")

    def test_two_instances_concurrently_finalize_only_once(self):
        f=Fixture();record=f.analyzed();barrier=threading.Barrier(2);results=[];errors=[]
        def work():
            try:
                barrier.wait();results.append(f.new_planner().prepare_record(record["id"]))
            except Exception as error:errors.append(error)
        threads=[threading.Thread(target=work) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(5)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors,[])
        self.assertEqual(len(results),2)
        self.assertEqual(len(f.jobs()),1)
        self.assertEqual(sum(r["first_finalization"] for r in results),1)

    def test_new_source_invalidates_old_pending_and_new_analysis_gets_new_version_job(self):
        f=Fixture();old=f.analyzed();first=f.planner.prepare_record(old["id"])
        f.clock[0]+=dt.timedelta(minutes=1)
        corrected=f.records.register_official({**f.message,"text":f.message["text"]+" 통제 구간 안내를 정정합니다."},"SN-stage2",f.clock[0].isoformat())["record"]
        self.assertEqual(f.planner.validate_pending(first["job_id"])["state"],"invalidated")
        provisional=f.planner.prepare_record(corrected["id"])
        self.assertIsNone(provisional["job_id"])
        corrected=f.records.analyze(corrected["id"],AnalyzeRecord(expected_version=corrected["version"]))
        newest=f.planner.prepare_record(corrected["id"])
        self.assertEqual(newest["state"],"pending")
        self.assertNotEqual(first["job_id"],newest["job_id"])
        self.assertEqual(len(f.jobs()),2)
        self.assertEqual(sum(j["state"]=="pending" for j in f.jobs()),1)

    def test_reanalysis_invalidates_pending_but_cannot_auto_rearm_same_source(self):
        f=Fixture();record=f.analyzed();first=f.planner.prepare_record(record["id"])
        record=f.records.analyze(record["id"],AnalyzeRecord(expected_version=record["version"]))
        latest=f.planner.prepare_record(record["id"])
        self.assertEqual(latest["job_id"],first["job_id"])
        self.assertEqual(latest["state"],"invalidated")
        self.assertNotEqual(latest["decision_id"],first["decision_id"])
        self.assertEqual(len(f.jobs()),1)

    def test_policy_catalog_or_manual_edit_invalidates_without_paid_reanalysis(self):
        for change in ("policy","catalog","note"):
            with self.subTest(change=change):
                f=Fixture();record=f.analyzed();first=f.planner.prepare_record(record["id"])
                if change=="policy":planner=f.new_planner(policy_version="future-test-policy")
                else:
                    planner=f.new_planner()
                    if change=="catalog":planner.catalog=lambda:("b"*64,CATALOG)
                    else:f.records.save_note(record["id"],SaveRecordNote(expected_version=record["version"],note="수동 확인 대기",review_state="needs_confirmation"))
                self.assertEqual(planner.validate_pending(first["job_id"])["state"],"invalidated")
                planner.prepare_record(record["id"])
                self.assertEqual(len(f.jobs()),1)
                self.assertEqual(f.jobs()[0]["state"],"invalidated")
                self.assertEqual(f.analyzer.analyze.call_count,1)

    def test_activation_is_persistent_and_preexisting_issued_messages_do_not_backfill(self):
        f=Fixture();config=f.repo.get(CONFIG_KEY)
        old=f.analyzed("OLD")
        old_message={**f.message,"issued_at":(NOW-dt.timedelta(hours=2)).isoformat()}
        historical=f.register("HISTORY",message=old_message)
        historical=f.records.analyze(historical["id"],AnalyzeRecord(expected_version=historical["version"]))
        result=f.planner.prepare_record(historical["id"])
        self.assertEqual(result["state"],"before_activation")
        self.assertIsNone(result["job_id"])
        f.clock[0]+=dt.timedelta(days=1)
        self.assertEqual(f.new_planner().activate(),config)
        self.assertIsNone(f.new_planner().prepare_record(historical["id"])["job_id"])

    def test_no_rearm_after_sent_unknown_or_already_invalidated_state(self):
        for state in ("sent","unknown","invalidated"):
            with self.subTest(state=state):
                f=Fixture();record=f.analyzed();first=f.planner.prepare_record(record["id"])
                f.pipeline.values[first["job_id"]]["state"]=state
                record=f.records.analyze(record["id"],AnalyzeRecord(expected_version=record["version"]))
                self.assertEqual(f.planner.prepare_record(record["id"])["state"],state)
                self.assertEqual(len(f.jobs()),1)

    def test_scheduled_validation_invalidates_expired_message_without_new_record_changes(self):
        f=Fixture();record=f.analyzed();first=f.planner.prepare_record(record["id"])
        f.clock[0]+=dt.timedelta(hours=25)
        self.assertEqual(f.planner.run()["checked_pending"],1)
        self.assertEqual(f.repo.get(first["job_id"])["state"],"invalidated")
        self.assertEqual(f.analyzer.analyze.call_count,1)

    def test_observation_metadata_survives_ack_and_does_not_recreate_jobs(self):
        f=Fixture();record=f.analyzed();f.planner.prepare_record(record["id"])
        fetched=(NOW+dt.timedelta(minutes=4)).isoformat()
        observed=f.records.register_official(f.message,"SN-stage2",fetched)["record"]
        self.assertFalse(observed["notification_dirty"])
        self.assertEqual(observed["version"],record["version"])
        f.planner.prepare_record(record["id"])
        self.assertEqual(f.records.get(record["id"])["official_fetched_at"],fetched)
        self.assertEqual(len(f.jobs()),1)

    def test_preparation_can_run_when_ai_daily_limit_is_exhausted_and_without_feed_key(self):
        for configured in (False,True):
            with self.subTest(feed_configured=configured):
                f=Fixture();record=f.analyzed()
                settings=MessageAutomationSettings(enabled=True,contract_verified=True,notification_preparation_enabled=True)
                day=NOW.date().isoformat();f.pipeline.values['usage-'+day]={'day':day,'attempts':20}
                runtime=MessageRuntime(f.analyzer,f.records,Mock(configured=configured),Mock(),lambda:f.pipeline,settings,f.planner)
                client=TestClient(worker_app(runtime))
                result=client.post('/internal/v1/analyze-next')
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(len(f.jobs()),1)
                self.assertEqual(f.analyzer.analyze.call_count,1)
                self.assertEqual(result.json()['notification_preparation']['state'],'preview')
                self.assertEqual(result.json()['state'],'daily_limit' if configured else 'disabled')
                self.assertEqual(client.post('/internal/v1/dispatch').status_code,404)

    def test_worker_prepares_newly_analyzed_record_in_same_run(self):
        f=Fixture();record=f.register();MessageAnalysisQueue(f.pipeline).enqueue(record,NOW)
        settings=MessageAutomationSettings(enabled=True,contract_verified=True,notification_preparation_enabled=True)
        runtime=MessageRuntime(f.analyzer,f.records,Mock(configured=True),Mock(),lambda:f.pipeline,settings,f.planner)
        response=TestClient(worker_app(runtime)).post('/internal/v1/analyze-next')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['state'],'analyzed')
        self.assertEqual(len(f.jobs()),1)

    def test_completed_uncertain_source_requires_reconsideration_instead_of_silent_auto_rearm(self):
        f=Fixture()
        f.template['analysis']['analysis']['notification_assessment'].update(need='uncertain',relevance='unknown',urgency='unknown')
        record=f.analyzed();first=f.planner.prepare_record(record['id'])
        self.assertEqual(first['state'],'attention_required')
        self.assertIsNone(first['job_id'])
        f.template['analysis']['analysis']['notification_assessment'].update(need='notify',relevance='nearby',urgency='immediate')
        record=f.records.analyze(record['id'],AnalyzeRecord(expected_version=record['version']))
        again=f.planner.prepare_record(record['id'])
        self.assertEqual(again['state'],'reconsideration_required')
        self.assertEqual(f.planner.read_record(record['id'])['state'],'reconsideration_required')
        self.assertEqual(f.jobs(),[])

    def test_semantic_edit_between_preview_and_commit_is_preserved_and_invalidates_pending(self):
        f=Fixture();record=f.analyzed();first=f.planner.prepare_record(record['id'])
        original=f.repo.run_record;called=[]
        def concurrent_edit(*args,**kwargs):
            if not called:
                called.append(True)
                f.records.save_note(record['id'],SaveRecordNote(expected_version=record['version'],
                    note='동시 수정된 확인 메모',review_state='needs_confirmation'))
            return original(*args,**kwargs)
        with patch.object(f.repo,'run_record',side_effect=concurrent_edit):
            result=f.planner.prepare_record(record['id'])
        self.assertEqual(result['state'],'invalidated')
        current=f.records.get(record['id'])
        self.assertEqual(current['note'],'동시 수정된 확인 메모')
        self.assertEqual(current['version'],record['version']+1)
        self.assertEqual(len(f.jobs()),1)
        self.assertEqual(f.repo.get(first['job_id'])['state'],'invalidated')

    def test_worker_failure_after_paid_analysis_is_recovered_even_when_budget_is_exhausted(self):
        f=Fixture();record=f.register();MessageAnalysisQueue(f.pipeline).enqueue(record,NOW)
        original=f.repo.run_record;failed=[]
        def interruption(*args,**kwargs):
            if f.analyzer.analyze.call_count and not failed:
                failed.append(True)
                raise RuntimeError('simulated interruption after analysis commit')
            return original(*args,**kwargs)
        settings=MessageAutomationSettings(enabled=True,contract_verified=True,notification_preparation_enabled=True)
        runtime=MessageRuntime(f.analyzer,f.records,Mock(configured=True),Mock(),lambda:f.pipeline,settings,f.planner)
        client=TestClient(worker_app(runtime))
        with patch.object(f.repo,'run_record',side_effect=interruption):
            self.assertEqual(client.post('/internal/v1/analyze-next').status_code,503)
        self.assertEqual(f.records.get(record['id'])['analysis_state'],'completed')
        self.assertTrue(f.records.get(record['id'])['notification_dirty'])
        day=NOW.date().isoformat();f.pipeline.values['usage-'+day]={'day':day,'attempts':20}
        response=client.post('/internal/v1/analyze-next')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['state'],'daily_limit')
        self.assertEqual(f.analyzer.analyze.call_count,1)
        self.assertEqual(len(f.jobs()),1)
        self.assertFalse(f.records.get(record['id'])['notification_dirty'])

    def test_disabled_feature_never_initializes_notification_storage(self):
        records=Mock();factory=Mock(side_effect=AssertionError('must stay lazy'));catalog=Mock()
        planner=MessageNotificationPreparation(records,factory,catalog)
        self.assertEqual(planner.run(),{'state':'disabled'})
        self.assertEqual(planner.read_record('id')['state'],'disabled')
        factory.assert_not_called();catalog.assert_not_called()
        path=Path(__file__).resolve().parents[1]/'facilities_info.csv'
        with patch.dict('os.environ',{},clear=True):
            runtime=build_message_runtime(path,'','memory','')
            self.assertFalse(runtime.settings.notification_preparation_enabled)
            self.assertEqual(runtime.notification_preparation.run(),{'state':'disabled'})

    def test_stored_status_endpoint_is_authenticated_and_read_only(self):
        f=Fixture();record=f.analyzed();f.planner.prepare_record(record['id'])
        app=create_app(message_record_service=f.records,message_notification_preparation_service=f.planner,
            admin_access_service=AdminAccessVerifier(AdminAccessSettings('local-test-password')))
        client=TestClient(app);path=f"/internal/v1/message-records/{record['id']}/notification-preparation?expected_version={record['version']}"
        self.assertEqual(client.get(path).status_code,403)
        token=client.post('/internal/v1/admin/access',json={'password':'local-test-password'}).json()['token']
        before=copy.deepcopy(f.pipeline.values);current=f.records.get(record['id'])
        response=client.get(path,headers={'X-Alert-Admin-Token':token})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['state'],'pending')
        self.assertFalse(response.json()['dispatch_enabled'])
        self.assertEqual(response.headers['cache-control'],'private, no-store')
        self.assertEqual(f.pipeline.values,before)
        self.assertEqual(f.records.get(record['id']),current)
        self.assertEqual(f.analyzer.analyze.call_count,1)
