import copy
import datetime as dt
import json
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient

from safety_dashboard.admin.access import AdminAccessSettings, AdminAccessVerifier
from safety_dashboard.api.app import create_app
from safety_dashboard.application.message_analysis import MessageAnalysisInput, MessageAnalysisService
from safety_dashboard.application.message_facility_queries import FacilityQuery, query_facilities
from safety_dashboard.application.message_notification import notification_preview
from safety_dashboard.application.message_records import AnalyzeRecord
from safety_dashboard.application.message_spatial import MessageSpatialService
from safety_dashboard.domain.models import Facility, GeoPoint
from tests.test_message_analysis import FakeClient, FakePlaces, call, draft, part, location, search_args
from tests.test_message_records import make_service, registration

NOW = dt.datetime.fromisoformat("2026-11-09T10:05:00+09:00")
ISSUED = "2026-11-09T10:00:00+09:00"
DIGEST = "a" * 64
CATALOG = (
    Facility("FA", "창작 A처리장", "처리장", GeoPoint(35.851, 128.5), "대구광역시 달서구 시험로 1", manager="private-manager"),
    Facility("FB", "창작 B측정소", "측정소", GeoPoint(35.852, 128.5), "대구광역시 달서구 시험로 2"),
    Facility("FC", "창작 원거리시설", "사업소", GeoPoint(36.1, 128.7), "대구광역시 북구 시험로 3"),
    Facility("FD", "창작 부산시설", "사업소", GeoPoint(35.3, 129.2), "부산광역시 기장군 시험로 4"),
)


def assessment(text, *, need="notify", relevance="nearby", urgency="immediate", refs=()):
    return {"need": need, "urgency": urgency, "relevance": relevance, "reason": "창작 입력의 업무 관련 정보를 확인함",
            "evidence": [text], "basis_refs": list(refs)}


def analyzed_record(text, a, *, steps=(), parts=None, questions=(), issued=ISSUED, origin="example", regions=()):
    req = MessageAnalysisInput(text=text, source="창작 예문", issued_at=issued,
        reference_radius_km=3, input_kind=origin, recipient_regions=list(regions))
    body = {**draft(parts or [part(text)], list(questions)), "notification_assessment": a}
    client = FakeClient([*steps, call("submit_analysis", body)])
    svc = MessageAnalysisService(client, FakePlaces(), lambda: CATALOG)
    result = svc.analyze(req)
    record = {"id": "manual-" + "a"*32, "version": 3, "origin": origin,
        "message": {"text": text, "source": req.source, "issued_at": issued, "recipient_regions": list(regions)},
        "source_revision": 1, "analysis_source_revision": 1, "analysis_revision": 1,
        "analysis_state": "completed", "analysis": result, "facility_digest": DIGEST,
        "review_state": "unreviewed", "review_completion": None}
    return record, client


def preview(record, **overrides):
    return notification_preview(record, (DIGEST, CATALOG), now=NOW,
                                base_url="https://example.test/control/messages?token=not-a-real-token", **overrides)


def point_case(*, destination=False):
    text = "대구 성서산업단지에서 화재가 발생했습니다. 인근 통행에 주의하세요."
    steps = [call("search_places", search_args()), call("find_nearby_facilities", {"candidate_id": "P1"})]
    return analyzed_record(text, assessment(text, refs=["P1"]), steps=steps,
        parts=[part(text, locations=[location(candidate_ids=["P1"])])], questions=["산업단지 대표점으로 실제 발생 위치는 미상입니다."])


