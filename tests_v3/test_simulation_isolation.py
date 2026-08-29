import datetime as dt
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from safety_dashboard.adapters.pdf_report import PdfReportRenderer
from safety_dashboard.adapters.weather_layers import load_monitoring_scope
from safety_dashboard.alerts.worker_app import _SnapshotProvider
from safety_dashboard.api.service import MonitoringApiService
from safety_dashboard.api.settings import ApiSettings
from safety_dashboard.domain import DataHealth, RiskGrade, WeatherLayerKind
from safety_dashboard.simulation.scenarios import MULTI_HAZARD_SCENARIO
from safety_dashboard.simulation.weather_layers import SimulationWeatherLayerProvider

KST = dt.timezone(dt.timedelta(hours=9))


class SimulationIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base_dir = Path(__file__).resolve().parent.parent
        cls.settings = ApiSettings.from_environment()
        cls.service = MonitoringApiService(cls.settings)
        cls.pdf_renderer = PdfReportRenderer(
            font_path=base_dir / "fonts" / "NotoSansKR-Bold.ttf",
            zone_geojson_path=cls.settings.zone_fallback_path,
        )
        cls.scope = load_monitoring_scope(cls.settings.zone_fallback_path)

    def test_simulation_snapshot_counts_and_consistency(self):
        """수용조건 2: 종합 시나리오 기준 특보 4건, 영향시설 31개소, 상 위험 10개소가 정확히 일치한다."""
        payload = self.service.monitoring(simulation=True)

        self.assertEqual(payload["status"]["health"], "SIMULATION")
        self.assertIsNotNone(payload["summary"])
        self.assertEqual(payload["summary"]["active_warning_count"], 4)
        self.assertEqual(payload["summary"]["affected_facility_count"], 31)
        self.assertEqual(payload["summary"]["high_risk_count"], 10)

        high_facilities = [
            f for f in payload["facilities"] if f["grade"] == "HIGH"
        ]
        self.assertEqual(len(high_facilities), 10)

        affected_facilities = [
            f for f in payload["facilities"] if f["grade"] not in {"NONE", "UNASSESSED", "UNAVAILABLE"}
        ]
        self.assertEqual(len(affected_facilities), 31)

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext is required")
    def test_simulation_pdf_rendering_contains_simulation_badge(self):
        """수용조건 1 & 4.6: 모의훈련 PDF 렌더링 시 모의훈련 표식을 전체 페이지에 유지한다."""
        snapshot = self.service.snapshot(simulation=True)

        pdf_bytes = self.pdf_renderer.render(
            snapshot=snapshot,
            scope_label="전체 소관시설 (모의훈련)",
        )

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 1000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        with tempfile.NamedTemporaryFile(suffix=".pdf") as report:
            report.write(pdf_bytes)
            report.flush()
            text = subprocess.run(
                ["pdftotext", "-layout", report.name, "-"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout

        pages = [page for page in text.split("\f") if page.strip()]
        self.assertGreaterEqual(len(pages), 2)
        for page_number, page in enumerate(pages, 1):
            self.assertIn("모의훈련", page, f"{page_number}페이지 훈련 표식 누락")

    def test_simulation_weather_layer_deterministic_and_unaffected_by_kma(self):
        """수용조건 3 & 4: 모의훈련 기상 그래픽은 결정적이며 실제 관측이 아님을 명시한다."""
        from safety_dashboard.api.serialization import serialize_weather_layer

        provider = SimulationWeatherLayerProvider(
            self.scope, scenario=MULTI_HAZARD_SCENARIO
        )
        moment = dt.datetime(2026, 8, 29, 12, 0, tzinfo=KST)
        wind = provider.fetch(WeatherLayerKind.WIND, moment)
        rain = provider.fetch(WeatherLayerKind.RAINFALL, moment)
        temp = provider.fetch(WeatherLayerKind.TEMPERATURE, moment)

        self.assertEqual(wind.health, DataHealth.SIMULATION)
        self.assertEqual(rain.health, DataHealth.SIMULATION)
        self.assertEqual(temp.health, DataHealth.SIMULATION)

        wind_payload = serialize_weather_layer(wind)
        self.assertFalse(wind_payload["actual_data"])
        self.assertEqual(wind_payload["status"], "SIMULATION")
        self.assertEqual(wind_payload["scenario_id"], "multi_hazard_demo")
        self.assertIn("모의훈련", wind_payload["source"])
        self.assertGreater(len(wind_payload["points"]), 0)

    def test_automatic_alert_worker_always_requests_live_snapshot(self):
        """수용조건 5: 자동알림 Worker는 모의훈련 snapshot을 요청하지 않는다."""

        class RecordingMonitoringService:
            def __init__(self) -> None:
                self.simulation_calls: list[bool] = []

            def snapshot(self, *, simulation: bool = False) -> object:
                self.simulation_calls.append(simulation)
                return object()

        service = RecordingMonitoringService()
        result = _SnapshotProvider(service).fetch()  # type: ignore[arg-type]

        self.assertIsNotNone(result)
        self.assertEqual(service.simulation_calls, [False])


if __name__ == "__main__":
    unittest.main()
