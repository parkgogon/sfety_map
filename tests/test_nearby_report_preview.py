"""개발용 시안에서도 집계·지도와 기존 보고서의 대상을 일치시킨다."""
import dataclasses
import io
import hashlib
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from PIL import Image

from design.nearby_report.model import capture_input, destination, summary
from design.nearby_report.pdf import NearbyPreviewRenderer, validate_map
from design.nearby_report.cases import build_cases
from safety_dashboard.application.nearby_report import NearbyReport, distance_meters
from safety_dashboard.domain.models import Facility, GeoPoint


class NearbyPreviewTests(unittest.TestCase):
    def test_distance_bands_include_boundaries_and_same_location_once(self):
        origin = GeoPoint(35.87, 128.6)
        template = Facility("f", "같은 이름", "수질측정소", origin, "검수 주소", "같은 부서")
        rows = [dataclasses.replace(template, id=str(i)) for i in range(6)]
        report = NearbyReport.build(origin, "검수", "", 5, rows)
        # 정확한 구간 경계·0m를 주입해 부동소수점 좌표 변환 오차와 구분한다.
        report = dataclasses.replace(report, facilities=tuple(
            dataclasses.replace(row, meters=meters)
            for row, meters in zip(report.facilities, [0, 1000, 1000.4, 3000, 3000.1, 5000])))
        result = summary(report)
        self.assertEqual([b["count"] for b in result["bands"]], [2, 2, 2])
        self.assertEqual(result["count"], 6)
        self.assertEqual(result["nearest_meters"], 0)
        self.assertEqual(sum(t["count"] for t in result["types"]), 6)
        self.assertEqual(sum(t["count"] for t in result["departments"]), 6)
        self.assertEqual(len(capture_input(report, "same")["facilities"]), 6)

    def test_arbitrary_radius_has_no_empty_or_overlapping_intervals(self):
        point = GeoPoint(35.87, 128.6)
        facility = Facility("f", "검수", "유형", point, "주소", "부서")
        for radius, expected in [(0.1, ["0–0.1km"]), (1, ["0–1km"]),
                                  (1.5, ["0–1km", "1–1.5km"]),
                                  (50, ["0–1km", "1–3km", "3–5km", "5–50km"])]:
            report = NearbyReport.build(point, "검수", "", radius, [facility])
            result = summary(report)
            self.assertEqual([b["label"] for b in result["bands"]], expected)
            self.assertEqual(sum(b["count"] for b in result["bands"]), 1)

    def test_circle_uses_the_same_distance_model_and_empty_report_is_valid(self):
        point = GeoPoint(35.87, 128.6)
        outside = Facility("f", "멀리 있는 시설", "유형", GeoPoint(37, 129), "주소", "부서")
        for radius in (0.1, 1, 3, 5, 50):
            report = NearbyReport.build(point, "검수", "", radius, [outside])
            value = capture_input(report, "circle")
            self.assertIsNone(value["summary"]["nearest_meters"])
            for vertex in value["circle"]:
                self.assertAlmostEqual(distance_meters(point, GeoPoint(**vertex)), radius * 1000, places=6)
            east = GeoPoint(**destination(point.latitude, point.longitude, radius * 1000, 90))
            self.assertGreater(east.longitude, point.longitude)

    def test_map_metadata_cannot_hide_changed_ids_coordinates_or_duplicate_groups(self):
        point = GeoPoint(35.87, 128.6)
        rows = [Facility(str(i), "같은 이름", "유형", point, "주소", "부서") for i in range(2)]
        report = NearbyReport.build(point, "검수", "", 5, rows)
        metadata = capture_input(report, "same")
        metadata["geometry"] = {"groups": [{"number": 1, "ids": ["0", "1"]}]}
        self.assertEqual(validate_map(report, metadata), {"0": 1, "1": 1})
        changes = [dict(radius_km=3), dict(facilities=metadata["facilities"][:1]),
                   dict(facilities=[metadata["facilities"][0], metadata["facilities"][1] | {"longitude": 129}]),
                   dict(geometry={"groups": [{"number": 1, "ids": ["0", "1"]}, {"number": 2, "ids": ["1"]}]}),
                   dict(summary=metadata["summary"] | {"count": 3})]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_map(report, metadata | change)

    def test_preview_pdf_zero_small_and_195_long_rows_without_contact_leaks(self):
        point = GeoPoint(35.87, 128.6)
        buffer = io.BytesIO()
        Image.new("RGB", (1200, 620), "white").save(buffer, format="PNG")
        # 테스트 이미지이며 실제 지도 검수 증빙으로 저장하지 않는다.
        renderer = NearbyPreviewRenderer(Path(__file__).parents[1] / "fonts/NotoSansKR.ttf")
        for count in (0, 1, 3, 195):
            rows = [Facility(str(i), f"검수시설 {i}", "수질측정소", point, "검수 주소", "검수 부서") for i in range(count)]
            if count == 195:
                rows[-1] = dataclasses.replace(rows[-1], name="긴 시설명 " * 30 + "마지막시설",
                    address="긴 한글 주소 " * 400 + "주소마지막", department="검수 부서 010-1234-5678")
            catalog = rows or [Facility("outside", "멀리 있는 시설", "유형", GeoPoint(37, 129), "주소", "부서")]
            report = NearbyReport.build(point, "검수 010-1234-5678", "주소", 5, catalog)
            metadata = capture_input(report, "test")
            metadata["geometry"] = {"groups": [{"number": 1, "ids": [r.facility.id for r in report.facilities]}] if count else []}
            metadata["pngSha256"] = hashlib.sha256(buffer.getvalue()).hexdigest()
            pdf = renderer.render(report, buffer.getvalue(), metadata)
            pages = len(re.findall(rb"/Type /Page\b", pdf))
            self.assertEqual(pages, 1) if count <= 3 else self.assertGreater(pages, 2)
            if shutil.which("pdftotext"):
                with tempfile.NamedTemporaryFile(suffix=".pdf") as output:
                    output.write(pdf); output.flush()
                    text = subprocess.check_output(["pdftotext", "-layout", output.name, "-"], text=True)
                self.assertIn("기준점 주변 시설 현황 보고서", text)
                self.assertIn("담당부서", text)
                self.assertNotIn("010-1234-5678", text)
                if count == 195:
                    self.assertIn("마지막시설", text)
                    self.assertIn("주소마지막", text)

    def test_real_three_facilities_with_long_departments_fit_one_page(self):
        data, report = next(case for case in build_cases() if case[0]["id"] == "urban-5km")
        self.assertEqual(len(report.facilities), 3)
        data["geometry"] = {"groups": [{"number": index + 1, "ids": [row.facility.id]}
                                       for index, row in enumerate(report.facilities)]}
        image = io.BytesIO()
        Image.new("RGB", (1200, 620), "white").save(image, format="PNG")
        renderer = NearbyPreviewRenderer(Path(__file__).parents[1] / "fonts/NotoSansKR.ttf")
        data["pngSha256"] = hashlib.sha256(image.getvalue()).hexdigest()
        self.assertEqual(len(re.findall(rb"/Type /Page\b", renderer.render(report, image.getvalue(), data))), 1)
        with self.assertRaisesRegex(ValueError, "이미지와 캡처"):
            renderer.render(report, image.getvalue(), data | {"pngSha256": "wrong-image"})


if __name__ == "__main__":
    unittest.main()