class NotificationPreviewTests(unittest.TestCase):
    def test_point_event_uses_server_distances_and_has_public_links_without_private_data(self):
        record, client = point_case()
        result = preview(record)
        self.assertEqual(result["decision"], "notify_ready")
        self.assertEqual({f["id"] for f in result["facilities"]}, {"FA", "FB"})
        self.assertLess(result["facilities"][0]["distance_m"], 120)
        self.assertIn("검색 기준점", result["preview_text"])
        self.assertEqual(result["map_url"], "https://example.test/")
        self.assertNotIn("control", result["preview_text"])
        self.assertNotIn("not-a-real-token", result["preview_text"])
        self.assertNotIn("private-", json.dumps(result))
        self.assertEqual(len(client.inputs), 3)
        self.assertFalse(result["dispatch_enabled"])

    def test_area_wide_water_outage_queries_addresses_without_places_or_distances(self):
        text = "대구광역시 달서구 전역이 단수 상태입니다. 시설 운영에 참고하세요."
        args = {"area_text": "대구광역시 달서구", "facility_name": None, "evidence": text}
        record, client = analyzed_record(text, assessment(text, relevance="area_operations", refs=["FQ1"]),
            steps=[call("find_monitored_facilities", args)], parts=[part(text, "advisory")])
        result = preview(record)
        self.assertEqual(result["decision"], "notify_ready")
        self.assertEqual(len(result["facilities"]), 2)
        self.assertTrue(all(f["distance_m"] is None for f in result["facilities"]))
        self.assertEqual(len(client.inputs), 2)
        self.assertNotIn("km", result["preview_text"])

    def test_named_facility_outside_reference_radius_is_still_relevant(self):
        text = "창작 원거리시설 전력 공급이 중단되었습니다. 운영 담당자는 확인 바랍니다."
        args = {"area_text": None, "facility_name": "창작 원거리시설", "evidence": text}
        record, _ = analyzed_record(text, assessment(text, relevance="facility", refs=["FQ1"]),
                                   steps=[call("find_monitored_facilities", args)])
        result = preview(record)
        self.assertEqual(result["decision"], "notify_ready")
        self.assertEqual([f["id"] for f in result["facilities"]], ["FC"])
        self.assertEqual(result["map_url"], "https://example.test/?facility_id=FC")

    def test_general_prevention_is_recorded_without_model_or_location_retries(self):
        text = "기온이 내려갑니다. 외출 시 건강관리에 유의하시기 바랍니다."
        record, client = analyzed_record(text, assessment(text, need="record_only", relevance="general", urgency="reference"),
                                         parts=[part(text, "prevention")])
        before = copy.deepcopy(record)
        self.assertEqual(preview(record)["decision"], "record_only")
        self.assertEqual(preview(record)["decision"], "record_only")
        self.assertEqual(len(client.inputs), 1)
        self.assertEqual(record, before)

    def test_partial_release_preview_preserves_both_exact_source_sections(self):
        released = "대구광역시 달서구 가람교 통제는 10시 해제되었습니다."
        active = "푸른교 하부도로는 계속 통제 중입니다."
        text = released + " " + active
        record, _ = analyzed_record(text, assessment(text, relevance="area_operations", refs=["FQ1"]),
            steps=[call("find_monitored_facilities", {"area_text": "대구광역시 달서구", "facility_name": None, "evidence": text})],
            parts=[part(released, "release"), part(active, "active_restriction")])
        result = preview(record)
        self.assertIn(released, result["preview_text"])
        self.assertIn(active, result["preview_text"])
        self.assertNotIn("전체 해제", result["preview_text"])

    def test_urgent_known_region_without_precise_location_is_source_only(self):
        text = "대구광역시 달서구 화재로 인근 주민은 즉시 대피하시기 바랍니다."
        record, _ = analyzed_record(text, assessment(text, relevance="area_operations"),
                                    questions=["정확한 화재 발생 지점은 확인되지 않았습니다."])
        result = preview(record)
        self.assertEqual(result["decision"], "notify_source_only")
        self.assertEqual(result["facilities"], [])
        self.assertNotIn("km", result["preview_text"])
        self.assertIn(text, result["preview_text"])

    def test_multiple_recipient_regions_do_not_establish_an_incident_city(self):
        text = "중앙동 사거리 사고로 도로를 통제합니다. 인근 차량은 우회하세요."
        record, _ = analyzed_record(text, assessment(text, relevance="area_operations"),
                                    regions=["대구광역시", "부산광역시"])
        result = preview(record)
        self.assertEqual(result["decision"], "attention_required")
        self.assertIsNone(result["preview_text"])

    def test_source_only_keeps_the_whole_original_when_an_extracted_part_is_short(self):
        text = "대구광역시 달서구 화재입니다. 인근 주민은 즉시 대피하시기 바랍니다. 일부 도로는 통제 중입니다."
        record, _ = analyzed_record(text, assessment(text, relevance="area_operations"),
                                   parts=[part("화재입니다.")], questions=["정확한 화재 발생 지점 미상"])
        result = preview(record)
        self.assertEqual(result["decision"], "notify_source_only")
        self.assertIn(text, result["preview_text"])

    def test_destination_cannot_be_used_as_incident_nearby_basis(self):
        text = "대구 성서산업단지 화재입니다. 대피 목적지는 성서초등학교입니다."
        places = FakePlaces([{**FakePlaces().rows[0], "name": "성서초등학교", "category_group_code": "SC4"}])
        client = FakeClient([call("search_places", search_args("성서초등학교", "evacuation_destination")),
            call("submit_analysis", {**draft([part(text, locations=[location("성서초등학교", "evacuation_destination", ["P1"])])]),
                                     "notification_assessment": assessment(text, refs=["P1"])})])
        svc = MessageAnalysisService(client, places, lambda: CATALOG)
        record, _ = analyzed_record(text, assessment(text))
        record["analysis"] = svc.analyze(MessageAnalysisInput.model_validate(record["analysis"]["input"]))
        self.assertEqual(preview(record)["decision"], "attention_required")

    def test_scheduled_notice_requires_and_preserves_future_start(self):
        text = "대구광역시 달서구 도로는 내일 09시부터 18시까지 통제 예정입니다."
        record, _ = analyzed_record(text, assessment(text, relevance="area_operations", urgency="scheduled", refs=["FQ1"]),
            steps=[call("find_monitored_facilities", {"area_text": "대구광역시 달서구", "facility_name": None, "evidence": text})],
            parts=[part(text, "scheduled_restriction", time_text="내일 09시부터 18시까지",
                starts_at="2026-11-10T09:00:00+09:00", ends_at="2026-11-10T18:00:00+09:00")])
        self.assertIn("예정 상황", preview(record)["preview_text"])
        record["analysis"]["analysis"]["parts"][0]["starts_at"] = None
        self.assertEqual(preview(record)["decision"], "attention_required")

    def test_official_immediate_one_hour_cutoff_does_not_expire_a_valid_future_schedule(self):
        record,_=point_case();record['origin']='official';record['analysis']['input']['input_kind']='official'
        later=dt.datetime.fromisoformat(ISSUED)+dt.timedelta(hours=1,seconds=1)
        result=notification_preview(record,(DIGEST,CATALOG),now=later)
        self.assertEqual(result['decision'],'attention_required')
        self.assertIn('1시간',result['reason'])
        text='대구광역시 달서구 도로는 내일 09시부터 18시까지 통제 예정입니다.'
        scheduled,_=analyzed_record(text,assessment(text,relevance='area_operations',urgency='scheduled',refs=['FQ1']),
            origin='official',steps=[call('find_monitored_facilities',{'area_text':'대구광역시 달서구','facility_name':None,'evidence':text})],
            parts=[part(text,'scheduled_restriction',time_text='내일 09시부터 18시까지',starts_at='2026-11-10T09:00:00+09:00',ends_at='2026-11-10T18:00:00+09:00')])
        self.assertEqual(notification_preview(scheduled,(DIGEST,CATALOG),now=later)['decision'],'notify_ready')

    def test_outside_incident_is_not_located_using_target_recipient_regions(self):
        text = "서울특별시 강남구 화재로 인근 도로가 통제됩니다."
        record, _ = analyzed_record(text, assessment(text, need="record_only", relevance="outside_scope", urgency="reference"),
                                    regions=["부산광역시"])
        self.assertEqual(preview(record)["decision"], "record_only")

    def test_invalid_model_evidence_or_ids_are_returned_for_correction_inside_existing_call_budget(self):
        text = "일반적인 건강관리 예방 안내입니다. 외출 시 주의하세요."
        good = assessment(text, need="record_only", relevance="general", urgency="reference")
        for bad in ({**good, "evidence": ["원문에 없는 인용"]}, {**good, "basis_refs": ["FQ9"]}):
            with self.subTest(bad=bad):
                old = {**draft([part(text, "prevention")]), "notification_assessment": bad}
                record, client = analyzed_record(text, good, parts=[part(text, "prevention")], steps=[call("submit_analysis", old)])
                self.assertEqual(len(client.inputs), 2)
                self.assertEqual(preview(record)["decision"], "record_only")

    def test_stored_claimed_distance_is_recomputed_and_invented_summary_is_not_forwarded(self):
        record, _ = point_case()
        record["analysis"]["nearby"][0]["facilities"][0]["distance_m"] = 99999999
        record["analysis"]["analysis"]["summary"] = "가짜 시설이 99km 거리에서 피해를 입었습니다."
        result = preview(record)
        self.assertLess(result["facilities"][0]["distance_m"], 120)
        self.assertNotIn("99km", result["preview_text"])
        record["analysis"]["analysis"]["notification_assessment"]["basis_refs"] = ["P99"]
        self.assertEqual(preview(record)["decision"], "attention_required")

    def test_changed_source_catalog_or_analysis_failure_cannot_use_previous_ready_preview(self):
        original, _ = point_case()
        for patch, expected in (({"source_revision": 2}, "blocked"), ({"facility_digest": "changed"}, "blocked"),
                                ({"analysis_state": "failed"}, "analysis_unavailable")):
            record = {**original, **patch}
            self.assertEqual(preview(record)["decision"], expected)
            self.assertIsNone(preview(record)["preview_text"])
        changed = copy.deepcopy(original)
        changed["message"]["text"] = "정정된 다른 원문입니다. 이전 내용과 다릅니다."
        self.assertEqual(preview(changed)["decision"], "blocked")

    def test_missing_unknown_or_old_official_time_does_not_become_current_urgent_information(self):
        for issued in (None, "2026-11-10T10:00:00+09:00", "2026-11-07T10:00:00+09:00"):
            text = "대구광역시 달서구 화재로 대피 안내를 확인해 주세요."
            record, _ = analyzed_record(text, assessment(text, relevance="area_operations"), issued=issued, origin="official")
            self.assertEqual(preview(record)["decision"], "attention_required")

    def test_legacy_results_and_inconsistent_record_only_judgments_are_not_auto_authorized(self):
        record, _ = point_case()
        record["analysis"]["analysis"].pop("notification_assessment")
        self.assertIn("이전 분석", preview(record)["reason"])
        record, _ = point_case()
        record["analysis"]["analysis"]["notification_assessment"]["need"] = "record_only"
        self.assertEqual(preview(record)["decision"], "attention_required")

    def test_outside_scope_label_without_an_explicit_outside_region_is_not_enough_to_suppress(self):
        text = "화재가 발생했습니다. 업무 관련 지역이 어디인지 확인이 필요합니다."
        record, _ = analyzed_record(text, assessment(text, need="record_only", relevance="outside_scope", urgency="reference"))
        self.assertEqual(preview(record)["decision"], "attention_required")

    def test_invalid_coordinates_are_not_used_for_distances(self):
        record, _ = point_case()
        record["analysis"]["candidates"][0]["latitude"] = float("nan")
        self.assertEqual(preview(record)["decision"], "attention_required")
        self.assertIsNone(preview(record)["preview_text"])

    def test_model_query_display_limit_does_not_undercount_the_server_preview(self):
        text = "대구광역시 달서구 전역이 단수 상태입니다. 시설 운영에 참고하세요."
        args = {"area_text": "대구광역시 달서구", "facility_name": None, "evidence": text}
        record, _ = analyzed_record(text, assessment(text, relevance="area_operations", refs=["FQ1"]),
            steps=[call("find_monitored_facilities", args)], parts=[part(text, "advisory")])
        many = tuple(Facility(f"M{i:02}", f"창작 시설 {i}", "사업소", GeoPoint(35.8,128.5), "대구광역시 달서구 시험로") for i in range(25))
        model_query = query_facilities(FacilityQuery(**args), text, many)
        self.assertEqual(model_query["shown_count"], 20)
        result = notification_preview(record, (DIGEST, many), now=NOW)
        self.assertEqual(len(result["facilities"]), 25)
        self.assertIn("그 외 참고시설 22개소", result["preview_text"])


