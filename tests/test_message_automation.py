"""Message collection/queue/budget tests use fake providers and durable memory stores."""
import copy
from dataclasses import replace
import datetime as dt
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from safety_dashboard.application.context_info import KST
from safety_dashboard.application.message_analysis import AnalysisBusy, AnalysisUnavailable
from safety_dashboard.application.message_automation import MessageAutomationSettings, MessageAutomationStatus
from safety_dashboard.application.message_collection import OfficialMessageCollector
from safety_dashboard.application.message_feed import PROVINCES, OfficialFeedService, FeedRequest
from safety_dashboard.application.message_pipeline import (
    AnalysisDailyLimit, AnalysisRunGate, MemoryPipelineStore, MessageAnalysisQueue, PipelineLeases, stamp, task_id,
)
from safety_dashboard.application.message_processing import MessageQueueProcessor
from safety_dashboard.application.message_records import AnalyzeRecord, RecordConflict
from safety_dashboard.application.message_runtime import build_message_runtime
from safety_dashboard.domain.models import DisasterMessage
from safety_dashboard.operations.message_worker import create_app
from tests.test_message_analysis import call, draft, part, request, service
from tests.test_message_records import make_service, registration, NOW


SETTINGS = MessageAutomationSettings(enabled=True, contract_verified=True, start_at=NOW-dt.timedelta(minutes=1))


def message(identifier="SN-1", *, when=NOW, text="중앙동 사거리 사고로 도로를 통제합니다. 다른 도로로 우회하세요."):
    return DisasterMessage(identifier, when, "안전안내", "교통", text, ("경상남도 창원시",))


class FakeFeed:
    configured = True

    def __init__(self, pages=None):
        self.pages, self.calls = pages or {}, []

    def fetch_page(self, region, day, page, size):
        self.calls.append((region, day, page, size))
        rows, more, skipped = self.pages.get((region, day, page), self.pages.get((None, day, page), ([], False, 0)))
        return {"messages": rows, "has_more": more, "skipped": skipped}


