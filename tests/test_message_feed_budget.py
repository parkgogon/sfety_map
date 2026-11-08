import copy
from dataclasses import replace
import datetime as dt
import json
import threading
import unittest
from unittest.mock import Mock, patch

import requests

from safety_dashboard.adapters.disaster_messages import SafetyDataDisasterMessageProvider, DisasterMessageDataError
from safety_dashboard.application.message_feed_budget import OfficialRequestBudget, FeedRequestLimit, FeedBudgetUnavailable
from safety_dashboard.application.message_pipeline import MemoryPipelineStore, stamp
from safety_dashboard.application.message_automation import MessageAutomationSettings, MessageAutomationStatus
from safety_dashboard.application.message_collection import OfficialMessageCollector
from safety_dashboard.application.message_feed import OfficialFeedService, FeedRequest
from safety_dashboard.domain.models import DisasterMessage
from scripts.build_message_review_deploy_config import build_config
from tests.test_message_records import NOW, make_service


class OfficialRequestBudgetTests(unittest.TestCase):
    def test_service_cap_leaves_fifty_of_the_users_five_hundred_requests(self):
        budget = OfficialRequestBudget(MemoryPipelineStore(), now=lambda: NOW)
        for _ in range(450): budget.reserve()
        with self.assertRaises(FeedRequestLimit): budget.reserve()
        self.assertEqual(budget.status()["used"], 450)
        self.assertEqual(budget.status()["remaining"], 0)
        for invalid in (0, 451, 500):
            with self.assertRaises(ValueError): OfficialRequestBudget(MemoryPipelineStore(), invalid)

    def test_atomic_reservation_across_api_worker_and_simultaneous_requests(self):
        store = MemoryPipelineStore(); barrier = threading.Barrier(2); results = []
        def run():
            budget = OfficialRequestBudget(store, 1, now=lambda: NOW)
            barrier.wait()
            try: budget.reserve(); results.append("reserved")
            except FeedRequestLimit: results.append("limited")
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertCountEqual(results, ["reserved", "limited"])

    def test_rolling_window_does_not_reset_at_midnight_and_recovers_at_exact_expiry(self):
        now = [NOW.replace(hour=23, minute=59)]
        budget = OfficialRequestBudget(MemoryPipelineStore(), 1, now=lambda: now[0])
        budget.reserve()
        started = now[0]
        now[0] += dt.timedelta(minutes=2)
        with self.assertRaises(FeedRequestLimit): budget.reserve()
        self.assertEqual(budget.status()["next_available_at"], stamp(started+dt.timedelta(hours=24)))
        now[0] = started+dt.timedelta(hours=24)
        budget.reserve()
        self.assertEqual(budget.status()["used"], 1)

    def test_lowered_limit_reports_when_enough_old_requests_expire(self):
        now = [NOW]
        store = MemoryPipelineStore(); budget = OfficialRequestBudget(store, 3, now=lambda: now[0])
        for _ in range(3): budget.reserve(); now[0] += dt.timedelta(minutes=1)
        limited = OfficialRequestBudget(store, 1, now=lambda: now[0])
        self.assertEqual(limited.status()["next_available_at"], stamp(NOW+dt.timedelta(hours=24, minutes=2)))

    def test_failed_store_is_closed_and_does_not_echo_internal_data(self):
        budget = OfficialRequestBudget(Mock(run=Mock(side_effect=RuntimeError("private-data"))))
        with self.assertRaises(FeedBudgetUnavailable) as error: budget.reserve()
        self.assertNotIn("private-data", str(error.exception))

    @patch("safety_dashboard.adapters.disaster_messages.requests.get")
    def test_manual_and_automatic_provider_instances_share_count_and_timeout_is_counted(self, get):
        store = MemoryPipelineStore()
        factory = lambda: OfficialRequestBudget(store, 2, now=lambda: NOW)
        manual = SafetyDataDisasterMessageProvider("private-key", gate_factory=factory)
        automatic = SafetyDataDisasterMessageProvider("private-key", gate_factory=factory)
        get.return_value.json.return_value = {"totalCount": 0, "body": []}
        manual.fetch_page("대구광역시", NOW.date(), 1, 50)
        get.side_effect = requests.Timeout("private-key")
        with self.assertRaises(DisasterMessageDataError): automatic.fetch_page(None, NOW.date(), 1, 100)
        with self.assertRaises(FeedRequestLimit): manual.fetch_page("대구광역시", NOW.date(), 1, 50)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(factory().status()["used"], 2)
        self.assertNotIn("rgnNm", get.call_args.kwargs["params"])
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertNotIn("private-key", json.dumps(store.values))

    @patch("safety_dashboard.adapters.disaster_messages.requests.get")
    def test_unavailable_budget_or_redirect_cannot_start_more_http_requests(self, get):
        provider = SafetyDataDisasterMessageProvider("private", gate_factory=Mock(side_effect=RuntimeError("private")))
        with self.assertRaises(FeedBudgetUnavailable): provider.fetch_page(None, NOW.date(), 1, 100)
        get.assert_not_called()
        provider = SafetyDataDisasterMessageProvider("private")
        get.return_value.status_code = 302
        with self.assertRaises(DisasterMessageDataError): provider.fetch_page(None, NOW.date(), 1, 100)
        get.return_value.json.assert_not_called()