class FacilityQueryTests(unittest.TestCase):
    def test_subdistrict_address_boundaries_and_exact_facility_names_are_required(self):
        text = "대구광역시 달서구 창작 A처리장의 운영 안내입니다."
        result = query_facilities(FacilityQuery(area_text="대구광역시 달서구", facility_name="창작 A처리장", evidence=text), text, CATALOG)
        self.assertEqual([f["id"] for f in result["facilities"]], ["FA"])
        self.assertNotIn("private-", json.dumps(result))
        for args in ({"area_text": "달서구", "facility_name": None},
                     {"area_text": "대구광역시", "facility_name": None},
                     {"area_text": None, "facility_name": "조작한 시설명"}):
            with self.assertRaises(ValueError):
                query_facilities(FacilityQuery(**args, evidence=text), text, CATALOG)

    def test_duplicate_facility_names_remain_ambiguous_without_an_explicit_area(self):
        text = "창작 A처리장 운영에 관한 안내입니다."
        extra = Facility("FE", "창작 A처리장", "처리장", GeoPoint(35.3, 129.2), "부산광역시 기장군 시험로")
        result = query_facilities(FacilityQuery(area_text=None, facility_name="창작 A처리장", evidence=text), text, (*CATALOG, extra))
        self.assertEqual(result["status"], "needs_confirmation")


