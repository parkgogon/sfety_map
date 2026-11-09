import datetime as dt
import threading
import unittest
from unittest.mock import Mock

import requests

from safety_dashboard.adapters.openai_messages import OpenAIResponsesClient
from safety_dashboard.application.message_analysis import AnalysisBudgetBusy, AnalysisUnavailable, MessageAnalysisService
from safety_dashboard.application.message_automation import MessageAutomationSettings, MessageAutomationStatus
from safety_dashboard.application.message_pipeline import MemoryPipelineStore, AnalysisRunGate, MessageAnalysisQueue, task_id
from safety_dashboard.application.message_processing import MessageQueueProcessor
from safety_dashboard.application.message_records import AnalyzeRecord
from safety_dashboard.application.message_spend_budget import (
    MessageSpendBudget, SpendBudgetLimit, SpendBudgetUnavailable, RESERVATION, CONTRACT_KEY, MODEL,
)
from tests.test_message_analysis import FakePlaces, request, call
from tests.test_message_records import NOW, make_service, registration
from tests.test_message_pipeline_adapters import FakeFirestore
from safety_dashboard.adapters.firestore_message_pipeline import FirestoreMessagePipelineStore


def response(*, usage=None, status="completed", output=None):
    return Mock(status_code=200, json=Mock(return_value={"status": status, "output": output or [],
        "usage": usage if usage is not None else {"input_tokens": 1000, "output_tokens": 100,
                                                 "input_tokens_details": {"cached_tokens": 200}}}))


