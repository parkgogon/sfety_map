import dataclasses
import math
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from safety_dashboard.adapters.facility_csv import FacilityDataError
from safety_dashboard.adapters.nearby_pdf_report import NearbyPdfReportRenderer
from safety_dashboard.api.app import create_app
from safety_dashboard.application.nearby_report import EARTH_RADIUS_METERS, NearbyReport, distance_meters
from safety_dashboard.domain.models import Facility, GeoPoint

ROOT = Path(__file__).parents[1]


def facility(identifier, meters=0, name="같은 이름 시설"):
    return Facility(identifier, name, "대기측정소", GeoPoint(math.degrees(meters / EARTH_RADIUS_METERS), 0),
                    "검수 주소", "검수 담당부서", "010-1234-5678")


class NearbyReportTests(unittest.TestCase):
    def build(self, facilities, radius=1):
        return NearbyReport.build(GeoPoint(0, 0), "기준점", "주소", radius, facilities)

    def test_boundary_unrounded_distance_order_and_distinct_ids(self):
        rows = [facility("outside", 1000.4), facility("b", 0), facility("edge", 1000), facility("a", 0)]
        report = self.build(rows)
        self.assertEqual([r.facility.id for r in report.facilities], ["a", "b", "edge"])
        self.assertAlmostEqual(report.facilities[-1].meters, 1000)
        self.assertEqual(report.total_count, 4)
        self.assertEqual(self.build([facility("outside", 1000.4)]).facilities, ())

    def test_same_distance_as_frontend_known_daegu_pair(self):
        self.assertAlmostEqual(distance_meters(GeoPoint(35.8714, 128.6014), GeoPoint(35.8884, 128.6108)),
                               2071.568957885587, delta=1)

    def test_invalid_inventory_is_not_empty_result(self):
        for rows in [[], [facility("a"), facility("a")],
                     [dataclasses.replace(facility("a"), location=GeoPoint(float("nan"), 0))]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.build(rows)

    def test_pdf_empty_single_many_and_long_rows(self):
        renderer = NearbyPdfReportRenderer(ROOT / "fonts/NotoSansKR.ttf")
        for count in [0, 1, 195]:
            rows = [facility(f"f-{i:03}", i, name=f"검수시설 {i:03}") for i in range(count)]
            if rows:
                rows[-1] = dataclasses.replace(rows[-1], name="긴시설명" * 28 + "마지막시설",
                    address="긴 한글 주소 " * 400, department="담당부서 010-1234-5678 " * 10)
            report = dataclasses.replace(self.build(rows or [facility("outside", 2000)]), label="기준점 010-1234-5678")
            pdf = renderer.render(report)
            self.assertTrue(pdf.startswith(b"%PDF"))
            pages = len(re.findall(rb"/Type /Page\b", pdf))
            self.assertEqual(pages, 1) if count == 0 else self.assertGreaterEqual(pages, 1)
            if count == 195:
                self.assertGreater(pages, 2)
            if shutil.which("pdftotext"):
                with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
                    f.write(pdf); f.flush()
                    text = subprocess.check_output(["pdftotext", "-layout", f.name, "-"], text=True)
                self.assertIn("기준점 주변 시설 현황 보고서", text)
                self.assertNotIn("010-1234-5678", text)
                if count:
                    self.assertIn("마지막시설", text)
                else:
                    self.assertIn("반경 내 등록시설 0개소", text)


class NearbyReportApiTests(unittest.TestCase):
    def setUp(self):
        self.monitoring = Mock()
        self.monitoring.snapshot.side_effect = AssertionError("위치 보고서는 KMA snapshot을 호출하면 안 됩니다.")
        self.client = TestClient(create_app(service=self.monitoring))
        self.body = dict(latitude=0, longitude=0, label="테스트 기준점", address="", radius_km=1)

    def test_public_report_uses_inventory_without_monitoring(self):
        with patch("safety_dashboard.api.routes.reports.CsvFacilityRepository") as repo:
            repo.return_value.list_monitored.return_value = (facility("a"), facility("b", 2000))
            response = self.client.post("/api/v1/reports/nearby.pdf", json=self.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-nearby-facility-count"], "1")
        self.assertEqual(response.headers["x-nearby-facility-digest"], hashlib.sha256(b'["a"]').hexdigest())
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.monitoring.snapshot.assert_not_called()

    def test_inventory_failure_is_503_not_zero(self):
        with patch("safety_dashboard.api.routes.reports.CsvFacilityRepository") as repo:
            repo.return_value.list_monitored.side_effect = FacilityDataError("private detail")
            response = self.client.post("/api/v1/reports/nearby.pdf", json=self.body)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private detail", response.text)

    def test_invalid_input_and_client_target_override_are_rejected(self):
        for change in [dict(radius_km=0), dict(radius_km=50.1), dict(radius_km=0.15),
                       dict(latitude=91), dict(longitude=-181), dict(label=" "),
                       dict(facility_ids=["a"])]:
            with self.subTest(change=change):
                self.assertEqual(self.client.post("/api/v1/reports/nearby.pdf", json=self.body | change).status_code, 422)