class PreviewRouteTests(unittest.TestCase):
    def test_preview_is_authenticated_version_checked_read_only_and_uses_no_paid_calls(self):
        record, _ = point_case()
        records = make_service()
        saved = records.register_manual(registration())["record"]
        record.update(id=saved["id"], version=saved["version"])
        records.store.records[saved["id"]] = copy.deepcopy(record)
        analyzer = Mock()
        records.analysis = analyzer
        app = create_app(message_record_service=records, message_analysis_service=analyzer,
            message_spatial_service=MessageSpatialService(records, lambda: (DIGEST, CATALOG)),
            admin_access_service=AdminAccessVerifier(AdminAccessSettings("local-test-password")))
        client = TestClient(app)
        path = f"/internal/v1/message-records/{record['id']}/notification-preview?expected_version=1"
        self.assertEqual(client.get(path).status_code, 403)
        login = client.post("/internal/v1/admin/access", json={"password": "local-test-password"})
        self.assertEqual(login.status_code, 200, login.text)
        token = login.json()["token"]
        headers = {"X-Alert-Admin-Token": token}
        before = records.get(record["id"])
        response = client.get(path, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["dispatch_enabled"])
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(client.get(path.replace("=1", "=2"), headers=headers).status_code, 409)
        self.assertEqual(records.get(record["id"]), before)
        analyzer.analyze.assert_not_called()
