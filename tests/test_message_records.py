import copy
import datetime as dt
import json
import threading
import unittest
import uuid
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient

from safety_dashboard.admin.access import AdminAccessSettings, AdminAccessVerifier
from safety_dashboard.api.app import create_app
from safety_dashboard.adapters.disaster_messages import SafetyDataDisasterMessageProvider, DisasterMessageDataError
from safety_dashboard.adapters.firestore_message_records import FirestoreMessageRecordStore
from safety_dashboard.application.context_info import KST
from safety_dashboard.application.message_analysis import AnalysisBusy, AnalysisUnavailable
from safety_dashboard.application.message_records import (
    MessageRecordService, MemoryRecordStore, RegisterMessage, AnalyzeRecord, SaveRecordNote,
    RecordConflict, RecordStorageUnavailable,
)
from safety_dashboard.application.message_feed import OfficialFeedService, FeedRequest
from safety_dashboard.application.message_feed_budget import FeedRequestLimit, FeedBudgetUnavailable
from safety_dashboard.domain.models import DisasterMessage
from tests.test_message_analysis import request as analysis_request, service, call, draft, part, FakePlaces, search_args, location, PLACE

NOW = dt.datetime(2026, 11, 8, 9, tzinfo=KST)


def registration(**overrides):
    return RegisterMessage(text="중앙동 사거리에서 차량 사고로 도로를 통제합니다.", source="공개 문자 수동 입력",
                           issued_at=NOW, registration_key=uuid.uuid4(), recipient_regions=["경상남도 창원시"], **overrides)


def make_service(analyzer=None, store=None):
    analyzer = analyzer or Mock(analyze=lambda req: {"input": req.model_dump(mode="json"), "analysis": {"summary": "검증된 가짜 분석"}})
    store = store or MemoryRecordStore()
    return MessageRecordService(lambda: store, analyzer, storage_mode="memory", now=lambda: NOW, facility_digest=lambda: "csv-test-digest")


def feed_provider():
    return Mock(configured=True, fetch_page=Mock(return_value={"messages": [
        DisasterMessage("official-123", NOW, "안전안내", "교통통제", "중앙동 사거리에서 차량 사고로 도로를 통제합니다.", ("경상남도 창원시",))],
        "has_more": False, "skipped": 0}))


