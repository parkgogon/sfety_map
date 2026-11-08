import datetime as dt
import json
import unittest
from unittest.mock import Mock, MagicMock, patch

from scripts.check_safetydata_connection import check, gcloud, read_api, summarize, CheckFailed, PROJECT, SECRET, RUNTIME, KST


class SafetyDataConnectionTests(unittest.TestCase):
    def setUp(self):
        self.commands = []
        self.key = "test-private-key-never-print"
        def run(args):
            self.commands.append(args)
            if "describe" in args:
                return json.dumps({"name": "projects/531222653541/secrets/SAFETY_DATA_API_KEY/versions/2", "state": "ENABLED"})
            if "access" in args:
                return self.key
            return ""
        self.run = run
        self.payload = {"body": [{"SN": "test-id", "MSG_CN": "private-text", "CRT_DT": "2026-11-08 10:00:00", "RCPTN_RGN_NM": "대구광역시"}]}

    def test_owner_grants_only_runtime_secret_access_and_reads_once_without_key_in_report(self):
        fetch = Mock(return_value=self.payload)
        report = check(grant_runtime=True, run=self.run, fetch=fetch)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["version"], "2")
        self.assertTrue(report["runtime_access_granted"])
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[0], self.key)
        grants = [args for args in self.commands if "add-iam-policy-binding" in args]
        self.assertEqual(grants, [["secrets", "add-iam-policy-binding", SECRET, "--member=serviceAccount:"+RUNTIME,
            "--role=roles/secretmanager.secretAccessor", "--condition=None", "--format=none"]])
        self.assertEqual([args for args in self.commands if "access" in args][0][3], "2")
        for private in (self.key, "private-text", "test-id"):
            self.assertNotIn(private, json.dumps(report))
        self.assertNotIn(self.key, str(self.commands))
        self.assertEqual((report["deployments"], report["messages_sent"], report["collection_started"]), (0, 0, False))

    def test_without_grant_flag_only_reads_and_does_not_deploy_or_start_collection(self):
        report = check(run=self.run, fetch=Mock(return_value={"body": {"totalCount": 0, "items": []}}))
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["api_result"], "valid_empty_response")
        self.assertFalse(report["runtime_access_granted"])
        self.assertFalse(any("add-iam-policy-binding" in args for args in self.commands))

    def test_disabled_or_missing_secret_stops_before_grant_read_or_api_call(self):
        fetch = Mock()
        run = Mock(return_value=json.dumps({"name": "versions/1", "state": "DISABLED"}))
        report = check(grant_runtime=True, run=run, fetch=fetch)
        self.assertEqual(report["reason"], "enabled_secret_version_required")
        self.assertEqual(run.call_count, 1)
        fetch.assert_not_called()

    def test_permission_failure_does_not_start_api_or_reveal_subprocess_stderr(self):
        fetch = Mock()
        report = check(grant_runtime=True, run=Mock(side_effect=CheckFailed("permission_denied")), fetch=fetch)
        self.assertEqual(report["reason"], "permission_denied")
        fetch.assert_not_called()
        with patch("scripts.check_safetydata_connection.subprocess.run", return_value=Mock(returncode=1, stderr="PERMISSION_DENIED "+self.key)):
            with self.assertRaises(CheckFailed) as error: gcloud(["secrets", "versions", "access", "1"])
            self.assertNotIn(self.key, str(error.exception))

    def test_gcloud_value_is_captured_without_file_or_http_logging(self):
        with patch("scripts.check_safetydata_connection.subprocess.run", return_value=Mock(returncode=0, stdout=self.key)) as run:
            self.assertEqual(gcloud(["secrets", "versions", "access", "1"]), self.key)
            args, kwargs = run.call_args
            self.assertIn("--project="+PROJECT, args[0])
            self.assertTrue(kwargs["capture_output"])
            self.assertEqual(kwargs["env"]["CLOUDSDK_CORE_LOG_HTTP"], "false")
            self.assertEqual(kwargs["env"]["CLOUDSDK_CORE_DISABLE_FILE_LOGGING"], "true")

    def test_raw_provider_exceptions_and_error_payloads_are_not_exported(self):
        report = check(run=self.run, fetch=Mock(side_effect=RuntimeError(self.key)))
        self.assertEqual(report["status"], "blocked")
        self.assertNotIn(self.key, json.dumps(report))
        report = check(run=self.run, fetch=Mock(return_value={"header": {"resultCode": "30", "errMsg": self.key}}))
        self.assertEqual(report["reason"], "official_api_rejected_request")
        self.assertNotIn(self.key, json.dumps(report))

    def test_unrecognized_response_cannot_masquerade_as_no_disaster_messages(self):
        for payload in ({"body": []}, {"arbitrary": self.key}, "non-json-object"):
            with self.assertRaises(CheckFailed): summarize(payload)
        with self.assertRaises(CheckFailed): summarize({"body": [{"SN": "1", "MSG_CN": "text"}]})

    def test_fixed_provider_request_is_one_page_with_no_redirects_and_errors_are_safe(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(self.payload).encode()
        day = dt.date(2026, 11, 8)
        with patch("scripts.check_safetydata_connection.urllib.request.build_opener", return_value=opener):
            self.assertEqual(read_api(self.key, day), self.payload)
        request = opener.open.call_args.args[0]
        self.assertTrue(request.full_url.startswith("https://www.safetydata.go.kr/V2/api/DSSP-IF-00247?"))
        self.assertIn("numOfRows=1", request.full_url)
        self.assertIn("crtDt=20261108", request.full_url)
        self.assertEqual(opener.open.call_count, 1)
        with patch("scripts.check_safetydata_connection.urllib.request.build_opener", side_effect=RuntimeError(self.key)):
            with self.assertRaises(CheckFailed) as error: read_api(self.key, day)
            self.assertNotIn(self.key, str(error.exception))