class NationalCollectionTests(unittest.TestCase):
    def setUp(self):
        self.records = make_service(); self.store = MemoryPipelineStore()
        self.settings = MessageAutomationSettings(enabled=True, contract_verified=True, start_at=NOW-dt.timedelta(minutes=1))
        self.provider = Mock(configured=True)
        self.provider.fetch_page.side_effect = lambda region, day, page, size: {"messages": [], "has_more": False, "skipped": 0}

    def message(self, identifier, regions, when=NOW):
        return DisasterMessage(identifier, when, "안전안내", "교통", "사고로 도로를 통제합니다. 다른 도로로 우회해 주세요.", regions)

    def collect(self):
        return OfficialMessageCollector(self.provider, self.records, self.store, self.settings, now=lambda: NOW).run()

    def test_one_national_page_per_date_replaces_ten_regional_calls(self):
        self.assertEqual(self.collect()["state"], "ok")
        self.assertEqual(self.provider.fetch_page.call_count, 2)
        self.assertTrue(all(call.args[0] is None for call in self.provider.fetch_page.call_args_list))
        self.assertEqual(self.settings.interval_seconds, 900)
        self.assertEqual(self.settings.max_pages, 4)
        self.assertEqual(86400//self.settings.interval_seconds*self.settings.max_pages, 384)

    def test_recipient_region_filters_before_storage_and_analysis_queue(self):
        rows = [self.message("target", ("서울특별시", "경상남도 창원시")), self.message("out", ("서울특별시",)),
                self.message("nation", ("전국",)), self.message("alias", ("대구 달서구",))]
        self.provider.fetch_page.side_effect = lambda region, day, page, size: {
            "messages": rows if day == NOW.date() else [], "has_more": False, "skipped": 0}
        self.assertEqual(self.collect()["state"], "ok")
        saved = self.records.list_page()["records"]
        self.assertEqual(len(saved), 3)
        target = self.records.get(self.records.official_record_id("target"))
        self.assertEqual(target["message"]["recipient_regions"], ["서울특별시", "경상남도 창원시"])
        self.assertIsNone(self.records.store.get(self.records.official_record_id("out")))

    def test_start_date_range_response_is_idempotent_and_missing_recipient_is_partial(self):
        self.provider.fetch_page.side_effect = lambda *args: {"messages": [self.message("target", ("부산광역시",))], "has_more": False, "skipped": 0}
        self.assertEqual(self.collect()["state"], "ok")
        self.assertEqual(len(self.records.list_page()["records"]), 1)
        self.provider.fetch_page.side_effect = lambda *args: {"messages": [self.message("unknown", ("-",))], "has_more": False, "skipped": 0}
        self.assertEqual(self.collect()["state"], "partial")

    def test_request_limit_preserves_progress_and_resumes_after_credits_recover(self):
        calls = [0]
        def limited(*args):
            calls[0] += 1
            if calls[0] == 2: raise FeedRequestLimit(stamp(NOW+dt.timedelta(hours=24)))
            return {"messages": [], "has_more": False, "skipped": 0}
        self.provider.fetch_page.side_effect = limited
        self.assertEqual(self.collect()["state"], "request_limit")
        state = self.store.get("collection-state")
        self.assertEqual(len(state["work"]), 1)
        self.assertFalse(state.get("last_success_at"))
        self.assertEqual(self.collect()["state"], "ok")
        # A fresh today page is inserted before resuming yesterday after a wait.
        self.assertEqual(self.provider.fetch_page.call_count, 4)
        self.assertEqual(self.provider.fetch_page.call_args.args[1], dt.date.fromisoformat(state["work"][0]["date"]))

    def test_status_prioritizes_request_wait_over_stale_or_success(self):
        self.store.values["collection-state"] = {"last_attempt_at": stamp(NOW-dt.timedelta(days=1)), "last_success_at": stamp(NOW-dt.timedelta(days=1))}
        budget = OfficialRequestBudget(self.store, 1, now=lambda: NOW)
        budget.reserve()
        settings = replace(self.settings, request_limit=1)
        status = MessageAutomationStatus(settings, lambda: self.store, True, now=lambda: NOW).read()
        self.assertEqual(status["state"], "request_limit")
        self.assertEqual(status["feed_budget"]["remaining"], 0)

    def test_deployment_rejects_excess_requests_and_invalid_cadence(self):
        for env in ({"MESSAGE_FEED_REQUEST_LIMIT": "500"}, {"MESSAGE_COLLECTION_MAX_PAGES": "5"}, {"MESSAGE_COLLECTION_INTERVAL_MINUTES": "5"}):
            with self.assertRaises(ValueError): MessageAutomationSettings.from_environment(env)
            with self.assertRaises(ValueError): build_config(env)
        config = build_config({})["MESSAGE_REVIEW_ENV_VARS"]
        self.assertIn("MESSAGE_FEED_REQUEST_LIMIT=450", config)
        self.assertIn("MESSAGE_COLLECTION_MAX_PAGES=4", config)
        self.assertIn("MESSAGE_COLLECTION_INTERVAL_MINUTES=15", config)