class MessageRecordTests(unittest.TestCase):
    def test_registration_retry_is_idempotent_and_duplicate_content_does_not_merge_distinct_requests(self):
        svc = make_service(); req = registration()
        first = svc.register_manual(req)
        again = svc.register_manual(req)
        other = svc.register_manual(registration())
        self.assertEqual(again["registration"], "unchanged")
        self.assertEqual(first["record"], again["record"])
        self.assertNotEqual(other["record"]["id"], first["record"]["id"])
        self.assertEqual(len(svc.store.history(first["record"]["id"], None, 100)), 1)
        changed = req.model_copy(update={"text": "다른 원문의 문자입니다. 차량은 우회해 주세요."})
        with self.assertRaises(RecordConflict): svc.register_manual(changed)

    def test_source_and_analysis_survive_new_service_instance_and_notes_are_version_checked(self):
        store = MemoryRecordStore(); svc = make_service(store=store)
        record = svc.register_manual(registration())["record"]
        record = svc.analyze(record["id"], AnalyzeRecord(expected_version=1))
        another = make_service(store=store)
        saved = another.get(record["id"])
        self.assertEqual(saved["analysis"]["input"]["recipient_regions"], ["경상남도 창원시"])
        self.assertEqual(saved["facility_digest"], "csv-test-digest")
        changed = svc.save_note(record["id"], SaveRecordNote(expected_version=record["version"], review_state="needs_confirmation", note="정확한 교차로 확인"))
        with self.assertRaises(RecordConflict):
            another.save_note(record["id"], SaveRecordNote(expected_version=saved["version"], review_state="unreviewed"))
        self.assertEqual(another.get(record["id"])["note"], changed["note"])

    def test_changed_official_source_preserves_old_analysis_in_history_and_resets_current_analysis(self):
        svc = make_service(); message = registration().canonical()
        original = svc.register_official(message, "SN-1", NOW.isoformat())["record"]
        analyzed = svc.analyze(original["id"], AnalyzeRecord(expected_version=1))
        svc.now = lambda: NOW + dt.timedelta(minutes=1)
        changed_message = {**message, "text": "중앙동 사거리의 통제가 해제되었습니다. 통행에 참고하세요."}
        updated = svc.register_official(changed_message, "SN-1", (NOW + dt.timedelta(minutes=1)).isoformat())
        self.assertEqual(updated["registration"], "updated")
        self.assertEqual(updated["record"]["sort_key"], original["sort_key"])
        self.assertEqual(updated["record"]["source_revision"], 2)
        self.assertIsNone(updated["record"]["analysis"])
        self.assertEqual(updated["record"]["review_state"], "needs_confirmation")
        history = svc.store.history(original["id"], None, 20)
        self.assertTrue(any(row["record"]["analysis"] == analyzed["analysis"] for row in history))
        with self.assertRaises(RecordConflict): svc.register_official(message, "SN-1", NOW.isoformat())

    def test_newer_unchanged_observation_prevents_older_changed_snapshot_rollback(self):
        svc = make_service(); message = registration().canonical()
        record = svc.register_official(message, "SN-1", NOW.isoformat())["record"]
        newer = (NOW + dt.timedelta(minutes=3)).isoformat()
        observed = svc.register_official(message, "SN-1", newer)
        self.assertEqual(observed["registration"], "unchanged")
        self.assertEqual(observed["record"]["source_revision"], 1)
        with self.assertRaises(RecordConflict):
            svc.register_official({**message, "text": "오래된 조회 시점의 다른 문자 내용입니다."}, "SN-1", (NOW + dt.timedelta(minutes=1)).isoformat())
        self.assertEqual(svc.get(record["id"])["message"], message)

    def test_failed_reanalysis_retains_last_success_and_cannot_accept_client_supplied_analysis(self):
        analyzer = Mock(); analyzer.analyze.return_value = {"analysis": {"summary": "old"}}
        svc = make_service(analyzer)
        record = svc.register_manual(registration())["record"]
        record = svc.analyze(record["id"], AnalyzeRecord(expected_version=1))
        analyzer.analyze.side_effect = AnalysisUnavailable("safe failure")
        with self.assertRaises(AnalysisUnavailable): svc.analyze(record["id"], AnalyzeRecord(expected_version=record["version"]))
        saved = svc.get(record["id"])
        self.assertEqual(saved["analysis"], record["analysis"])
        self.assertEqual(saved["analysis_state"], "failed")
        with self.assertRaises(ValueError): AnalyzeRecord(expected_version=1, analysis={"fake": True})

    def test_source_change_while_analyzing_does_not_attach_old_result_to_new_source(self):
        analyzer = Mock(); svc = make_service(analyzer)
        message = registration().canonical()
        original = svc.register_official(message, "SN-1", NOW.isoformat())["record"]
        def change(_):
            svc.register_official({**message, "text": "차량 사고 통제가 모두 해제됐습니다. 통행에 참고하세요."}, "SN-1", (NOW + dt.timedelta(minutes=1)).isoformat())
            return {"analysis": {"summary": "old content"}}
        analyzer.analyze.side_effect = change
        with self.assertRaises(RecordConflict): svc.analyze(original["id"], AnalyzeRecord(expected_version=1))
        self.assertIsNone(svc.get(original["id"])["analysis"])
        self.assertEqual(svc.get(original["id"])["source_revision"], 2)

    def test_running_job_is_bounded_and_expired_lease_can_be_retried(self):
        svc = make_service(); record = svc.register_manual(registration())["record"]
        record.update(analysis_state="running", analysis_started_at=NOW.isoformat(), analysis_operation="lost-job")
        running = svc.store.commit(record, 1, "analysis_started")
        with self.assertRaises(AnalysisBusy): svc.analyze(record["id"], AnalyzeRecord(expected_version=running["version"]))
        svc.now = lambda: NOW + dt.timedelta(minutes=3)
        final = svc.analyze(record["id"], AnalyzeRecord(expected_version=running["version"]))
        self.assertEqual(final["analysis_state"], "completed")

    def test_list_pagination_does_not_skip_or_duplicate_equal_timestamp_records(self):
        svc = make_service()
        ids = {svc.register_manual(registration())["record"]["id"] for _ in range(5)}
        found = []; cursor = None
        while True:
            page = svc.list_page(cursor, limit=2)
            found.extend(row["id"] for row in page["records"])
            cursor = page["next_cursor"]
            if not cursor: break
        self.assertEqual(set(found), ids); self.assertEqual(len(found), 5)

    def test_two_competing_updates_do_not_overwrite_each_other(self):
        svc = make_service(); record = svc.register_manual(registration())["record"]
        barrier = threading.Barrier(2); results = []
        def update(note):
            copy_record = copy.deepcopy(record); copy_record["note"] = note; barrier.wait()
            try: svc.store.commit(copy_record, 1, "note_saved"); results.append("saved")
            except RecordConflict: results.append("conflict")
        threads = [threading.Thread(target=update, args=(note,)) for note in ("A", "B")]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertCountEqual(results, ["saved", "conflict"])

    def test_unconfigured_storage_does_not_fall_back_to_memory(self):
        svc = MessageRecordService(None, Mock())
        with self.assertRaises(RecordStorageUnavailable): svc.register_manual(registration())

    def test_recipient_region_reaches_real_agent_contract_without_rewriting_original_source(self):
        req = analysis_request("ambiguous", recipient_regions=["경상남도 창원시"])
        agent = service([
            call("search_places", search_args("중앙동 사거리", "restricted_area", "창원시")),
            call("find_nearby_facilities", {"candidate_id": "P1"}),
            call("submit_analysis", draft([part(req.text, "active_restriction", [location("중앙동 사거리", "restricted_area", ["P1"])])], ["통제 구간을 확인해 주세요."])),
        ], FakePlaces([{**PLACE, "name": "중앙동 사거리", "address": "경남 창원시 성산구 중앙동", "category_name": "교통 > 도로시설 > 교차로"}]))
        result = agent.analyze(req)
        self.assertEqual(agent.places.queries, ["창원시 중앙동 사거리"])
        self.assertEqual(result["input"]["source"], req.source)
        self.assertEqual(result["input"]["text"], req.text)
        self.assertTrue(result["candidates"][0]["scope_matches_source"])


