import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.evaluate_disaster_messages import check_case, evaluate, main, select_examples, write_report
from safety_dashboard.adapters.openai_messages import OpenAIConnectionError, OpenAIResponsesClient
from tests.test_message_analysis import EXAMPLES, draft, part, request


def result(parts):
    return {"analysis": draft(parts), "review_required": True, "trace": [], "nearby": []}


class EvaluationTests(unittest.TestCase):
    def test_school_destination_cannot_be_replaced_by_general_sports_ground(self):
        example = next(row for row in EXAMPLES if row["id"] == "destination")
        response = result([part(example["text"], locations=[{
            "text": "성서초등학교 운동장", "role": "evacuation_destination", "candidate_ids": ["P1"], "evidence": example["text"]}])])
        response["candidates"] = [{"id": "P1", "query": "대구 성서초등학교", "category_group_code": ""}]
        self.assertFalse(check_case(example, response, with_places=True)["destination_school_kind_matches"])
        response["candidates"][0]["category_group_code"] = "SC4"
        self.assertTrue(check_case(example, response, with_places=True)["destination_school_kind_matches"])

    def test_reference_lookup_requires_matching_place_kind_and_actual_lookup(self):
        example = EXAMPLES[1]
        response = result([part(example["text"], locations=[{
            "text": "성서산업단지", "role": "incident_site", "candidate_ids": ["P1"], "evidence": "성서산업단지"}])])
        response["candidates"] = [{"id": "P1", "query": "대구 성서산업단지", "role": "incident_site",
                                   "scope_matches_source": True, "category_name": "스포츠 > 체육관"}]
        response["trace"] = [{"tool": "find_nearby_facilities", "status": "ok", "role": "incident_site", "candidate_id": "P1"}]
        self.assertFalse(check_case(example, response, with_places=True)["primary_place_kind_matches"])
        response["candidates"][0]["category_name"] = "서비스,산업 > 산업단지"
        self.assertTrue(check_case(example, response, with_places=True)["primary_place_kind_matches"])
        response["trace"] = []
        self.assertFalse(check_case(example, response, with_places=True)["reference_facility_lookup_exercised"])

    def test_live_place_checks_reject_school_lookup_and_unscoped_zero_facility_lookup(self):
        example = next(row for row in EXAMPLES if row["id"] == "ambiguous")
        response = result([part(example["text"], "active_restriction")])
        response["analysis"]["questions"] = ["어느 시·군의 중앙동인가요?"]
        response["trace"] = [{"tool": "find_nearby_facilities", "status": "ok", "candidate_id": "P1", "role": "restricted_area"}]
        response["candidates"] = [{"id": "P1", "scope_matches_source": False, "role": "restricted_area"}]
        # A zero-result lookup is still a lookup at an invented/unscoped city.
        response["nearby"] = [{"candidate_id": "P1", "total_count": 0, "facilities": []}]
        checks = check_case(example, response, with_places=True)
        self.assertFalse(checks["auditable_facility_lookup_scope"])
        self.assertFalse(checks["no_city_guess_facility_lookup"])
        response["trace"][0]["role"] = "evacuation_destination"
        response["candidates"][0].update(role="evacuation_destination", scope_matches_source=True)
        self.assertFalse(check_case(example, response, with_places=True)["auditable_facility_lookup_scope"])

    def test_live_provider_failures_do_not_pass_as_location_verification(self):
        example = EXAMPLES[1]
        response = result([part(example["text"])])
        response["trace"] = [{"tool": "search_places", "role": "incident_site", "status": "unavailable"}]
        checks = check_case(example, response, with_places=True)
        self.assertFalse(checks["no_place_provider_failures"])
        self.assertFalse(checks["primary_place_search_attempted"])

    def test_locally_rejected_search_is_not_mistaken_for_provider_outage(self):
        example = EXAMPLES[1]
        response = result([part(example["text"])])
        response["trace"] = [
            {"tool": "search_places", "status": "invalid"},
            {"tool": "search_places", "role": "incident_site", "status": "ok"},
        ]
        checks = check_case(example, response, with_places=True)
        self.assertTrue(checks["no_place_provider_failures"])
        self.assertTrue(checks["primary_place_search_attempted"])
        response["trace"].append({"tool": "search_places", "role": "incident_site", "status": "unavailable"})
        self.assertFalse(check_case(example, response, with_places=True)["no_place_provider_failures"])

    def test_paid_batch_cannot_expand_when_ui_examples_are_added(self):
        self.assertEqual(len(select_examples(EXAMPLES, "all")), 6)
        self.assertEqual([row["id"] for row in select_examples(EXAMPLES, "event")], ["event"])
        for changed in (EXAMPLES + [EXAMPLES[0]], EXAMPLES[:-1], EXAMPLES[:-1] + [EXAMPLES[0]]):
            with self.assertRaises(ValueError):
                select_examples(changed, "all")

    def test_partial_release_checks_fail_when_both_segments_are_called_released(self):
        example = next(row for row in EXAMPLES if row["id"] == "partial_release")
        correct = [part("가람교 해제", "release"), part("푸른교 계속 통제", "active_restriction")]
        correct[0].update(ends_at="2026-11-07T15:00:00+09:00", time_text="15시")
        correct[1]["locations"] = [{"text": "푸른교", "role": "restricted_area", "evidence": "푸른교", "candidate_ids": []}]
        self.assertTrue(all(check_case(example, result(correct)).values()))
        incorrect = copy.deepcopy(correct)
        incorrect[1]["intent"] = "release"
        checks = check_case(example, result(incorrect))
        self.assertFalse(checks["still_restricted_segment"])
        self.assertFalse(checks["expected_intents"])

    def test_prevention_does_not_pass_if_agent_unnecessarily_looks_up_facilities(self):
        example = EXAMPLES[0]
        response = result([part(example["text"], "prevention")])
        self.assertTrue(all(check_case(example, response).values()))
        response["trace"] = [{"tool": "find_nearby_facilities"}]
        self.assertFalse(check_case(example, response)["no_incident_or_unnecessary_lookup"])

    def test_batch_stops_on_auth_failure_without_charging_for_remaining_cases(self):
        service = Mock()
        service.analyze.side_effect = OpenAIConnectionError("API 인증 실패")
        client = Mock()
        client.usage_snapshot.side_effect = [dict(requests=0), dict(requests=1)]
        with contextlib.redirect_stdout(io.StringIO()):
            rows = evaluate(EXAMPLES, service, client)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["usage"]["requests"], 1)
        self.assertEqual(service.analyze.call_count, 1)

    def test_batch_observes_start_interval_and_does_not_send_expected_answers_to_model(self):
        service = Mock()
        service.analyze.return_value = result([part(request("prevention").text, "prevention")])
        client = Mock()
        client.usage_snapshot.return_value = dict(requests=0)
        seconds = [0.0]
        pauses = []
        def pause(delay):
            pauses.append(delay)
            seconds[0] += delay
        with contextlib.redirect_stdout(io.StringIO()):
            rows = evaluate([EXAMPLES[0], EXAMPLES[0]], service, client, pause=pause, clock=lambda: seconds[0])
        self.assertEqual(len(rows), 2)
        self.assertEqual(pauses, [20.1])
        sent = service.analyze.call_args.args[0].model_dump()
        self.assertNotIn("expected_intents", sent)
        self.assertNotIn("expected_start", sent)

    def test_live_flag_and_missing_key_never_make_external_requests(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main([])
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            self.assertEqual(main(["--live", "--output-dir", directory]), 1)
            report = json.loads((Path(directory) / "results.json").read_text())
            self.assertEqual(report["cases"], [])
            self.assertIn("OPENAI_API_KEY", report["error"])

    def test_reports_redact_secret_values_and_record_unverified_place_search(self):
        report = {"model": "fake", "status": "error", "cases": [], "place_search_mode": "disabled", "error": "secret-value"}
        with tempfile.TemporaryDirectory() as directory:
            write_report(report, Path(directory), ("secret-value",))
            for path in Path(directory).iterdir():
                text = path.read_text()
                self.assertNotIn("secret-value", text)
                self.assertIn("[REDACTED]", text)
            self.assertIn("미검증", (Path(directory) / "summary.md").read_text())

    def test_usage_is_counted_even_when_the_model_response_is_incomplete(self):
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {
            "status": "incomplete", "output": [],
            "usage": {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 20}, "output_tokens": 50, "total_tokens": 150},
        }
        client = OpenAIResponsesClient("not-real", session=session)
        with self.assertRaisesRegex(RuntimeError, "완료"):
            client.respond([], [], "", 20)
        self.assertEqual(client.usage_snapshot(), dict(requests=1, usage_reports=1, input_tokens=100, cached_input_tokens=20, output_tokens=50, total_tokens=150))
