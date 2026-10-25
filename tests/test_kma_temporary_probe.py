"""임시 진단 도구의 자원 범위·정리·출력만 검증하며 gcloud/외부 통신은 가짜다."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

import requests


_FILE = Path(__file__).resolve().parents[1] / "docs/evidence/2026-10-25/weather-diagnosis/run_temporary_kma_probe.py"
_SPEC = importlib.util.spec_from_file_location("kma_temporary_probe", _FILE)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)
SOURCE = {"revision": "safety-dashboard-api-test", "image": "registry/api@sha256:example",
          "serviceAccount": "runtime@example.iam.gserviceaccount.com"}


class TemporaryKmaProbeTests(unittest.TestCase):
    def test_default_does_not_create_or_execute(self):
        with patch.object(probe.shutil, "which", return_value="/mock/gcloud"), \
             patch.object(probe, "production_image", return_value=SOURCE), \
             patch.object(probe, "run_probe") as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(probe.main([]), 0)
            run.assert_not_called()

    def test_requires_actual_unsplit_traffic(self):
        with patch.object(probe, "read_json", return_value={"status": {"traffic": [
            {"revisionName": "safety-dashboard-api-a", "percent": 50},
            {"revisionName": "safety-dashboard-api-b", "percent": 50}]}}):
            with self.assertRaisesRegex(RuntimeError, "traffic is split"):
                probe.production_image("project", "region")

    def test_selects_active_revision_and_immutable_image(self):
        service = {"status": {"latestReadyRevisionName": "safety-dashboard-api-new",
                              "traffic": [{"revisionName": "safety-dashboard-api-active", "percent": 100}]}}
        revision = {"spec": {"serviceAccountName": "runtime", "containers": [{"image": "registry/api:tag"}]},
                    "status": {"imageDigest": "registry/api@sha256:actual"}}
        with patch.object(probe, "read_json", side_effect=[service, revision]) as read:
            actual = probe.production_image("project", "region")
        self.assertIn("safety-dashboard-api-active", read.call_args.args[0])
        self.assertEqual(actual["image"], "registry/api@sha256:actual")

    def test_rejects_different_network_before_any_job(self):
        service = {"status": {"traffic": [{"revisionName": "safety-dashboard-api-active", "percent": 100}]}}
        revision = {"metadata": {"annotations": {"run.googleapis.com/vpc-access-connector": "connector"}}}
        with patch.object(probe, "read_json", side_effect=[service, revision]):
            with self.assertRaisesRegex(RuntimeError, "VPC"):
                probe.production_image("project", "region")

    def test_job_only_and_cleanup_after_success_with_log_delay(self):
        responses = [{"status": {"latestCreatedExecution": {"name": "diagnostic-execution"}}},
                     [], [{"textPayload": probe.PREFIX + '{"checks": []}'}]]
        with patch.object(probe, "command", return_value=subprocess.CompletedProcess([], 0, "", "")) as command, \
             patch.object(probe, "read_json", side_effect=responses), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            pause = Mock()
            result = probe.run_probe("project", "region", SOURCE, pause=pause)
        calls = [call.args[0] for call in command.call_args_list]
        self.assertEqual([call[:3] for call in calls], [["run", "jobs", "create"],
                         ["run", "jobs", "execute"], ["run", "jobs", "delete"]])
        self.assertEqual(len({call[3] for call in calls}), 1)
        self.assertTrue(calls[0][3].startswith("kma-net-diag-"))
        self.assertNotIn("--set-secrets", calls[0])
        self.assertNotIn("--set-env-vars", calls[0])
        self.assertIn("--args=^@^-c@" + probe.PAYLOAD, calls[0])
        pause.assert_called_once_with(3)
        self.assertEqual(result["probeResults"], [{"checks": []}])
        self.assertTrue(json.loads(output.getvalue())["deleteCommandSucceeded"])

    def test_cleanup_attempted_even_if_create_times_out(self):
        with patch.object(probe, "command", side_effect=[subprocess.TimeoutExpired("gcloud", 1),
                          subprocess.CompletedProcess([], 0, "", "")]) as command, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.TimeoutExpired):
                probe.run_probe("project", "region", SOURCE)
        self.assertEqual(command.call_args.args[0][:3], ["run", "jobs", "delete"])

    def test_authenticated_job_binds_only_fixed_kma_secret(self):
        source = {**SOURCE, "kmaSecretReference": {"name": "KMA_API_KEY", "version": "1"}}
        responses = [{"status": {"latestCreatedExecution": {"name": "diagnostic-execution"}}},
                     [{"textPayload": probe.PREFIX + '{"authenticatedMode": true}'}]]
        with patch.object(probe, "command", return_value=subprocess.CompletedProcess([], 0, "", "")) as command, \
             patch.object(probe, "read_json", side_effect=responses), contextlib.redirect_stdout(io.StringIO()):
            probe.run_probe("project", "region", source, authenticated=True)
        create = command.call_args_list[0].args[0]
        self.assertEqual(create[create.index("--set-secrets")+1], "KMA_API_KEY=KMA_API_KEY:1")
        self.assertEqual(create[create.index("--task-timeout")+1], "180s")
        self.assertNotIn("ADMIN_ACCESS_PASSWORD", str(create))
        self.assertNotIn("TELEGRAM_BOT_TOKEN", str(create))
        self.assertEqual(command.call_args.args[0][:3], ["run", "jobs", "delete"])

    def test_authenticated_mode_requires_fixed_reference_before_creation(self):
        with patch.object(probe, "command") as command:
            with self.assertRaisesRegex(RuntimeError, "fixed numeric"):
                probe.run_probe("project", "region", SOURCE, authenticated=True)
            command.assert_not_called()

    def test_cleanup_failure_is_explicit(self):
        with patch.object(probe, "command", side_effect=[RuntimeError("create failed"),
                          subprocess.TimeoutExpired("gcloud", 1)]), contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(RuntimeError, "create failed"):
                probe.run_probe("project", "region", SOURCE)
        self.assertFalse(json.loads(output.getvalue())["deleteCommandSucceeded"])

    def test_payload_preserves_tls_and_does_not_print_bodies_or_exception_values(self):
        sentinel = "PRIVATE_VALUE_MUST_NOT_APPEAR"
        response = Mock(status_code=403, headers={})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("requests.get", side_effect=[response, requests.ConnectTimeout(sentinel)]) as get, \
             patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("203.247.91.39", 443))]), \
             patch.dict(os.environ, {"HTTPS_PROXY": sentinel, "KMA_API_KEY": sentinel}), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            exec(compile(probe.PAYLOAD, "<diagnostic>", "exec"), {})
        self.assertNotIn(sentinel, output.getvalue())
        data = json.loads(output.getvalue()[len(probe.PREFIX):])
        self.assertEqual(data["checks"][1]["errorType"], "ConnectTimeout")
        self.assertEqual(len(get.call_args_list), 2)
        for call in get.call_args_list:
            self.assertTrue(call.args[0].startswith(("https://apihub.kma.go.kr/", "https://www.weather.go.kr/")))
            self.assertNotIn("?", call.args[0])
            self.assertTrue(call.kwargs.get("verify", True))
            self.assertFalse(call.kwargs["allow_redirects"])
            self.assertNotIn("proxies", call.kwargs)

    def test_stage_tracing_preserves_tcp_failure_and_restores_originals(self):
        import ssl
        import urllib3.util.connection
        response = Mock(status_code=200, headers={})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        sentinel = "PRIVATE_ERROR_MUST_NOT_APPEAR"
        def fake_get(url, **kwargs):
            if "apihub" in url:
                try:
                    urllib3.util.connection.create_connection(("apihub.kma.go.kr", 443), 7)
                except TimeoutError as error:
                    raise requests.ConnectTimeout(sentinel) from error
            else:
                urllib3.util.connection.create_connection(("www.weather.go.kr", 443), 7)
                ssl.SSLContext.wrap_socket(Mock(), Mock(), server_hostname="www.weather.go.kr")
            return response
        with patch("urllib3.util.connection.create_connection", side_effect=[TimeoutError(sentinel), Mock()]) as connect, \
             patch("ssl.SSLContext.wrap_socket", return_value=Mock()) as wrap, \
             patch("socket.getaddrinfo", return_value=[]), patch("requests.get", side_effect=fake_get), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            exec(compile(probe.PAYLOAD, "<diagnostic>", "exec"), {})
            self.assertIs(urllib3.util.connection.create_connection, connect)
            self.assertIs(ssl.SSLContext.wrap_socket, wrap)
        data = json.loads(output.getvalue()[len(probe.PREFIX):])
        self.assertNotIn(sentinel, output.getvalue())
        self.assertEqual(data["checks"][0]["stages"][0]["stage"], "tcp_connect")
        self.assertFalse(data["checks"][0]["stages"][0]["succeeded"])
        self.assertEqual([step["stage"] for step in data["checks"][1]["stages"]], ["tcp_connect", "tls_wrap"])
        self.assertTrue(all(step["succeeded"] for step in data["checks"][1]["stages"]))

    def test_tls_failure_is_separate_from_successful_tcp(self):
        import ssl
        import urllib3.util.connection
        def fake_get(url, **kwargs):
            urllib3.util.connection.create_connection(("target", 443), 7)
            try:
                ssl.SSLContext.wrap_socket(Mock(), Mock(), server_hostname="target")
            except TimeoutError as error:
                raise requests.ConnectTimeout("private TLS details") from error
        with patch("urllib3.util.connection.create_connection", return_value=Mock()), \
             patch("ssl.SSLContext.wrap_socket", side_effect=TimeoutError("private TLS details")), \
             patch("socket.getaddrinfo", return_value=[]), patch("requests.get", side_effect=fake_get), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            exec(compile(probe.PAYLOAD, "<diagnostic>", "exec"), {})
        data = json.loads(output.getvalue()[len(probe.PREFIX):])
        self.assertNotIn("private TLS details", output.getvalue())
        steps = data["checks"][0]["stages"]
        self.assertTrue(steps[0]["succeeded"])
        self.assertFalse(steps[1]["succeeded"])
        self.assertEqual(steps[1]["stage"], "tls_wrap")

    def test_authenticated_transport_excludes_key_body_and_redirect_query(self):
        from types import SimpleNamespace
        from safety_dashboard.domain.enums import DataHealth
        sentinel = "PRIVATE_AUTH_VALUE_MUST_NOT_APPEAR"
        response = Mock(status_code=302, headers={"Location": "https://example.test/return?authKey=" + sentinel})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        def grid_factory(key, scope, **kwargs):
            transport = kwargs["session"]
            def fetch(kind):
                transport.get("https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_latlon_api",
                              params={"authKey": key}, timeout=7)
                return SimpleNamespace(health=DataHealth.ERROR, points=[])
            return SimpleNamespace(fetch=fetch)
        observation = SimpleNamespace(health=DataHealth.ERROR)
        with patch.dict(os.environ, {"KMA_PROBE_AUTHENTICATED": "true", "KMA_API_KEY": sentinel}), \
             patch("requests.get", return_value=response) as get, \
             patch("socket.getaddrinfo", return_value=[]), \
             patch("safety_dashboard.adapters.weather_layers.load_monitoring_scope", return_value=Mock()), \
             patch("safety_dashboard.adapters.weather_layers.GridWeatherLayerProvider", side_effect=grid_factory), \
             patch("safety_dashboard.adapters.current_weather.CurrentWeatherProvider") as current, \
             patch("safety_dashboard.adapters.facility_csv.CsvFacilityRepository") as facilities, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            current.return_value.fetch.return_value = observation
            facilities.return_value.list_monitored.return_value = [SimpleNamespace(id="3077", location=Mock())]
            exec(compile(probe.PAYLOAD, "<diagnostic>", "exec"), {})
        data = json.loads(output.getvalue()[len(probe.PREFIX):])
        self.assertTrue(data["authenticatedMode"])
        self.assertTrue(data["kmaKeyConfigured"])
        self.assertNotIn(sentinel, output.getvalue())
        self.assertEqual(data["checks"][-1]["redirectTargetHost"], "example.test")
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertEqual(len(data["authenticatedProviders"]), 2)


if __name__ == "__main__":
    unittest.main()