class PipelineTests(unittest.TestCase):
    def test_shared_budget_is_atomic_across_instances_and_rolls_at_korean_midnight(self):
        store = MemoryPipelineStore()
        now = [dt.datetime(2026, 11, 8, 23, 59, tzinfo=KST)]
        gates = [AnalysisRunGate(store, 1, now=lambda: now[0]) for _ in range(2)]
        barrier, outcomes = threading.Barrier(2), []
        def reserve(index):
            barrier.wait()
            try:
                gates[index].acquire(str(index)); outcomes.append("reserved")
            except AnalysisBusy:
                outcomes.append("busy")
        threads = [threading.Thread(target=reserve, args=(i,)) for i in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertCountEqual(outcomes, ["reserved", "busy"])
        for i in range(2): gates[i].release(str(i))
        with self.assertRaises(AnalysisDailyLimit): gates[1].acquire("next")
        now[0] += dt.timedelta(minutes=1)
        gates[1].acquire("new-day")
        self.assertEqual(gates[1].status()["attempts"], 1)
        self.assertEqual(gates[1].status()["day"], "2026-11-09")

    def test_expired_owner_cannot_release_or_write_over_a_new_owner(self):
        store = MemoryPipelineStore(); leases = PipelineLeases(store)
        self.assertTrue(leases.acquire("lease", "old", NOW))
        self.assertFalse(leases.acquire("lease", "other", NOW))
        later = NOW+dt.timedelta(seconds=301)
        self.assertTrue(leases.acquire("lease", "new", later))
        leases.release("lease", "old")
        with self.assertRaises(RecordConflict): leases.write("lease", "old", later, "state", {"bad": True})
        self.assertTrue(leases.owns("lease", "new", later))
        gate = AnalysisRunGate(store, now=lambda: NOW)
        gate.acquire("old")
        gate.now = lambda: later
        gate.acquire("new")
        gate.release("old")
        self.assertTrue(gate.status()["active"])

    def test_gate_fails_closed_without_echoing_store_error_and_counts_failed_provider(self):
        store = MemoryPipelineStore(); gate = AnalysisRunGate(store, 2, now=lambda: NOW)
        req = request("prevention")
        agent = service([call("submit_analysis", draft([part(req.text, "prevention")]))], gate_factory=lambda: gate)
        agent.client.respond = Mock(side_effect=AnalysisUnavailable("fake failure"))
        with self.assertRaises(AnalysisUnavailable): agent.analyze(req)
        self.assertEqual(gate.status()["attempts"], 1)
        self.assertFalse(gate.status()["active"])
        broken = AnalysisRunGate(Mock(run=Mock(side_effect=RuntimeError("private"))))
        agent = service([], gate_factory=lambda: broken)
        with self.assertRaises(AnalysisUnavailable) as error: agent.analyze(req)
        self.assertNotIn("private", str(error.exception))
        self.assertEqual(agent.client.inputs, [])

    def test_separate_manual_and_worker_agents_share_daily_limit_before_any_model_call(self):
        store = MemoryPipelineStore(); req = request("prevention")
        def agent():
            return service([call("submit_analysis", draft([part(req.text, "prevention")]))],
                           gate_factory=lambda: AnalysisRunGate(store, 1, now=lambda: NOW))
        manual, worker = agent(), agent()
        manual.analyze(req)
        with self.assertRaises(AnalysisDailyLimit): worker.analyze(req)
        self.assertEqual(worker.client.inputs, [])

    def test_queue_duplicate_claim_and_stale_finish_do_not_damage_counts(self):
        store = MemoryPipelineStore(); queue = MessageAnalysisQueue(store)
        record = make_service().register_manual(registration())["record"]
        self.assertTrue(queue.enqueue(record, NOW)); self.assertFalse(queue.enqueue(record, NOW))
        key = task_id(record)
        self.assertEqual(len(queue.due(NOW)), 1)
        self.assertIsNotNone(queue.claim(key, "first", NOW))
        self.assertIsNone(queue.claim(key, "second", NOW))
        self.assertFalse(queue.finish(key, "done", NOW, "bad", owner="second"))
        self.assertEqual(queue.counts()["running"], 1)
        queue.finish(key, "pending", NOW, "retry", owner="first", delay=60)
        self.assertEqual(queue.due(NOW), [])
        queue.claim(key, "second", NOW+dt.timedelta(seconds=61))
        self.assertFalse(queue.finish(key, "done", NOW, "old", owner="first"))
        self.assertEqual(sum(queue.counts().values()), 1)


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryPipelineStore(); self.records = make_service()
        self.provider = FakeFeed({(None, NOW.date(), 1): ([message()], False, 0)})
        self.now = NOW
        self.settings = SETTINGS

    def collect(self, **kwargs):
        return OfficialMessageCollector(self.provider, self.records, self.store, self.settings, now=lambda: self.now, **kwargs).run()

    def test_restarts_overlap_and_manual_import_use_identical_ids_and_do_not_reanalyze(self):
        self.assertEqual(self.collect()["state"], "ok")
        first = self.records.list_page()["records"][0]
        self.now += dt.timedelta(minutes=5)
        self.assertEqual(self.collect()["state"], "ok")
        self.assertEqual(self.records.get(first["id"])["version"], first["version"])
        self.assertEqual(MessageAnalysisQueue(self.store).counts()["pending"], 1)
        feed = OfficialFeedService(self.provider, "fake-signing", now=lambda: self.now)
        page = feed.fetch(FeedRequest(region=PROVINCES[0], date=NOW.date()))
        source, identifier, fetched = feed.verify(page["messages"][0]["import_token"])
        self.assertEqual(self.records.register_official(source, identifier, fetched)["registration"], "unchanged")
        self.assertEqual(len(self.records.store.history(first["id"], None, 100)), 1)

    def test_more_than_three_pages_are_resumed_and_tail_checks_head_without_paid_calls(self):
        for p in range(1, 6):
            self.provider.pages[(None, NOW.date(), p)] = ([message(str(p))], p < 5, 0)
        self.settings = replace(SETTINGS, max_pages=3)
        for _ in range(12):
            result = self.collect()
            if result["state"] == "ok": break
        self.assertEqual(result["state"], "ok")
        self.assertEqual(len(self.records.list_page()["records"]), 5)
        self.assertTrue(any(call[2] == 5 for call in self.provider.calls))
        self.assertEqual(MessageAnalysisQueue(self.store).counts()["pending"], 5)

    def test_changed_page_head_restarts_scan_and_keeps_partial_until_rechecked(self):
        self.settings = replace(SETTINGS, max_pages=1)
        self.store.values["collection-state"] = {"start_at": stamp(SETTINGS.start_at), "cycle_skipped": 0,
            "work": [{"region": None, "date": NOW.date().isoformat(), "page": 1, "offset": 0}]}
        self.provider.pages[(None, NOW.date(), 1)] = ([message("A")], True, 0)
        self.provider.pages[(None, NOW.date(), 2)] = ([message("B")], False, 0)
        self.collect(); self.collect()
        self.provider.pages[(None, NOW.date(), 1)] = ([message("new"), message("A")], True, 0)
        result = self.collect()
        self.assertEqual(result["state"], "partial")
        self.assertFalse(self.store.get("collection-state").get("last_success_at"))
        self.collect()
        self.assertIsNotNone(self.records.store.get(self.records.official_record_id("new")))

    def test_partial_row_resume_and_shifted_page_do_not_skip_new_rows(self):
        state = {"start_at": stamp(SETTINGS.start_at), "cycle_skipped": 0,
                 "work": [{"region": None, "date": NOW.date().isoformat(), "page": 1, "offset": 2, "page_hash": "old-page"}]}
        self.store.values["collection-state"] = state
        self.provider.pages[(None, NOW.date(), 1)] = ([message("new"), message("A"), message("B")], False, 0)
        self.collect()
        self.assertEqual(len(self.records.list_page()["records"]), 3)

    def test_scan_time_limit_persists_row_offset_and_resumes_identical_page(self):
        self.provider.pages[(None, NOW.date(), 1)] = ([message("A"), message("B"), message("C")], False, 0)
        elapsed = [0]
        collector = OfficialMessageCollector(self.provider, self.records, self.store, self.settings, now=lambda: self.now, clock=lambda: elapsed[0])
        real_import = collector._import
        def limited_import(*args):
            real_import(*args)
            elapsed[0] = self.settings.scan_seconds
        collector._import = limited_import
        self.assertEqual(collector.run()["state"], "partial")
        self.assertEqual(self.store.get("collection-state")["work"][0]["offset"], 1)
        collector = OfficialMessageCollector(self.provider, self.records, self.store, self.settings, now=lambda: self.now)
        collector._import = Mock(wraps=collector._import)
        self.assertEqual(collector.run()["state"], "ok")
        self.assertEqual([call.args[1] for call in collector._import.call_args_list], ["B", "C"])
        self.assertEqual(MessageAnalysisQueue(self.store).counts()["pending"], 3)

    def test_yesterday_overlap_collects_late_arrival_with_actual_recipient_regions(self):
        self.settings = replace(SETTINGS, start_at=NOW-dt.timedelta(days=2))
        self.collect()
        late = NOW-dt.timedelta(hours=12)
        self.provider.pages[(None, late.date(), 1)] = ([message("late", when=late)], False, 0)
        self.now += dt.timedelta(minutes=5)
        self.collect()
        saved = self.records.get(self.records.official_record_id("late"))
        self.assertEqual(saved["message"]["recipient_regions"], ["경상남도 창원시"])
        self.assertNotIn(None, saved["message"]["recipient_regions"])

    def test_midnight_has_priority_and_source_correction_retires_old_task(self):
        self.collect(); first = self.records.list_page()["records"][0]
        self.provider.pages[(None, NOW.date(), 1)] = ([message(text="중앙동 사거리 통제가 해제되었습니다. 통행에 참고해 주세요.")], False, 0)
        self.now += dt.timedelta(minutes=1)
        self.collect()
        saved = self.records.get(first["id"])
        self.assertEqual(saved["source_revision"], 2)
        self.assertEqual(MessageAnalysisQueue(self.store).counts()["obsolete"], 1)
        self.assertEqual(MessageAnalysisQueue(self.store).counts()["pending"], 1)
        self.store.values["collection-state"]["work"] = [{"region": None, "date": NOW.date().isoformat(), "page": 4, "offset": 0}]
        self.now += dt.timedelta(days=1)
        self.settings = replace(SETTINGS, max_pages=1)
        self.collect()
        self.assertEqual(self.provider.calls[-1][1:3], (self.now.date(), 1))

    def test_initial_start_does_not_flood_old_history_and_survives_config_changes(self):
        self.provider.pages[(None, NOW.date(), 1)] = ([message("old", when=NOW-dt.timedelta(hours=1)), message()], False, 0)
        self.collect()
        self.assertEqual(len(self.records.list_page()["records"]), 1)
        start = self.store.get("collection-state")["start_at"]
        self.settings = replace(SETTINGS, start_at=NOW-dt.timedelta(days=10))
        self.collect()
        self.assertEqual(self.store.get("collection-state")["start_at"], start)

    def test_unimported_prestart_unknown_recipient_does_not_poison_repeated_overlap(self):
        old=replace(message("old",when=NOW-dt.timedelta(hours=1)),regions=("알수없는지역",))
        self.provider.pages={(None,NOW.date(),1):([old,message()],False,0),
                             (None,(NOW-dt.timedelta(days=1)).date(),1):([old],False,0)}
        for _ in range(2):
            self.assertEqual(self.collect()["state"],"ok")
            state=self.store.get("collection-state")
            self.assertEqual(state["cycle_skipped"],0)
            self.assertEqual(state["cycle_ignored_before_start"],2)
            self.assertTrue(state["last_success_at"])
        self.assertEqual(len(self.records.list_page()["records"]),1)
        self.assertEqual(MessageAnalysisQueue(self.store).counts()["pending"],1)

    def test_current_unknown_recipient_still_blocks_complete_coverage(self):
        self.provider.pages={(None,NOW.date(),1):([replace(message(),regions=("알수없는지역",))],False,0)}
        self.assertEqual(self.collect()["state"],"partial")
        state=self.store.get("collection-state")
        self.assertEqual(state["cycle_skipped_reasons"],{"recipient_region":1})
        self.assertFalse(state.get("last_success_at"))

    def test_known_prestart_record_correction_is_not_filtered_as_unused_history(self):
        old=message("existing",when=NOW-dt.timedelta(hours=1))
        saved=self.records.register_official({**registration().canonical(),"issued_at":old.created_at.isoformat(),"text":old.content},old.id,NOW.isoformat())["record"]
        corrected=replace(old,content="중앙동 도로 통제가 해제되었습니다. 통행에 참고해 주세요.")
        self.provider.pages={(None,NOW.date(),1):([corrected],False,0)}
        self.assertEqual(self.collect()["state"],"ok")
        self.assertEqual(self.records.get(saved["id"])["source_revision"],2)
        unknown=replace(corrected,regions=("알수없는지역",))
        self.provider.pages={(None,NOW.date(),1):([unknown],False,0)}
        self.assertEqual(self.collect()["state"],"partial")
        self.assertEqual(self.store.get("collection-state")["cycle_skipped_reasons"],{"recipient_region":1})

    def test_unparseable_provider_fields_are_never_ignored_as_prestart_history(self):
        self.provider.pages={(None,NOW.date(),1):([],False,1)}
        self.assertEqual(self.collect()["state"],"partial")
        self.assertEqual(self.store.get("collection-state")["cycle_skipped_reasons"],{"source_fields":1})

    def test_prestart_cutoff_does_not_hide_an_api_row_outside_the_requested_date_range(self):
        old=message("outside-date",when=NOW-dt.timedelta(days=3))
        self.provider.pages={(None,NOW.date(),1):([old],False,0)}
        self.assertEqual(self.collect()["state"],"partial")
        state=self.store.get("collection-state")
        self.assertEqual(state["cycle_skipped_reasons"],{"query_date":1})
        self.assertEqual(state["cycle_ignored_before_start"],0)
        self.assertFalse(state.get("last_success_at"))

    def test_outage_during_partial_scan_adds_every_missing_day_before_advancing_success(self):
        self.store.values["collection-state"] = {"start_at": stamp(SETTINGS.start_at), "cycle_skipped": 0,
                "work": [{"region": None, "date": NOW.date().isoformat(), "page": 4, "offset": 0, "head_hash": "previous-cycle-head"}]}
        self.now += dt.timedelta(days=3)
        self.settings = replace(SETTINGS, max_pages=50)
        self.assertEqual(self.collect()["state"], "ok")
        queried = {call[1] for call in self.provider.calls}
        self.assertTrue({NOW.date()+dt.timedelta(days=i) for i in range(4)} <= queried)

    def test_outage_and_invalid_rows_preserve_success_and_never_claim_empty_success(self):
        self.collect(); success = self.store.get("collection-state")["last_success_at"]
        self.provider.fetch_page = Mock(side_effect=RuntimeError("secret-url"))
        self.now += dt.timedelta(minutes=5)
        self.assertEqual(self.collect()["state"], "error")
        self.assertEqual(self.store.get("collection-state")["last_success_at"], success)
        self.assertNotIn("secret", str(self.store.values))
        self.provider = FakeFeed({(None, NOW.date(), 1): ([message("short", text="짧음")], False, 1)})
        self.assertEqual(self.collect()["state"], "partial")
        self.assertEqual(self.store.get("collection-state")["last_success_at"], success)
        self.assertEqual(len(self.records.list_page()["records"]), 1)

    def test_catchup_window_exposes_gap_instead_of_advancing_watermark(self):
        self.settings = replace(SETTINGS, max_pages=50)
        self.store.values["collection-state"] = {"start_at": stamp(NOW-dt.timedelta(days=20)), "last_success_at": stamp(NOW-dt.timedelta(days=10))}
        result = self.collect()
        self.assertEqual(result["state"], "partial")
        self.assertTrue(self.store.get("collection-state")["coverage_gap"])
        self.assertEqual(self.store.get("collection-state")["last_success_at"], stamp(NOW-dt.timedelta(days=10)))
        days = {call[1] for call in self.provider.calls}
        self.assertEqual(min(days), NOW.date()-dt.timedelta(days=6))

    def test_registration_queue_crash_is_repaired_by_reobserving_same_page(self):
        enqueue = MessageAnalysisQueue.enqueue
        with patch.object(MessageAnalysisQueue, "enqueue", side_effect=RuntimeError("crash")):
            self.assertEqual(self.collect()["state"], "error")
        self.assertEqual(len(self.records.list_page()["records"]), 1)
        self.assertEqual(self.store.get("collection-state")["work"][0]["offset"], 0)
        self.collect()
        self.assertEqual(MessageAnalysisQueue(self.store).counts()["pending"], 1)
        self.assertEqual(len(self.records.list_page()["records"]), 1)

    def test_disabled_unverified_and_unconfigured_never_poll(self):
        for settings in (replace(SETTINGS, enabled=False), replace(SETTINGS, contract_verified=False)):
            self.settings = settings
            self.assertEqual(self.collect()["state"], "disabled")
        self.settings = SETTINGS; self.provider.configured = False
        self.assertEqual(self.collect()["state"], "disabled")
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.store.values, {})


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryPipelineStore(); self.queue = MessageAnalysisQueue(self.store)
        self.analyzer = Mock(analyze=Mock(return_value={"analysis": {"summary": "fake"}}))
        self.records = make_service(self.analyzer); self.now = NOW
        self.record = self.records.register_official(registration().canonical(), "SN-1", NOW.isoformat())["record"]
        self.queue.enqueue(self.record, self.now)
        self.processor = MessageQueueProcessor(self.records, self.store, SETTINGS, now=lambda: self.now)

    def test_automatic_success_once_with_saved_result_and_manual_note_preserved(self):
        self.records.store.records[self.record["id"]]["note"] = "담당자가 확인 중"
        self.assertEqual(self.processor.run()["state"], "analyzed")
        self.assertEqual(self.processor.run()["state"], "idle")
        saved = self.records.get(self.record["id"])
        self.assertEqual(saved["analysis_state"], "completed")
        self.assertEqual(saved["analysis_attempt_source_revision"], 1)
        self.assertEqual(saved["note"], "담당자가 확인 중")
        self.analyzer.analyze.assert_called_once()

    def test_provider_failure_is_not_automatically_retried(self):
        self.analyzer.analyze.side_effect = AnalysisUnavailable("fake")
        self.assertEqual(self.processor.run()["state"], "failed")
        self.assertEqual(self.processor.run()["state"], "idle")
        self.analyzer.analyze.assert_called_once()
        self.assertEqual(self.queue.counts()["failed"], 1)
        self.assertEqual(self.records.get(self.record["id"])["analysis_state"], "failed")

    def test_precall_busy_restores_attempt_ledger_then_returns_to_queue(self):
        self.analyzer.analyze.side_effect = AnalysisBusy("busy")
        self.assertEqual(self.processor.run()["state"], "busy")
        saved = self.records.get(self.record["id"])
        self.assertEqual(saved["analysis_state"], "not_analyzed")
        self.assertIsNone(saved["analysis_attempt_source_revision"])
        self.assertEqual(self.queue.counts()["pending"], 1)
        self.now += dt.timedelta(seconds=61); self.records.now = lambda: self.now
        self.analyzer.analyze.side_effect = None
        self.assertEqual(self.processor.run()["state"], "analyzed")

    def test_expired_claim_before_call_is_recoverable_but_after_start_is_not_rebilled(self):
        key = task_id(self.record); self.queue.claim(key, "dead", NOW)
        self.now += dt.timedelta(seconds=301)
        self.assertEqual(self.processor.run()["state"], "analyzed")
        self.setUp()
        self.queue.claim(task_id(self.record), "dead", NOW)
        self.records.store.records[self.record["id"]].update(analysis_state="running", analysis_started_at=NOW.isoformat(),
                analysis_attempt_source_revision=1, analysis_attempted_at=NOW.isoformat(), analysis_operation="dead")
        self.now += dt.timedelta(seconds=301)
        self.assertEqual(self.processor.run()["state"], "idle")
        self.analyzer.analyze.assert_not_called()
        self.assertEqual(self.queue.counts()["failed"], 1)

    def test_saved_result_after_lost_queue_ack_is_recovered_without_call(self):
        self.queue.claim(task_id(self.record), "dead", NOW)
        self.records.analyze(self.record["id"], AnalyzeRecord(expected_version=1))
        self.analyzer.analyze.reset_mock(); self.now += dt.timedelta(seconds=301)
        self.processor.run()
        self.analyzer.analyze.assert_not_called()
        self.assertEqual(self.queue.counts()["done"], 1)

    def test_daily_limit_keeps_pending_without_touching_record_or_retrying(self):
        gate = AnalysisRunGate(self.store, 20, now=lambda: NOW)
        for i in range(20): gate.acquire(str(i)); gate.release(str(i))
        self.assertEqual(self.processor.run()["state"], "daily_limit")
        self.assertEqual(self.queue.counts()["pending"], 1)
        self.assertEqual(self.records.get(self.record["id"])["version"], 1)
        self.analyzer.analyze.assert_not_called()

    def test_stale_source_and_old_backlog_are_preserved_for_manual_review(self):
        self.records.register_official({**self.record["message"], "text": "중앙동 통제가 모두 해제되었습니다. 통행에 참고해 주세요."}, "SN-1", (NOW+dt.timedelta(minutes=1)).isoformat())
        self.processor.run()
        self.assertEqual(self.queue.counts()["obsolete"], 1)
        self.analyzer.analyze.assert_not_called()
        self.setUp(); self.now += dt.timedelta(hours=25)
        self.processor.run()
        self.assertEqual(self.queue.counts()["deferred"], 1)
        self.assertEqual(self.records.get(self.record["id"])["analysis_state"], "not_analyzed")

    def test_source_change_during_call_discards_old_result_and_does_not_mark_done(self):
        def change(_):
            self.records.register_official({**self.record["message"], "text": "중앙동 통제가 해제되었습니다. 통행에 참고해 주세요."}, "SN-1", (NOW+dt.timedelta(minutes=1)).isoformat())
            return {"analysis": {"summary": "old"}}
        self.analyzer.analyze.side_effect = change
        self.assertEqual(self.processor.run()["state"], "changed")
        self.assertEqual(self.queue.counts()["obsolete"], 1)
        self.assertIsNone(self.records.get(self.record["id"])["analysis"])

    def test_successful_manual_retry_closes_failed_automatic_task(self):
        self.queue.finish(task_id(self.record), "failed", NOW, "old_failure")
        self.records.on_analysis_saved = lambda saved: self.queue.sync_record(saved, NOW)
        self.records.analyze(self.record["id"], AnalyzeRecord(expected_version=1))
        self.assertEqual(self.queue.counts()["failed"], 0)
        self.assertEqual(self.queue.counts()["done"], 1)


