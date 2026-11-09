from dataclasses import replace
import datetime as dt
import unittest

from safety_dashboard.application.context_info import KST
from safety_dashboard.application.message_automation import MessageAutomationSettings, MessageAutomationStatus
from safety_dashboard.application.message_collection_latest import LatestFirstMessageCollector
from safety_dashboard.application.message_collection import OfficialMessageCollector
from safety_dashboard.application.message_feed_budget import OfficialRequestBudget, FeedRequestLimit
from safety_dashboard.application.message_pipeline import MemoryPipelineStore, stamp
from safety_dashboard.domain.models import DisasterMessage
from tests.test_message_records import make_service

NOW = dt.datetime(2026,11,9,10,0,tzinfo=KST)


class Feed:
    configured=True
    def __init__(self,budget):
        self.budget=budget;self.calls=[]
        self.result=lambda day,page:{"messages":[],"has_more":False,"skipped":0}
    def fetch_page(self,region,day,page,size,*,priority="normal"):
        self.budget.reserve(priority=priority)
        self.calls.append((day,page,priority))
        return self.result(day,page)


class LatestCollectionTests(unittest.TestCase):
    def setUp(self):
        self.clock=[NOW]
        self.store=MemoryPipelineStore();self.records=make_service();self.records.now=lambda:self.clock[0]
        self.budget=OfficialRequestBudget(self.store,latest_reserve=289,now=lambda:self.clock[0])
        self.feed=Feed(self.budget)
        self.settings=MessageAutomationSettings(enabled=True,contract_verified=True,latest_first_enabled=True,interval_seconds=300,start_at=NOW-dt.timedelta(minutes=1))

    def collect(self):
        return LatestFirstMessageCollector(self.feed,self.records,self.store,self.settings,now=lambda:self.clock[0]).run()

    def row(self,identifier="SN-new",**overrides):
        return DisasterMessage(**{"id":identifier,"created_at":self.clock[0],"emergency_step":"안전안내",
            "disaster_type":"교통", "content":"대구 달서구에서 차량 사고로 도로를 통제합니다.","regions":("대구광역시",),**overrides})

    def test_today_head_precedes_busy_legacy_partition_and_keeps_original_start(self):
        start=NOW-dt.timedelta(hours=1)
        self.store.values["collection-state"]={"start_at":stamp(start),"work":[{"region":None,"date":"2026-11-08","page":18,"offset":0,"head_hash":"legacy"}]}
        self.collect()
        self.assertEqual(self.feed.calls[0],(NOW.date(),1,"latest"))
        self.assertIn((dt.date(2026,11,8),18,"background"),self.feed.calls)
        self.assertEqual(self.store.get("collection-state")["start_at"],stamp(start))

    def test_five_minute_buckets_and_hourly_history_do_not_repeat_from_scheduler_jitter(self):
        self.collect();backfill=self.store.get("collection-state")["last_backfill_success_at"]
        self.clock[0]+=dt.timedelta(seconds=2);self.collect()
        self.assertEqual(len(self.feed.calls),2)
        self.clock[0]+=dt.timedelta(minutes=5);self.collect()
        self.assertEqual(len(self.feed.calls),3)
        self.assertEqual(self.store.get("collection-state")["last_backfill_success_at"],backfill)
        self.clock[0]=NOW+dt.timedelta(hours=1);self.collect()
        self.assertEqual(len(self.feed.calls),5)

    def test_one_page_today_and_yesterday_are_312_requests_per_24_hours(self):
        self.clock[0]=NOW.replace(hour=0)
        self.settings=replace(self.settings,start_at=self.clock[0])
        for _ in range(288):
            self.collect();self.clock[0]+=dt.timedelta(minutes=5)
        self.assertEqual(len(self.feed.calls),312)
        self.assertEqual(sum(p=="latest" for _,_,p in self.feed.calls),288)
        self.assertEqual(sum(p=="background" for _,_,p in self.feed.calls),24)

    def test_background_limit_leaves_latest_reserve_and_all_calls_share_450(self):
        for _ in range(161):self.budget.reserve()
        with self.assertRaises(FeedRequestLimit):self.budget.reserve(priority="background")
        self.assertEqual(self.collect()["state"],"request_limit")
        self.assertEqual(self.feed.calls,[(NOW.date(),1,"latest")])
        self.assertTrue(self.store.get("collection-state")["work"])
        for _ in range(288):self.budget.reserve(priority="latest")
        with self.assertRaises(FeedRequestLimit):self.budget.reserve(priority="latest")
        self.assertEqual(self.budget.status()["used"],450)

    def test_migrated_unclassified_calls_count_as_background_and_rolling_quota_crosses_midnight(self):
        old=stamp(NOW-dt.timedelta(hours=1))
        self.store.values[self.budget.KEY]={"starts":[old]*161}
        with self.assertRaises(FeedRequestLimit):self.budget.reserve()
        self.budget.reserve(priority="latest")
        self.clock[0]=NOW+dt.timedelta(hours=15)
        self.assertEqual(self.budget.status()["used"],162)
        self.assertEqual(self.budget.status()["background_remaining"],0)
        self.clock[0]=NOW+dt.timedelta(hours=23)
        self.budget.reserve(priority="background")

    def test_midnight_always_reads_new_day_before_yesterdays_tail(self):
        self.clock[0]=NOW.replace(hour=23,minute=59)
        self.settings=replace(self.settings,max_pages=1)
        self.feed.result=lambda day,page:{"messages":[],"has_more":True,"skipped":0}
        self.collect();self.clock[0]+=dt.timedelta(minutes=2);self.collect()
        self.assertEqual(self.feed.calls[-1],(dt.date(2026,11,10),1,"latest"))
        self.assertTrue(any(p["date"]=="2026-11-09" for p in self.store.get("collection-state")["work"]))

    def test_unchanged_full_head_does_not_rescan_tail_each_five_minutes(self):
        row=self.row()
        self.feed.result=lambda day,page:{"messages":[row] if day==NOW.date() and page==1 else [],"has_more":day==NOW.date() and page==1,"skipped":0}
        for _ in range(3):self.collect()  # page 2 and page-1 verification finish within one run
        tail_calls=sum(page==2 for _,page,_ in self.feed.calls)
        self.clock[0]+=dt.timedelta(minutes=5);self.collect()
        self.assertEqual(sum(page==2 for _,page,_ in self.feed.calls),tail_calls)
        self.assertEqual(tail_calls,1)

    def test_changed_page_one_after_tail_walk_restarts_and_repairs_source_correction(self):
        original=self.row(content="대구 달서구의 도로를 통제합니다. 다른 도로로 우회하세요.")
        revised=self.row(content="대구 달서구의 통제 구간을 정정합니다. 다른 도로로 우회하세요.")
        self.settings=replace(self.settings,max_pages=1)
        self.feed.result=lambda day,page:{"messages":[original] if day==NOW.date() and page==1 else [],"has_more":day==NOW.date() and page==1,"skipped":0}
        self.collect()
        self.clock[0]+=dt.timedelta(minutes=5)
        self.feed.result=lambda day,page:{"messages":[revised] if day==NOW.date() and page==1 else [],"has_more":day==NOW.date() and page==1,"skipped":0}
        self.collect()
        record=self.records.get(self.records.official_record_id(original.id))
        self.assertEqual(record["source_revision"],2)
        self.assertEqual(record["message"]["text"],revised.content)
        self.assertEqual(self.records.list_page()["records"].__len__(),1)

    def test_invalid_date_is_not_hidden_by_prestart_filter_and_unknown_history_is_ignored(self):
        rows=[self.row("wrong-date",created_at=NOW-dt.timedelta(days=1)),
              self.row("old-unknown",created_at=NOW-dt.timedelta(minutes=2),regions=("-",))]
        self.feed.result=lambda day,page:{"messages":rows if day==NOW.date() else [],"has_more":False,"skipped":0}
        self.assertEqual(self.collect()["state"],"partial")
        state=self.store.get("collection-state")
        self.assertEqual(state["cycle_skipped_reasons"],{"query_date":1})
        self.assertEqual(state["cycle_ignored_before_start"],1)

    def test_tail_validation_errors_survive_later_clean_head_checks(self):
        self.settings=replace(self.settings,max_pages=3)
        def result(day,page):
            return {"messages":[],"has_more":day==NOW.date() and page<3,"skipped":1 if day==NOW.date() and page==2 else 0}
        self.feed.result=result
        self.collect()
        self.settings=replace(self.settings,max_pages=1)
        self.clock[0]+=dt.timedelta(minutes=5);self.collect()
        self.assertEqual(self.store.get("collection-state")["cycle_skipped_reasons"]["source_fields"],1)
        self.assertIsNone(self.store.get("collection-state").get("last_success_at"))

    def test_provider_failure_consumes_bucket_and_does_not_block_next_latest_head(self):
        def fail(day,page):raise RuntimeError("private-key-in-url")
        self.feed.result=fail
        self.assertEqual(self.collect()["state"],"error")
        self.collect()
        self.assertEqual(sum(p=="latest" for _,_,p in self.feed.calls),1)
        self.clock[0]+=dt.timedelta(minutes=5)
        self.feed.result=lambda day,page:{"messages":[],"has_more":False,"skipped":0}
        self.collect()
        self.assertEqual(self.feed.calls[-2][2],"latest")
        self.assertNotIn("private-key",str(self.store.values))

    def test_status_distinguishes_latest_check_from_unfinished_history(self):
        for _ in range(161):self.budget.reserve()
        self.collect()
        status=MessageAutomationStatus(self.settings,lambda:self.store,True,now=lambda:NOW).read()
        self.assertEqual(status["state"],"partial")
        self.assertEqual(status["last_latest_success_at"],stamp(NOW))
        self.assertIsNone(status["last_success_at"])
        self.assertIn("최신 첫 페이지",status["detail"])

    def test_legacy_skip_counter_is_rechecked_before_migration_marks_complete(self):
        self.store.values['collection-state']={'start_at':stamp(NOW-dt.timedelta(minutes=1)),
            'work':[],'cycle_skipped':1,'cycle_skipped_reasons':{'recipient_region':1}}
        self.assertEqual(self.collect()['state'],'ok')
        self.assertEqual(self.store.get('collection-state')['cycle_skipped'],0)
        self.assertNotIn('legacy_recheck',self.store.get('collection-state'))
        self.assertIn((NOW.date()-dt.timedelta(days=1),1,'background'),self.feed.calls)

    def test_return_to_legacy_mode_keeps_unfinished_latest_page_and_start_boundary(self):
        self.store.values['collection-state']={'start_at':stamp(NOW-dt.timedelta(hours=1)),
            'strategy':'latest_first_v1','work':[],
            'latest_part':{'region':None,'date':NOW.date().isoformat(),'page':1,'offset':0}}
        settings=replace(self.settings,latest_first_enabled=False,interval_seconds=900)
        result=OfficialMessageCollector(self.feed,self.records,self.store,settings,now=lambda:NOW).run()
        self.assertEqual(result['state'],'ok')
        self.assertEqual(self.feed.calls[0][:2],(NOW.date(),1))
        self.assertNotIn('latest_part',self.store.get('collection-state'))
        self.assertEqual(self.store.get('collection-state')['start_at'],stamp(NOW-dt.timedelta(hours=1)))

    def test_page_walk_restarts_when_head_changes_during_verification(self):
        row=self.row();changed=self.row('SN-newer')
        reads=[0]
        def result(day,page):
            if day==NOW.date() and page==1:
                reads[0]+=1
                return {'messages':[row] if reads[0]==1 else [changed,row],'has_more':True,'skipped':0}
            return {'messages':[],'has_more':False,'skipped':0}
        self.feed.result=result
        self.collect()
        for _ in range(3):self.collect()
        self.assertGreaterEqual(reads[0],3)
        self.assertEqual(len(self.records.list_page()['records']),2)
        self.assertEqual(sum(page==2 for day,page,_ in self.feed.calls if day==NOW.date()),2)