class SpendBudgetTests(unittest.TestCase):
    def setUp(self):
        self.clock = [NOW]
        self.store = MemoryPipelineStore()
        self.budget = MessageSpendBudget(self.store, now=lambda:self.clock[0])

    def client(self, **kwargs):
        self.session = Mock()
        self.session.post.return_value = response()
        return OpenAIResponsesClient("private-key", session=self.session, spend_factory=lambda:self.budget, **kwargs)

    def test_before_http_reservation_then_settles_actual_cached_and_reasoning_tokens(self):
        client = self.client()
        def post(*args, **kwargs):
            self.assertEqual(self.budget.status()["daily"]["reserved_usd"], .318)
            self.assertEqual(kwargs["json"]["max_output_tokens"], 4000)
            self.assertEqual(kwargs["json"]["service_tier"], "default")
            return response()
        self.session.post.side_effect = post
        client.respond([{ "role":"user", "content":"private-text"}], [], "instructions", 10)
        status = self.budget.status()
        self.assertAlmostEqual(status["daily"]["settled_usd"], .001065)
        self.assertEqual(status["daily"]["reserved_usd"], 0)
        self.assertEqual(status["daily"]["input_tokens"], 1000)
        self.assertEqual(status["monthly"]["cached_input_tokens"], 200)
        self.assertNotIn("private-key", str(self.store.values))
        self.assertNotIn("private-text", str(self.store.values))

    def test_atomic_reservations_cannot_overspend_the_last_slot(self):
        barrier = threading.Barrier(2); results=[]
        budget = MessageSpendBudget(self.store, daily_cents=32, now=lambda:NOW)
        def work():
            barrier.wait()
            try: budget.reserve(MODEL);results.append("reserved")
            except SpendBudgetLimit:results.append("limited")
        threads=[threading.Thread(target=work) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(5)
        self.assertCountEqual(results,["reserved","limited"])
        self.assertEqual(budget.status()["daily"]["calls"],1)

    def test_timeout_keeps_full_reservation_and_next_call_is_rejected_before_http(self):
        self.budget = MessageSpendBudget(self.store,daily_cents=32,now=lambda:NOW)
        client=self.client();self.session.post.side_effect=requests.Timeout("private-key")
        with self.assertRaises(AnalysisUnavailable):client.respond([],[],"",10)
        with self.assertRaises(SpendBudgetLimit):client.respond([],[],"",10)
        self.assertEqual(self.session.post.call_count,1)
        self.assertEqual(self.budget.status()["daily"]["reserved_usd"],.318)
        self.assertEqual(self.budget.status()["daily"]["unsettled_calls"],1)

    def test_incomplete_response_still_settles_reported_usage(self):
        client=self.client();self.session.post.return_value=response(status="incomplete")
        with self.assertRaises(AnalysisUnavailable):client.respond([],[],"",10)
        self.assertEqual(self.budget.status()["daily"]["reserved_usd"],0)
        self.assertGreater(self.budget.status()["daily"]["settled_usd"],0)

    def test_missing_usage_retains_reserve_and_invalid_usage_blocks_new_requests(self):
        for usage in (None, {"input_tokens":400001,"output_tokens":2},
                      {"input_tokens":20,"output_tokens":4001},
                      {"input_tokens":True,"output_tokens":1},
                      {"input_tokens":1,"output_tokens":1,"input_tokens_details":{"cached_tokens":2}}):
            with self.subTest(usage=usage):
                store=MemoryPipelineStore();budget=MessageSpendBudget(store,now=lambda:NOW)
                identifier=budget.reserve(MODEL)
                with self.assertRaises(SpendBudgetUnavailable):budget.settle(identifier,usage)
                self.assertEqual(budget.status()["daily"]["reserved_usd"],.318)
                if usage is not None:
                    self.assertTrue(budget.status()["blocked"])
                    with self.assertRaises(SpendBudgetUnavailable):budget.reserve(MODEL)

    def test_settlement_retry_is_idempotent_and_failed_commit_keeps_reserve(self):
        identifier=self.budget.reserve(MODEL)
        original=self.store.run
        self.store.run=Mock(side_effect=RuntimeError("private"))
        with self.assertRaises(SpendBudgetUnavailable):self.budget.settle(identifier,{"input_tokens":10,"output_tokens":1})
        self.store.run=original
        self.assertEqual(self.budget.status()["daily"]["reserved_usd"],.318)
        self.budget.settle(identifier,{"input_tokens":10,"output_tokens":1})
        settled=self.budget.status()
        self.budget.settle(identifier,{"input_tokens":10,"output_tokens":1})
        self.assertEqual(self.budget.status(),settled)

    def test_kst_day_rollover_keeps_month_reservations_and_retries_at_month_reset(self):
        self.clock[0]=NOW.replace(hour=23,minute=59)
        budget=MessageSpendBudget(self.store,daily_cents=100,monthly_cents=32,now=lambda:self.clock[0])
        budget.reserve(MODEL)
        self.clock[0]+=dt.timedelta(minutes=2)
        self.assertEqual(budget.status()["daily"]["reserved_usd"],0)
        self.assertEqual(budget.status()["monthly"]["reserved_usd"],.318)
        with self.assertRaises(SpendBudgetLimit) as error:budget.reserve(MODEL)
        self.assertEqual(dt.datetime.fromisoformat(error.exception.retry_at).astimezone(NOW.tzinfo).day,1)

    def test_late_settlement_uses_original_periods_after_month_rollover(self):
        self.clock[0]=NOW.replace(day=30,hour=23,minute=59)
        identifier=self.budget.reserve(MODEL)
        old_keys=self.store.get(identifier)["period_keys"]
        self.clock[0]+=dt.timedelta(minutes=2)
        self.budget.settle(identifier,{"input_tokens":10,"output_tokens":1})
        self.assertEqual(self.budget.status()["monthly"]["calls"],0)
        self.assertEqual(self.store.get(old_keys[1])["reserved_nano"],0)
        self.assertGreater(self.store.get(old_keys[1])["settled_nano"],0)

    def test_unknown_model_hosted_tool_or_store_outage_never_starts_http(self):
        for mode in ("model","tool","store"):
            with self.subTest(mode=mode):
                client=self.client(model="unknown-model" if mode=="model" else MODEL)
                if mode=="store":self.store.run=Mock(side_effect=RuntimeError("private"))
                with self.assertRaises(AnalysisUnavailable):client.respond([], [{"type":"web_search"}] if mode=="tool" else [], "",10)
                self.session.post.assert_not_called()

    def test_preflight_cost_denial_does_not_spend_daily_analysis_attempt_or_start_http(self):
        self.budget=MessageSpendBudget(self.store,daily_cents=1,now=lambda:NOW)
        client=self.client()
        gate=AnalysisRunGate(self.store,now=lambda:NOW)
        analyzer=MessageAnalysisService(client,FakePlaces(),lambda:(),gate_factory=lambda:gate)
        with self.assertRaises(AnalysisBudgetBusy):analyzer.analyze(request())
        self.assertEqual(gate.status()["attempts"],0)
        self.session.post.assert_not_called()

    def test_mid_loop_budget_denial_is_terminal_and_paid_turn_is_not_automatically_repeated(self):
        # A malformed first tool call still paid for a response; the second turn is denied.
        client=Mock(configured=True,model=MODEL)
        client.respond.side_effect=[call("unknown_tool",{}), SpendBudgetLimit((NOW+dt.timedelta(days=1)).isoformat())]
        analyzer=MessageAnalysisService(client,FakePlaces(),lambda:())
        records=make_service(analyzer)
        record=records.register_official(registration().canonical(),"paid-first-turn",NOW.isoformat())["record"]
        MessageAnalysisQueue(self.store).enqueue(record,NOW)
        settings=MessageAutomationSettings(enabled=True,contract_verified=True)
        processor=MessageQueueProcessor(records,self.store,settings,now=lambda:NOW)
        self.assertEqual(processor.run()["state"],"failed")
        self.assertEqual(records.get(record["id"])["analysis_state"],"failed")
        self.assertEqual(self.store.get(task_id(record))["state"],"failed")
        processor.run()
        self.assertEqual(client.respond.call_count,2)

    def test_queue_cost_denial_before_first_call_delays_without_recording_a_paid_attempt(self):
        analyzer=Mock();retry=NOW+dt.timedelta(days=1)
        analyzer.analyze.side_effect=AnalysisBudgetBusy(retry.isoformat())
        records=make_service(analyzer)
        record=records.register_official(registration().canonical(),"preflight",NOW.isoformat())["record"]
        MessageAnalysisQueue(self.store).enqueue(record,NOW)
        settings=MessageAutomationSettings(enabled=True,contract_verified=True)
        processor=MessageQueueProcessor(records,self.store,settings,now=lambda:NOW)
        self.assertEqual(processor.run()["state"],"spend_limit")
        self.assertEqual(records.get(record["id"])["analysis_state"],"not_analyzed")
        self.assertEqual(self.store.get(task_id(record))["attempts"],1)
        processor.run()
        self.assertEqual(analyzer.analyze.call_count,1)

    def test_firestore_budget_reads_all_periods_before_writing_and_never_uses_alert_collection(self):
        client=FakeFirestore()
        store=FirestoreMessagePipelineStore(client=client,transaction_runner=lambda callback:callback)
        budget=MessageSpendBudget(store,now=lambda:NOW)
        identifier=budget.reserve(MODEL)
        ops=[op[0] for op in client.operations]
        self.assertEqual(ops[:4],['get']*4)
        self.assertEqual(ops[4:],['set']*3)
        client.operations.clear()
        budget.settle(identifier,{'input_tokens':100,'output_tokens':20})
        ops=[op[0] for op in client.operations]
        self.assertEqual(ops[:4],['get']*4)
        self.assertEqual(ops[4:],['set']*3)
        self.assertTrue(all(key.startswith('disaster_message_pipeline/') for key in client.documents))

    def test_operator_status_reports_this_apps_actual_and_unsettled_budget_without_new_model_calls(self):
        self.budget.reserve(MODEL)
        status=MessageAutomationStatus(MessageAutomationSettings(spend_budget_enabled=True),lambda:self.store,False,now=lambda:NOW).read()
        self.assertEqual(status['spend_budget']['daily']['settled_usd'],0)
        self.assertEqual(status['spend_budget']['monthly']['reserved_usd'],.318)
        self.assertTrue(status['spend_budget']['can_start'])
        self.assertEqual(status['state'],'disabled')