class AutomationIntegrationTests(unittest.TestCase):
    def test_partial_row_validation_is_distinct_from_pending_pages_and_counts_are_observations(self):
        store=MemoryPipelineStore();store.values['collection-state']={'last_attempt_at':stamp(NOW),'work':[],
            'cycle_skipped':2,'cycle_skipped_reasons':{'recipient_region':2},'cycle_ignored_before_start':3}
        status=MessageAutomationStatus(SETTINGS,lambda:store,True,now=lambda:NOW).read()
        self.assertEqual(status['state'],'partial')
        self.assertIn('수신지역 확인 필요 2회',status['detail'])
        self.assertEqual(status['ignored_before_start'],3)

    def test_status_does_not_confuse_outage_partial_or_unverified_with_live(self):
        store = MemoryPipelineStore(); status = MessageAutomationStatus(SETTINGS, lambda: store, True, now=lambda: NOW)
        self.assertEqual(status.read()["state"], "starting")
        store.values["collection-state"] = {"last_attempt_at": stamp(NOW), "last_success_at": stamp(NOW), "work": []}
        self.assertEqual(status.read()["state"], "live")
        store.values["collection-state"]["work"] = [{}]
        self.assertEqual(status.read()["state"], "partial")
        store.values["collection-state"]["last_error"] = "collection_failed"
        self.assertEqual(status.read()["state"], "error")
        status.now = lambda: NOW+dt.timedelta(minutes=32)
        self.assertEqual(status.read()["state"], "stale")
        status.settings = replace(SETTINGS, contract_verified=False)
        self.assertEqual(status.read()["state"], "needs_verification")
        status.feed_configured = False
        self.assertEqual(status.read()["state"], "needs_key")
        status.store_factory = Mock(side_effect=RuntimeError("private"))
        self.assertEqual(status.read()["state"], "store_unavailable")
        self.assertNotIn("private", str(status.read()))

    def test_runtime_caches_pipeline_and_never_uses_memory_on_cloud_run(self):
        path = Path(__file__).resolve().parents[1]/"facilities_info.csv"
        with patch.dict("os.environ", {}, clear=True):
            runtime = build_message_runtime(path, "", "memory", "")
            self.assertIs(runtime.pipeline_factory(), runtime.pipeline_factory())
            self.assertFalse(runtime.automation.read()["auto_collection_enabled"])
        with patch.dict("os.environ", {"K_SERVICE": "worker"}, clear=True):
            runtime = build_message_runtime(path, "", "memory", "")
            self.assertFalse(runtime.records.availability()["storage_configured"])
            with self.assertRaises(AnalysisUnavailable): runtime.pipeline_factory()

    def test_private_worker_has_no_dispatch_routes_and_disabled_posts_do_no_work(self):
        runtime = Mock(settings=replace(SETTINGS, enabled=False), provider=Mock(configured=True))
        client = TestClient(create_app(runtime))
        self.assertEqual(client.post("/internal/v1/collect").json(), {"state": "disabled"})
        self.assertEqual(client.post("/internal/v1/analyze-next").json(), {"state": "disabled"})
        self.assertEqual(client.post("/internal/v1/dispatch").status_code, 404)
        runtime.pipeline_factory.assert_not_called()

    def test_settings_reject_configuration_injection_and_unknown_boolean(self):
        for env in ({"MESSAGE_COLLECTION_ENABLED": "yes"}, {"MESSAGE_ANALYSIS_DAILY_LIMIT": "0"},
                    {"MESSAGE_COLLECTION_MAX_PAGES": "999"}, {"MESSAGE_COLLECTION_START_AT": "2026-11-08"},
                    {"MESSAGE_ANALYSIS_DAILY_LIMIT": "1,OTHER=key"}):
            with self.assertRaises(ValueError): MessageAutomationSettings.from_environment(env)

    def test_nonversioned_observation_survives_concurrent_edit_and_rejects_source_rollback(self):
        records = make_service(); message = registration().canonical()
        original = records.register_official(message, "ID", NOW.isoformat())["record"]
        observed = records.register_official(message, "ID", (NOW+dt.timedelta(minutes=3)).isoformat())["record"]
        self.assertEqual(observed["version"], original["version"])
        original["note"] = "동시 수정"
        saved = records.store.commit(original, original["version"], "note_saved")
        self.assertEqual(saved["official_fetched_at"], observed["official_fetched_at"])
        saved["message"] = {**message, "text": "오래된 다른 원문입니다. 통행에 참고하세요."}
        saved["content_hash"] = "different"; saved["official_fetched_at"] = NOW.isoformat()
        with self.assertRaises(RecordConflict): records.store.commit(saved, saved["version"], "source_changed")