class OfficialFeedTests(unittest.TestCase):
    def setUp(self):
        self.provider = feed_provider()
        self.svc = OfficialFeedService(self.provider, "test-signing-secret", now=lambda: NOW)
        self.query = FeedRequest(region="경상남도", date=NOW.date())

    def test_server_verified_import_preserves_source_and_rejects_tamper_expiry_and_admin_session_tokens(self):
        page = self.svc.fetch(self.query); token = page["messages"][0]["import_token"]
        message, identifier, fetched = self.svc.verify(token)
        self.assertEqual(message["recipient_regions"], ["경상남도 창원시"])
        self.assertEqual(identifier, "official-123"); self.assertEqual(fetched, NOW.isoformat())
        for bad in (token[:-1] + ("0" if token[-1] != "0" else "1"), "not-a-token", "a.b.c"):
            with self.assertRaises(ValueError): self.svc.verify(bad)
        self.svc.now = lambda: NOW + dt.timedelta(minutes=16)
        with self.assertRaises(ValueError): self.svc.verify(token)

    def test_feed_is_requested_only_by_page_and_does_not_auto_analyze_or_import(self):
        self.provider.fetch_page.return_value["has_more"] = True
        page = self.svc.fetch(self.query.model_copy(update={"page": 3}))
        self.provider.fetch_page.assert_called_once_with("경상남도", NOW.date(), 3, 50)
        self.assertTrue(page["page_limit_reached"])
        self.assertTrue(page["has_more"])

    def test_empty_unconfigured_and_invalid_dates_are_distinct(self):
        self.provider.configured = False
        self.assertEqual(self.svc.fetch(self.query)["status"], "NOT_CONFIGURED")
        self.provider.fetch_page.assert_not_called()
        self.provider.configured = True
        self.provider.fetch_page.return_value["messages"] = []
        self.assertEqual(self.svc.fetch(self.query)["status"], "LIVE")
        for delta in (1, -7):
            with self.assertRaises(ValueError): self.svc.fetch(self.query.model_copy(update={"date": NOW.date() + dt.timedelta(days=delta)}))
        with self.assertRaises(ValueError): FeedRequest(region="경상남도", date=NOW.date(), page=4)

    @patch("safety_dashboard.adapters.disaster_messages.requests.get")
    def test_adapter_passes_bounded_query_and_reports_total_and_dropped_rows(self, get):
        get.return_value.json.return_value = {"body": {"totalCount": 51, "items": [
            {"SN": "1", "CRT_DT": "2026/11/08 09:00:00", "MSG_CN": "중앙동 사거리 교통 통제 안내입니다.", "RCPTN_RGN_NM": "경상남도 창원시"},
            {"SN": "2", "MSG_CN": "시각이 없는 불완전한 문자"},
        ]}}
        result = SafetyDataDisasterMessageProvider("provider-secret").fetch_page("경상남도", NOW.date(), 1, 50)
        self.assertEqual(len(result["messages"]), 1); self.assertEqual(result["skipped"], 1)
        self.assertTrue(result["has_more"])
        self.assertEqual(get.call_args.kwargs["params"]["numOfRows"], 50)
        self.assertEqual(get.call_args.kwargs["params"]["crtDt"], "20261108")
        get.side_effect = requests.Timeout("provider-secret")
        with self.assertRaises(DisasterMessageDataError) as raised:
            SafetyDataDisasterMessageProvider("provider-secret").fetch_page("경상남도", NOW.date(), 1, 50)
        self.assertNotIn("provider-secret", str(raised.exception))


class MessageRecordRouteTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = Mock()
        self.analyzer.analyze.return_value = {"analysis": {"summary": "fake"}}
        self.svc = make_service(self.analyzer)
        self.feed = OfficialFeedService(feed_provider(), "test-signing-secret", now=lambda: NOW)
        self.verifier = AdminAccessVerifier(AdminAccessSettings(password="test-pass"))
        self.app = create_app(admin_access_service=self.verifier, message_record_service=self.svc, message_feed_service=self.feed)
        self.client = TestClient(self.app)
        self.base = "/internal/v1/message-records"

    def login(self):
        response = self.client.post("/internal/v1/admin/access", json={"password": "test-pass"})
        self.assertEqual(response.status_code, 200)

    def test_all_record_routes_require_admin_before_provider_or_storage_access(self):
        self.svc.store_factory = Mock(side_effect=AssertionError("unauthorized storage"))
        for method, path, body in (("GET", "", None), ("GET", "/status", None), ("GET", "/automation", None), ("POST", "/feed", {"region": "경상남도", "date": "2026-11-08"}),
                                   ("POST", "", registration().model_dump(mode="json")), ("GET", "/bad/history", None)):
            response = self.client.request(method, self.base + path, json=body)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.svc.store_factory.assert_not_called(); self.feed.provider.fetch_page.assert_not_called()

    def test_register_reload_analyze_note_and_conflict_are_server_saved(self):
        self.login()
        response = self.client.post(self.base, json=registration().model_dump(mode="json"))
        self.assertEqual(response.status_code, 200, response.text)
        record = response.json()["record"]; path = self.base + "/" + record["id"]
        self.assertEqual(self.client.get(path).json()["message"], record["message"])
        analyzed = self.client.post(path + "/analyze", json={"expected_version": 1}).json()
        self.assertEqual(analyzed["analysis_state"], "completed")
        changed = self.client.patch(path, json={"expected_version": analyzed["version"], "review_state": "needs_confirmation", "note": "위치 확인"})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.client.patch(path, json={"expected_version": 1, "review_state": "unreviewed"}).status_code, 409)
        self.assertEqual(len(self.client.get(path + "/history").json()["versions"]), 4)
        self.assertEqual(self.client.get(self.base).json()["records"][0]["note"], "위치 확인")

    def test_official_import_only_accepts_verified_provider_content_and_is_idempotent(self):
        self.login()
        page = self.client.post(self.base + "/feed", json={"region": "경상남도", "date": "2026-11-08"}).json()
        token = page["messages"][0]["import_token"]
        for expected in ("created", "unchanged"):
            response = self.client.post(self.base + "/import", json={"import_token": token})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["registration"], expected)
            self.assertEqual(response.json()["record"]["origin"], "official")
        forged = registration().model_dump(mode="json"); forged["input_kind"] = "official"
        self.assertEqual(self.client.post(self.base, json=forged).status_code, 422)
        self.assertEqual(self.client.post(self.base + "/import", json={"import_token": token + "0"}).status_code, 422)
        self.analyzer.analyze.assert_not_called()

    def test_storage_and_provider_errors_do_not_leak_secrets_or_claim_success(self):
        self.login(); self.svc.store_factory = Mock(side_effect=RuntimeError("private-credential"))
        response = self.client.post(self.base, json=registration().model_dump(mode="json"))
        self.assertEqual(response.status_code, 503); self.assertNotIn("private-credential", response.text)
        self.feed.provider.fetch_page.side_effect = DisasterMessageDataError("private-provider-key")
        response = self.client.post(self.base + "/feed", json={"region": "경상남도", "date": "2026-11-08"})
        self.assertEqual(response.status_code, 503); self.assertNotIn("private-provider-key", response.text)
        self.assertEqual(self.client.get(self.base + "/arbitrary").status_code, 404)

    def test_automation_status_is_protected_read_only_and_worker_routes_are_absent(self):
        self.assertEqual(self.client.get(self.base + "/automation").status_code, 403)
        self.login()
        response = self.client.get(self.base + "/automation")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertFalse(response.json()["auto_collection_enabled"])
        self.analyzer.analyze.assert_not_called()
        self.assertEqual(self.client.post("/internal/v1/collect").status_code, 404)
        self.assertEqual(self.client.post("/internal/v1/analyze-next").status_code, 404)

    def test_manual_feed_reports_shared_request_limit_without_claiming_empty_success(self):
        self.login()
        body = {"region": "경상남도", "date": "2026-11-08"}
        self.feed.provider.fetch_page.side_effect = FeedRequestLimit((NOW+dt.timedelta(days=2)).isoformat())
        response = self.client.post(self.base+"/feed", json=body)
        self.assertEqual(response.status_code, 429)
        self.assertGreaterEqual(int(response.headers["retry-after"]), 1)
        self.assertIn("조회 한도", response.json()["detail"])
        self.feed.provider.fetch_page.side_effect = FeedBudgetUnavailable("문자 조회 한도를 확인하지 못했습니다.")
        self.assertEqual(self.client.post(self.base+"/feed", json=body).status_code, 503)


