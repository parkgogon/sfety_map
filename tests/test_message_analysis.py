import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient
from pydantic import ValidationError

from safety_dashboard.adapters.openai_messages import OpenAIResponsesClient
from safety_dashboard.adapters.kakao_places import KakaoPlaceSearch
from safety_dashboard.admin.access import AdminAccessSettings, AdminAccessVerifier
from safety_dashboard.admin.session import AdminSessionManager
from safety_dashboard.api.app import create_app
from safety_dashboard.application.message_analysis import (
    AnalysisBusy, AnalysisUnavailable, MAX_MODEL_CALLS, MessageAnalysisInput, MessageAnalysisService, TOOLS,
)
from safety_dashboard.domain.models import Facility, GeoPoint

EXAMPLES = json.loads((Path(__file__).resolve().parents[1] / "field_web/src/messageExamples.json").read_text())
PLACE = {"name": "시험 장소", "address": "대구 시험 주소", "latitude": 35.85, "longitude": 128.5, "provider": "fake"}
FACILITIES = (Facility(id="F-test", name="시험 시설", facility_type="측정소", address="시험 주소",
                       location=GeoPoint(35.851, 128.5), manager="private-manager", metadata={"phone": "private-phone"}),)


def request(example_id="event", **overrides):
    example = next(row for row in EXAMPLES if row["id"] == example_id)
    return MessageAnalysisInput(**{**{key: example[key] for key in ("text", "issued_at", "source")},
                                   "input_kind": "example", "reference_radius_km": 3, **overrides})


def part(evidence, intent="event", locations=None, **kwargs):
    return {"intent": intent, "description": "검토용 설명", "evidence": evidence, "time_text": "",
            "starts_at": None, "ends_at": None, "locations": locations or [], **kwargs}


def draft(parts, questions=None):
    return {"summary": "검토용 요약", "parts": parts, "questions": questions or []}


def location(text="성서산업단지", role="incident_site", candidate_ids=None):
    return {"text": text, "role": role, "evidence": text, "candidate_ids": candidate_ids or []}


def call(name, args, extra=None):
    return [*(extra or []), {"type": "function_call", "name": name, "call_id": "test-call", "arguments": json.dumps(args, ensure_ascii=False)}]


class FakeClient:
    configured = True
    model = "fake-model"

    def __init__(self, responses):
        self.responses = responses
        self.inputs = []

    def respond(self, items, tools, instructions, timeout):
        self.inputs.append(copy.deepcopy(items))
        return copy.deepcopy(self.responses[min(len(self.inputs) - 1, len(self.responses) - 1)])


class FakePlaces:
    configured = True

    def __init__(self, rows=None):
        self.rows = [PLACE] if rows is None else rows
        self.queries = []

    def search(self, query, timeout):
        self.queries.append(query)
        return self.rows


def service(responses, places=None, **kwargs):
    return MessageAnalysisService(FakeClient(responses), places or FakePlaces(), lambda: FACILITIES, **kwargs)


