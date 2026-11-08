import datetime as dt
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import yaml

from scripts.verify_safetydata_runtime import probe, handler_class
from scripts.invoke_safetydata_runtime import main as invoke


DAY = dt.date(2026, 11, 8)


def message(identifier, *, day=DAY, region="대구광역시 달서구"):
    return {"SN": identifier, "MSG_CN": "private-message-must-not-export", "CRT_DT": day.isoformat()+" 12:00:00", "RCPTN_RGN_NM": region}


def page(*items):
    return {"body": list(items), "totalCount": len(items)}


class RuntimeProbeTests(unittest.TestCase):
    def test_real_sample_dates_region_pagination_and_stable_head_are_checked_without_exporting_content(self):
        calls = []
        def fetch(key, day, *, region, page: int, size):
            calls.append((key, day, region, page, size))
            return globals()["page"](*(message(f"private-id-{page}-{i}") for i in range(2)))
        result = probe("private-key", fetch=fetch, today=DAY)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["api_calls"], 5)
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(calls[2][2], "대구광역시")
        self.assertTrue(all(call[4] == 2 for call in calls))
        self.assertEqual(calls[-1][1], DAY-dt.timedelta(days=1))
        for secret in ("private-key", "private-message", "private-id", "달서구"):
            self.assertNotIn(secret, json.dumps(result))

    def test_empty_today_looks_back_and_total_requests_are_at_most_six(self):
        attempts = []
        def fetch(key, day, **kwargs):
            attempts.append(day)
            if day > DAY-dt.timedelta(days=2):
                return page()
            return page(*(message(f'{kwargs["page"]}-{i}', day=day) for i in range(2)))
        result = probe("key", fetch=fetch, today=DAY)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["api_calls"], 6)
        self.assertEqual(attempts[:3], [DAY, DAY-dt.timedelta(days=1), DAY-dt.timedelta(days=2)])

    def test_no_recent_samples_remains_inconclusive(self):
        fetch = Mock(return_value=page())
        result = probe("key", fetch=fetch, today=DAY)
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(result["reason"], "no_sample_in_recent_three_days")
        self.assertEqual(fetch.call_count, 4)

    def test_unfiltered_control_distinguishes_date_filter_or_historical_data_from_no_records(self):
        def fetch(key, day, **kwargs):
            return page(message("private-id")) if day is None else page()
        result = probe("key", fetch=fetch, today=DAY)
        self.assertEqual(result["api_calls"], 4)
        self.assertEqual(result["reason"], "unfiltered_sample_requires_date_review")
        self.assertEqual(result["control_sample_dates"], [DAY.isoformat()])
        self.assertNotIn("private-id", json.dumps(result))

    def test_page_overlap_wrong_dates_and_wrong_region_do_not_pass(self):
        for failure in ("page", "date", "region"):
            def fetch(key, day, **kwargs):
                value = message("same" if failure == "page" else str(kwargs["page"]),
                                day=DAY-dt.timedelta(days=1) if failure == "date" else DAY,
                                region="서울특별시" if failure == "region" and kwargs["region"] else "대구광역시")
                return page(value)
            self.assertEqual(probe("key", fetch=fetch, today=DAY)["status"], "needs_contract_review")

    def test_head_change_is_explicit_and_does_not_restart_a_paid_or_unbounded_loop(self):
        fetch = Mock(side_effect=[page(message("first")), page(message("second")), page(message("first")), page(message("changed")), page(message("prior"))])
        result = probe("key", fetch=fetch, today=DAY)
        self.assertFalse(result["checks"]["head_stable"])
        self.assertEqual(fetch.call_count, 5)

    def test_prior_day_range_accepts_start_date_semantics_but_rejects_older_rows(self):
        for invalid in (False, True):
            def fetch(key, day, **kwargs):
                actual = DAY-dt.timedelta(days=2) if invalid and day < DAY else DAY
                return page(*(message(f'{kwargs["page"]}-{i}', day=actual) for i in range(2)))
            result = probe("key", fetch=fetch, today=DAY)
            self.assertEqual(result["checks"]["prior_date_range_matches"], not invalid)
            self.assertLessEqual(result["api_calls"], 6)

    def test_missing_runtime_key_and_provider_errors_never_export_secret_or_payload(self):
        fetch = Mock(side_effect=RuntimeError("private-key"))
        self.assertEqual(probe("", fetch=fetch, today=DAY)["api_calls"], 0)
        fetch.assert_not_called()
        result = probe("private-key", fetch=fetch, today=DAY)
        self.assertEqual(result["reason"], "probe_failed")
        self.assertNotIn("private-key", json.dumps(result))

    def test_cached_http_probe_runs_only_once_and_rejects_request_bodies(self):
        run = Mock(return_value={"status": "inconclusive", "api_calls": 3})
        handler = handler_class(run)
        request = handler.__new__(handler)
        request.path, request.headers, request.wfile = "/verify", {"Content-Length": "0"}, io.BytesIO()
        request.send_response = Mock(); request.send_header = Mock(); request.end_headers = Mock(); request.send_error = Mock()
        request.do_POST(); request.do_POST()
        run.assert_called_once()
        request.headers = {"Content-Length": "20"}
        request.do_POST()
        request.send_error.assert_called_once_with(400)

    def test_private_invoker_rejects_other_services_before_any_network_call(self):
        with patch.dict("os.environ", {"CHECK_URL": "https://safety-dashboard-api.example.com"}, clear=True), patch("urllib.request.build_opener") as opener:
            with self.assertRaises(ValueError): invoke()
            opener.assert_not_called()

    def test_runtime_probe_is_explicit_only_and_never_binds_model_admin_or_delivery_keys(self):
        root = Path(__file__).resolve().parents[1]
        source = (root/".github/workflows/check-message-review-deployment.yml").read_text()
        config = yaml.safe_load(source)
        job = config["jobs"]["official-feed"]
        self.assertIn("inputs.mode == 'official-feed'", job["if"])
        self.assertIn("github.event_name == 'workflow_dispatch'", job["if"])
        deploy = next(step["run"] for step in job["steps"] if step.get("name", "").startswith("Run private"))
        self.assertIn("--no-allow-unauthenticated", deploy)
        self.assertIn("SAFETY_DATA_API_KEY:1", deploy)
        for forbidden in ("OPENAI_API_KEY", "ADMIN_ACCESS_PASSWORD", "TELEGRAM", "dispatch", "run jobs"):
            self.assertNotIn(forbidden, deploy)
        cleanup = next(step for step in job["steps"] if step.get("name", "").startswith("Remove only"))
        self.assertEqual(cleanup["if"], "always()")
        self.assertIn('"$CHECK_SERVICE"', cleanup["run"])