class FirestoreMessageStoreTests(unittest.TestCase):
    def test_compare_and_set_transaction_writes_current_and_history_and_rejects_stale_update(self):
        documents = {}; transaction = Mock()
        class Ref:
            def __init__(self, path): self.path = path
            def get(self, **kwargs):
                value = documents.get(self.path)
                return Mock(exists=value is not None, to_dict=lambda: copy.deepcopy(value))
            def collection(self, name): return Collection(self.path + "/" + name)
        class Collection:
            def __init__(self, path): self.path = path
            def document(self, name): return Ref(self.path + "/" + name)
        transaction.set.side_effect = lambda ref, data: documents.update({ref.path: copy.deepcopy(data)})
        client = Mock(); client.collection.side_effect = Collection; client.transaction.return_value = transaction
        store = FirestoreMessageRecordStore(client=client, transaction_runner=lambda callback: callback)
        svc = make_service(store=store)
        record = svc.register_manual(registration())["record"]
        self.assertEqual(len(documents), 2)
        self.assertTrue(all(path.startswith("disaster_message_reviews/") for path in documents))
        self.assertEqual(store.get(record["id"]), record)
        with self.assertRaises(RecordConflict): store.commit(record, 0, "stale")
        self.assertEqual(len(documents), 2)
        self.assertEqual(store.get(record["id"])["version"], 1)
