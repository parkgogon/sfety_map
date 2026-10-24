import unittest
from unittest.mock import Mock, patch

import requests

from safety_dashboard.adapters.kma import (
    KMA_PUBLIC_DELAY_MESSAGE,
    KmaWarningProvider,
)
from safety_dashboard.adapters.kma_diagnostics import KmaFailureDiagnoser
from safety_dashboard.domain import DataHealth, KmaFailureCategory
from safety_dashboard.domain.models import KmaFailureDiagnostic
from safety_dashboard.domain.risk_policy import RiskPolicy


class KmaFailureDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = RiskPolicy.load("safety_dashboard/config/risk_policy.toml")

    def provider(self):
        return KmaWarningProvider("private-kma-key", self.policy, timeout=0.1)

    @staticmethod
    def response(status, text=""):
        response = Mock()
        response.status_code = status
        response.text = text
        response.raise_for_status.side_effect = (
            requests.HTTPError() if status >= 400 else None
        )
        return response

    @patch("safety_dashboard.adapters.kma.requests.get")
    def test_http_failures_are_classified_without_exposing_key(self, get):
        cases = (
            (400, KmaFailureCategory.AUTH_CONFIG),
            (401, KmaFailureCategory.AUTH_CONFIG),
            (429, KmaFailureCategory.QUOTA),
            (503, KmaFailureCategory.KMA_SERVER),
        )
        for status, category in cases:
            with self.subTest(status=status):
                get.return_value = self.response(status)
                feed = self.provider().fetch_active()
                self.assertEqual(feed.health, DataHealth.ERROR)
                self.assertEqual(feed.message, KMA_PUBLIC_DELAY_MESSAGE)
                self.assertEqual(feed.diagnostic.category, category)
                self.assertNotIn("private-kma-key", repr(feed))

    @patch("safety_dashboard.adapters.kma.requests.get")
    def test_blank_html_and_unknown_200_are_not_treated_as_no_warning(self, get):
        for body in ("", "<html>gateway error</html>", "unexpected response"):
            with self.subTest(body=body):
                get.return_value = self.response(200, body)
                feed = self.provider().fetch_active()
                self.assertEqual(feed.health, DataHealth.ERROR)
                self.assertEqual(
                    feed.diagnostic.category,
                    KmaFailureCategory.RESPONSE_FORMAT,
                )

    @patch("safety_dashboard.adapters.kma.requests.get")
    def test_valid_header_only_response_means_no_active_warning(self, get):
        get.return_value = self.response(
            200,
            "# REG_UP,REG_UP_KO,REG_ID,REG_KO,TM_FC,TM_EF,WRN,LVL,CMD,ED_TM",
        )
        feed = self.provider().fetch_active()
        self.assertEqual(feed.health, DataHealth.LIVE)
        self.assertEqual(feed.warnings, ())

    @patch("safety_dashboard.adapters.kma.requests.get")
    def test_connect_timeout_starts_as_unknown(self, get):
        get.side_effect = requests.ConnectTimeout("secret-url-data")
        feed = self.provider().fetch_active()
        self.assertEqual(feed.diagnostic.category, KmaFailureCategory.UNKNOWN)
        self.assertEqual(feed.diagnostic.evidence, "ConnectTimeout")

    def test_control_probes_distinguish_kma_route_and_cloud_egress(self):
        initial = KmaFailureDiagnostic(
            KmaFailureCategory.UNKNOWN,
            "KMA API와 연결하지 못함",
            "ConnectTimeout",
        )
        diagnoser = KmaFailureDiagnoser()
        with patch.object(diagnoser, "_probe", return_value=True):
            route = diagnoser.diagnose(initial)
        self.assertEqual(route.category, KmaFailureCategory.KMA_ROUTE)

        with patch.object(diagnoser, "_probe", return_value=False):
            egress = diagnoser.diagnose(initial)
        self.assertEqual(egress.category, KmaFailureCategory.CLOUD_EGRESS)


if __name__ == "__main__":
    unittest.main()
