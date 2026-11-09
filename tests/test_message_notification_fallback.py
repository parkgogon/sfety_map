import copy
from dataclasses import replace
import datetime as dt
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from safety_dashboard.application.message_analysis import AnalysisUnavailable
from safety_dashboard.application.message_automation import MessageAutomationSettings
from safety_dashboard.application.message_notification import notification_preview
from safety_dashboard.application.message_notification_fallback import emergency_original_preview
from safety_dashboard.application.message_notification_jobs import job_key
from safety_dashboard.application.message_pipeline import MessageAnalysisQueue, stamp, task_id
from safety_dashboard.application.message_processing import MessageQueueProcessor
from safety_dashboard.application.message_records import AnalyzeRecord
from safety_dashboard.application.message_runtime import MessageRuntime
from safety_dashboard.operations.message_worker import create_app
from tests.test_message_notification import NOW, CATALOG, DIGEST, analyzed_record, assessment
from tests.test_message_notification_jobs import Fixture

TEXT="대구 달서구 시험산 인근에서 산불이 발생했습니다. 인근 주민은 즉시 안전한 곳으로 대피하세요."


class FallbackFixture(Fixture):
    def __init__(self):
        super().__init__()
        self.reason=[None]
        self.message={**self.message,"text":TEXT}
        self.planner=self.new_planner(fallback_enabled=True,failure_check=lambda record:self.reason[0])

    def failed(self):
        record=self.register()
        self.analyzer.analyze.side_effect=AnalysisUnavailable("가짜 분석 실패")
        try:self.records.analyze(record["id"],AnalyzeRecord(expected_version=record["version"]))
        except AnalysisUnavailable:pass
        return self.records.get(record["id"])


class EmergencyFallbackPolicyTests(unittest.TestCase):
    def evaluate(self,text=TEXT,**overrides):
        f=FallbackFixture();record=f.register(message={**f.message,"text":text})
        record.update(overrides)
        base=notification_preview(record,(DIGEST,CATALOG),now=NOW)
        return emergency_original_preview(record,base,"ai_daily_limit",now=NOW,base_url="https://example.test/control/messages?token=private")

    def test_explicit_current_evacuation_uses_whole_original_without_invented_facilities(self):
        result=self.evaluate()
        self.assertEqual(result["decision"],"notify_source_only")
        self.assertIn(TEXT,result["preview_text"])
        self.assertIn("AI 분석 불가",result["preview_text"])
        self.assertEqual(result["facilities"],[])
        self.assertFalse(result["dispatch_enabled"])
        self.assertEqual(result["map_url"],"https://example.test/")
        self.assertNotIn("private",result["preview_text"])

    def test_prevention_training_future_release_negation_quotation_and_false_message_are_rejected(self):
        for text in (
            TEXT+" 재난대피 훈련입니다.",TEXT+" 내일 실시 예정입니다.",TEXT+" 대피 명령을 해제합니다.",
            TEXT+" 현재 대피할 필요가 없습니다.",TEXT+" 이는 오발송입니다.",
            '대구 달서구에 "즉시 대피하세요"라는 문자는 가짜입니다.',
            "대구 전역에 산불 발생 시 즉시 대피하세요.",
            "대구 주민은 위험한 경우 즉시 대피하세요.",
            "대구 시민은 오늘 18시 즉시 대피하세요.",
            "대구 시민은 위험하면 즉시 대피하세요.",
            "대구 시민은 12월 1일부터 즉시 대피하세요.",
            "어제 대구 주민에게 즉시 대피하세요. 라고 안내했습니다.",
            "대구 주민은 즉시 대피하세요?",TEXT+" 위 문구는 예시입니다.",
        ):
            with self.subTest(text=text):self.assertIsNone(self.evaluate(text))

    def test_recipient_issuer_only_or_mixed_outside_region_does_not_establish_site(self):
        for text in ("[대구광역시] 중앙동에서 화재가 발생했습니다. 즉시 대피하세요.",
                     "중앙동에서 화재가 발생했습니다. 즉시 대피하세요.",
                     "대구에 전달된 서울 화재 안내입니다. 즉시 대피하세요."):
            with self.subTest(text=text):self.assertIsNone(self.evaluate(text))

    def test_only_official_fresh_nonrunning_unavailable_analysis_can_fallback(self):
        f=FallbackFixture();record=f.register();base=notification_preview(record,(DIGEST,CATALOG),now=NOW)
        for origin in ("manual","example"):
            self.assertIsNone(emergency_original_preview({**record,"origin":origin},base,"ai_daily_limit",now=NOW))
        for state in ("running","completed"):
            self.assertIsNone(emergency_original_preview({**record,"analysis_state":state},base,"ai_daily_limit",now=NOW))
        for issued in (None,(NOW-dt.timedelta(hours=1,seconds=1)).isoformat(),(NOW+dt.timedelta(minutes=6)).isoformat()):
            old={**record,"message":{**record["message"],"issued_at":issued}}
            self.assertIsNone(emergency_original_preview(old,base,"ai_daily_limit",now=NOW))
        self.assertIsNone(emergency_original_preview(record,base,None,now=NOW))