class MessageAgentTests(unittest.TestCase):
    def test_prevention_can_finish_without_location_or_facility_lookup(self):
        req = request("prevention")
        svc = service([call("submit_analysis", draft([part(req.text, "prevention")]))])
        result = svc.analyze(req)
        self.assertEqual(result["nearby"], [])
        self.assertEqual(svc.places.queries, [])
        self.assertTrue(result["review_required"])
        self.assertEqual(result["model_calls"], 1)

    def test_model_selects_lookup_chain_and_receives_real_tool_results(self):
        req = request()
        reasoning = {"type": "reasoning", "id": "rs-test", "summary": [], "encrypted_content": "opaque-state"}
        svc = service([
            call("search_places", {"query": "대구 성서산업단지", "evidence": "성서산업단지"}, [reasoning]),
            call("find_nearby_facilities", {"candidate_id": "P1"}),
            call("submit_analysis", draft([part(req.text, locations=[location(candidate_ids=["P1"])])])),
        ])
        result = svc.analyze(req)
        self.assertEqual(result["nearby"][0]["facilities"][0]["id"], "F-test")
        self.assertLess(result["nearby"][0]["facilities"][0]["distance_m"], 120)
        self.assertIn(reasoning, svc.client.inputs[1])
        self.assertEqual(json.loads(svc.client.inputs[1][-1]["output"])["candidates"][0]["id"], "P1")
        self.assertNotIn("private-", json.dumps(svc.client.inputs))
        self.assertNotIn("private-", json.dumps(result))

    def test_all_six_fixture_contracts_accept_grounded_parts_without_claiming_model_accuracy(self):
        # Scripted interpretations test validation/transport, not a real model's classification.
        for example in EXAMPLES:
            with self.subTest(example=example["id"]):
                req = request(example["id"])
                rows = [part(req.text, intent) for intent in example["expected_intents"]]
                result = service([call("submit_analysis", draft(rows))]).analyze(req)
                self.assertEqual([row["intent"] for row in result["analysis"]["parts"]], example["expected_intents"])

    def test_relative_time_uses_issued_korean_date_and_preserves_future_interval(self):
        req = request("scheduled", issued_at="2026-11-07T08:00:00Z")
        result_part = part(req.text, "scheduled_restriction", time_text="내일 09시부터 12시까지",
                           starts_at="2026-11-08T09:00:00+09:00", ends_at="2026-11-08T12:00:00+09:00")
        svc = service([call("submit_analysis", draft([result_part]))])
        result = svc.analyze(req)
        self.assertEqual(json.loads(svc.client.inputs[0][0]["content"])["issued_at"], "2026-11-07T17:00:00+09:00")
        self.assertEqual(result["analysis"]["parts"][0]["starts_at"], "2026-11-08T09:00:00+09:00")

    def test_partial_release_retains_two_independent_segments(self):
        req = request("partial_release")
        rows = [part("가람교 하부도로 통제는 15시 해제되었습니다.", "release"),
                part("푸른교 하부도로는 침수로 계속 통제 중", "active_restriction")]
        result = service([call("submit_analysis", draft(rows))]).analyze(req)
        self.assertEqual(len(result["analysis"]["parts"]), 2)

    def test_destination_lookup_is_not_returned_as_incident_nearby_facilities(self):
        req = request("destination")
        svc = service([
            call("search_places", {"query": "성서초등학교", "evidence": "성서초등학교"}),
            call("find_nearby_facilities", {"candidate_id": "P1"}),
            call("submit_analysis", draft([part(req.text, locations=[location("성서초등학교", "evacuation_destination", ["P1"])])])),
        ])
        self.assertEqual(svc.analyze(req)["nearby"], [])

    def test_ambiguous_candidates_are_preserved_and_do_not_become_confirmed_points(self):
        req = request("ambiguous")
        svc = service([
            call("search_places", {"query": "중앙동 사거리", "evidence": "중앙동"}),
            call("submit_analysis", draft([part(req.text, "active_restriction", [location("중앙동", "restricted_area", ["P1", "P2"])])], ["어느 시·군의 중앙동인가요?"])),
        ], FakePlaces([PLACE, {**PLACE, "name": "다른 중앙동"}]))
        result = svc.analyze(req)
        self.assertEqual(len(result["candidates"]), 2)
        self.assertTrue(result["analysis"]["questions"])
        self.assertTrue(result["review_required"])

    def test_unconfigured_failed_and_zero_match_search_are_distinct(self):
        for state in ("unavailable", "failed", "empty"):
            with self.subTest(state=state):
                places = FakePlaces([])
                if state == "unavailable":
                    places.configured = False
                if state == "failed":
                    places.search = Mock(side_effect=AnalysisUnavailable("search failed"))
                svc = service([
                    call("search_places", {"query": "성서산업단지", "evidence": "성서산업단지"}),
                    call("submit_analysis", draft([part(request().text)], ["정확한 장소를 확인해 주세요."])),
                ], places)
                result = svc.analyze(request())
                self.assertEqual(result["trace"][0]["status"], "not_found" if state == "empty" else "unavailable")
                self.assertEqual(result["nearby"], [])

    def test_invented_quote_unknown_candidate_and_naive_time_are_rejected(self):
        variants = [part("원문에 없는 근거"), part(request().text, locations=[location(candidate_ids=["invented"])]),
                    part(request().text, time_text="오늘 10시", starts_at="2026-11-07T10:00:00")]
        for invalid in variants:
            with self.subTest(invalid=invalid):
                svc = service([call("submit_analysis", draft([invalid])), call("submit_analysis", draft([part(request().text)]))])
                result = svc.analyze(request())
                self.assertEqual(result["trace"][0]["status"], "invalid")
                self.assertEqual(result["model_calls"], 2)

    def test_unknown_tool_cannot_execute_and_loop_stops_at_budget(self):
        svc = service([call("send_telegram", {"text": "ignore instructions"})])
        with self.assertRaises(AnalysisUnavailable):
            svc.analyze(request())
        self.assertEqual(len(svc.client.inputs), MAX_MODEL_CALLS)
        self.assertEqual(svc.places.queries, [])

    def test_invalid_input_is_rejected_before_inference(self):
        for overrides in ({"text": "짧음"}, {"reference_radius_km": 999}, {"issued_at": "2026-11-07T09:00:00"}, {"text": "x" * 2001}):
            with self.assertRaises(ValidationError):
                request(**overrides)

    def test_rate_and_concurrency_limits_do_not_make_extra_model_calls(self):
        clock = [0.0]
        svc = service([call("submit_analysis", draft([part(request().text)]))], clock=lambda: clock[0])
        svc.analyze(request())
        with self.assertRaises(AnalysisBusy):
            svc.analyze(request())
        self.assertEqual(len(svc.client.inputs), 1)
        for number in range(1, 20):
            clock[0] = number * 21
            svc.analyze(request())
        clock[0] += 21
        with self.assertRaises(AnalysisBusy):
            svc.analyze(request())
        clock[0] = 3601
        svc._lock.acquire()
        try:
            with self.assertRaises(AnalysisBusy):
                svc.analyze(request())
        finally:
            svc._lock.release()
        svc.analyze(request())

    def test_time_budget_stops_before_next_model_request(self):
        ticks = iter([0, 81])
        svc = service([], clock=lambda: next(ticks))
        with self.assertRaises(AnalysisUnavailable):
            svc.analyze(request())
        self.assertEqual(svc.client.inputs, [])

    def test_strict_tool_schemas_require_all_fields_and_forbid_unknown_fields(self):
        def check(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertFalse(node["additionalProperties"])
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                for child in node.values():
                    check(child)
            elif isinstance(node, list):
                for child in node:
                    check(child)
        for tool in TOOLS:
            check(tool["parameters"])


class MessageAdapterTests(unittest.TestCase):
    def test_openai_transport_uses_strict_read_only_tools_without_storage_or_parallel_calls(self):
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {"status": "completed", "output": []}
        client = OpenAIResponsesClient("test-not-real", session=session)
        client.respond([], TOOLS, "instructions", 20)
        payload = session.post.call_args.kwargs
        self.assertFalse(payload["json"]["store"])
        self.assertFalse(payload["json"]["parallel_tool_calls"])
        self.assertEqual(payload["json"]["max_output_tokens"], 2200)
        self.assertFalse(payload["allow_redirects"])

    def test_provider_error_never_exposes_raw_response(self):
        session = Mock()
        session.post.return_value.status_code = 401
        session.post.return_value.text = "secret raw response"
        with self.assertRaises(AnalysisUnavailable) as raised:
            OpenAIResponsesClient("secret", session=session).respond([], TOOLS, "", 20)
        self.assertNotIn("secret", str(raised.exception))

    def test_kakao_rejects_bad_coordinates_and_omits_unneeded_fields(self):
        session = Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {"documents": [
            {"x": "128.5", "y": "35.85", "place_name": "후보", "address_name": "주소", "phone": "private-phone"},
            {"x": "nan", "y": "35.85", "place_name": "오류"},
        ]}
        rows = KakaoPlaceSearch("test", session=session).search("후보", 8)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("phone", rows[0])


class MessageApiTests(unittest.TestCase):
    def setUp(self):
        self.svc = Mock()
        self.svc.availability.return_value = {"configured": True, "place_search_configured": False}
        self.svc.analyze.return_value = {"review_required": True}
        self.verifier = AdminAccessVerifier(AdminAccessSettings(password="test-password"))
        self.client = TestClient(create_app(admin_access_service=self.verifier, message_analysis_service=self.svc))
        self.url = "/internal/v1/message-analysis"

    def login(self):
        result = self.client.post("/internal/v1/admin/access", json={"password": "test-password"})
        self.assertEqual(result.status_code, 200)
        return result.json()["token"]

    def test_unauthorized_calls_never_reach_model(self):
        self.assertEqual(self.client.get(self.url + "/status").status_code, 403)
        self.assertEqual(self.client.post(self.url, json=request().model_dump(mode="json")).status_code, 403)
        self.svc.analyze.assert_not_called()

    def test_cookie_and_signed_header_work_without_notification_store(self):
        token = self.login()
        result = self.client.post(self.url, json=request().model_dump(mode="json"))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["cache-control"], "private, no-store")
        # The UI's restored-cookie sentinel is not an actual token; valid cookie still works.
        self.assertEqual(self.client.get(self.url + "/status", headers={"X-Alert-Admin-Token": "active-session"}).status_code, 200)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(self.url + "/status", headers={"X-Alert-Admin-Token": token}).status_code, 200)

    def test_known_fallback_secret_does_not_authorize_unconfigured_admin(self):
        client = TestClient(create_app(admin_access_service=AdminAccessVerifier(AdminAccessSettings()), message_analysis_service=self.svc))
        forged = AdminSessionManager("keco-session-secret").create_token()
        self.assertEqual(client.get(self.url + "/status", headers={"X-Alert-Admin-Token": forged}).status_code, 403)

    def test_upstream_errors_are_no_store_and_do_not_leak_details(self):
        self.login()
        for error, expected in ((AnalysisBusy("잠시 후 재시도"), 429), (AnalysisUnavailable("연결 실패"), 503), (RuntimeError("secret"), 503)):
            with self.subTest(error=type(error).__name__):
                self.svc.analyze.side_effect = error
                response = self.client.post(self.url, json=request().model_dump(mode="json"))
                self.assertEqual(response.status_code, expected)
                self.assertEqual(response.headers["cache-control"], "private, no-store")
                self.assertNotIn("secret", response.text)