class EmergencyFallbackPreparationTests(unittest.TestCase):
    def test_normal_waiting_does_not_skip_ai_then_budget_exhaustion_rechecks_clean_watch(self):
        f=FallbackFixture();record=f.register()
        first=f.planner.prepare_record(record["id"])
        self.assertIsNone(first["job_id"])
        self.assertFalse(f.records.get(record["id"])["notification_dirty"])
        f.reason[0]="ai_daily_limit"
        f.planner.run()
        self.assertEqual(len(f.jobs()),1)
        self.assertEqual(f.jobs()[0]["snapshot"]["preparation_kind"],"raw_emergency_fallback")
        self.assertFalse(f.jobs()[0]["dispatch_enabled"])
        self.assertEqual(f.analyzer.analyze.call_count,0)

    def test_real_saved_analysis_failure_can_prepare_fallback_without_model_retry(self):
        f=FallbackFixture();record=f.failed();history=f.records.store.history(record["id"],None,100)
        result=f.planner.prepare_record(record["id"])
        self.assertEqual(result["state"],"pending")
        self.assertEqual(f.jobs()[0]["snapshot"]["fallback_unavailable_reason"],"ai_analysis_failed")
        f.planner.run()
        self.assertEqual(f.analyzer.analyze.call_count,1)
        self.assertEqual(f.records.store.history(record["id"],None,100),history)
        self.assertNotEqual(f.records.get(record["id"])["review_state"],"completed")

    def test_quota_recovery_preserves_pending_fallback_and_blocks_later_automatic_paid_analysis(self):
        f=FallbackFixture();f.reason[0]="ai_spend_limit";record=f.register()
        MessageAnalysisQueue(f.pipeline).enqueue(record,NOW)
        first=f.planner.prepare_record(record["id"])
        f.reason[0]=None
        self.assertEqual(f.planner.validate_pending(first["job_id"])["state"],"pending")
        self.assertEqual(f.planner.prepare_record(record["id"])["job_id"],first["job_id"])
        settings=MessageAutomationSettings(enabled=True,contract_verified=True)
        MessageQueueProcessor(f.records,f.pipeline,settings,now=lambda:NOW,before_analysis=f.planner.auto_analysis_needed).run()
        self.assertEqual(f.pipeline.get(task_id(record))["state"],"deferred")
        self.assertEqual(f.analyzer.analyze.call_count,0)

    def test_concurrent_fallback_commit_and_quota_recovery_cannot_invalidate_the_new_job(self):
        f=FallbackFixture();record=f.register();jid=job_key(record)
        original=f.repo.get;interleaved=[]
        def get(key):
            observed=original(key)
            if key==jid and not interleaved:
                interleaved.append(True)
                f.reason[0]='ai_daily_limit'
                f.new_planner(fallback_enabled=True,failure_check=lambda record:f.reason[0]).prepare_record(record['id'])
                f.reason[0]=None
            return observed
        with patch.object(f.repo,'get',side_effect=get):
            result=f.planner.prepare_record(record['id'])
        self.assertEqual(result['state'],'pending')
        self.assertEqual(len(f.jobs()),1)
        self.assertEqual(f.jobs()[0]['state'],'pending')

    def test_expiry_or_source_correction_invalidates_old_fallback_without_automatic_rearm(self):
        f=FallbackFixture();f.reason[0]="ai_daily_limit";record=f.register()
        first=f.planner.prepare_record(record["id"])
        f.clock[0]+=dt.timedelta(hours=1)
        self.assertEqual(f.planner.validate_pending(first["job_id"])["state"],"invalidated")
        f.planner.prepare_record(record["id"])
        self.assertEqual(len(f.jobs()),1)
        corrected=f.register(message={**f.message,"text":TEXT+" 현장 도로 안내를 추가합니다.","issued_at":stamp(f.clock[0])})
        self.assertNotEqual(job_key(record),job_key(corrected))
        f.planner.prepare_record(corrected["id"])
        self.assertEqual(len(f.jobs()),2)

    def test_completed_uncertain_analysis_is_not_overridden_by_fallback_keywords(self):
        f=FallbackFixture();f.reason[0]="ai_daily_limit"
        f.template,_=analyzed_record(TEXT,assessment(TEXT,need='uncertain',relevance='unknown',urgency='unknown'))
        record=f.analyzed()
        self.assertIsNone(f.planner.prepare_record(record["id"])["job_id"])
        self.assertEqual(f.jobs(),[])

    def test_nonmatching_unavailability_aggregates_admin_incident_once_per_source_and_category(self):
        f=FallbackFixture();f.reason[0]="ai_daily_limit"
        record=f.register(message={**f.message,"text":"대구 전역에 폭염이 예상됩니다. 건강관리에 유의하세요."})
        for _ in range(3):f.planner.prepare_record(record["id"])
        other=f.register("SN-other",message={**f.message,"text":"부산 전역에 폭염이 예상됩니다. 건강관리에 유의하세요."})
        f.planner.prepare_record(other["id"])
        incidents=[v for v in f.pipeline.values.values() if v.get("queue_key","").startswith("NE|")]
        self.assertEqual(len(incidents),1)
        self.assertEqual(incidents[0]["source_count"],2)
        self.assertEqual(incidents[0]["destination"],"admin_group")
        self.assertFalse(incidents[0]["dispatch_enabled"])
        self.assertEqual(f.jobs(),[])

    def test_worker_prepares_fallback_even_when_analysis_limit_blocks_processing(self):
        f=FallbackFixture();f.reason[0]="ai_daily_limit";record=f.register()
        f.pipeline.values['usage-'+NOW.date().isoformat()]={'attempts':20}
        settings=MessageAutomationSettings(enabled=True,contract_verified=True,notification_preparation_enabled=True,emergency_fallback_enabled=True)
        runtime=MessageRuntime(f.analyzer,f.records,Mock(configured=True),Mock(),lambda:f.pipeline,settings,f.planner)
        response=TestClient(create_app(runtime)).post('/internal/v1/analyze-next')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['state'],'daily_limit')
        self.assertEqual(len(f.jobs()),1)
        self.assertEqual(f.analyzer.analyze.call_count,0)

    def test_fallback_disabled_keeps_unavailable_analysis_provisional(self):
        f=FallbackFixture();record=f.failed()
        planner=f.new_planner(fallback_enabled=False,failure_check=Mock(side_effect=AssertionError("must stay off")))
        self.assertIsNone(planner.prepare_record(record["id"])["job_id"])
        self.assertEqual(f.jobs(),[])
