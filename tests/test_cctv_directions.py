import datetime as dt
import tempfile
import unittest
from pathlib import Path

from safety_dashboard.application.cctv_directions import (
    CctvDirectionCatalog,
    CctvDirectionConfigError,
    describe_cctv_direction,
    direction_label,
    load_cctv_direction_catalog,
)
from safety_dashboard.domain.models import GeoPoint, NearbyCctv


ROOT = Path(__file__).parents[1]


def load_text(document: str) -> CctvDirectionCatalog:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "directions.toml"
        path.write_text(document, encoding="utf-8")
        return CctvDirectionCatalog.load(path)


def sample_cctv(
    name: str = "포항교차로 CCTV",
    latitude: float = 36.123459,
    longitude: float = 129.123459,
) -> NearbyCctv:
    return NearbyCctv(
        id="cctv-1",
        name=name,
        location=GeoPoint(latitude, longitude),
        distance_km=2.3,
        road_type="국도",
        video_url="https://video.example/cctv.mp4",
    )


VALID_DOCUMENT = """
[[directions]]
name = "포항교차로 CCTV"
latitude = 36.123456
longitude = 129.123456
bearing_deg = 135.0
verified_on = 2026-08-06
source = "현장 영상 검증"
"""


class CctvDirectionCatalogTests(unittest.TestCase):
    def test_packaged_catalog_starts_empty(self):
        catalog = CctvDirectionCatalog.load(
            ROOT / "safety_dashboard/config/cctv_directions.toml"
        )
        self.assertEqual(catalog.entries, ())
        self.assertEqual(catalog.enrich((sample_cctv(),)), (sample_cctv(),))

    def test_name_and_rounded_coordinates_enrich_cctv(self):
        enriched = load_text(VALID_DOCUMENT).enrich((sample_cctv(),))[0]
        self.assertEqual(enriched.bearing_deg, 135.0)
        self.assertEqual(enriched.direction_verified_on, dt.date(2026, 8, 6))
        self.assertEqual(enriched.direction_source, "현장 영상 검증")
        self.assertEqual(
            describe_cctv_direction(enriched),
            "촬영방향 남동 135° · 2026-08-06 검증",
        )

    def test_name_or_coordinate_mismatch_does_not_guess_direction(self):
        catalog = load_text(VALID_DOCUMENT)
        mismatched = (
            sample_cctv(name="포항교차로 CCTV 변경"),
            sample_cctv(latitude=36.12340),
        )
        enriched = catalog.enrich(mismatched)
        self.assertTrue(all(item.bearing_deg is None for item in enriched))
        self.assertTrue(
            all(describe_cctv_direction(item) == "촬영방향 미확인" for item in enriched)
        )

    def test_duplicate_rounded_name_and_coordinates_are_rejected(self):
        duplicate = VALID_DOCUMENT + """
[[directions]]
name = "포항교차로 CCTV"
latitude = 36.123459
longitude = 129.123459
bearing_deg = 140
verified_on = 2026-08-06
source = "두 번째 검증"
"""
        with self.assertRaisesRegex(CctvDirectionConfigError, "중복"):
            load_text(duplicate)

    def test_configuration_error_is_isolated_to_an_empty_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "directions.toml"
            path.write_text("[[directions]\ninvalid", encoding="utf-8")
            catalog, warning = load_cctv_direction_catalog(path)
        self.assertEqual(catalog.entries, ())
        self.assertIn("읽을 수 없습니다", warning)

    def test_invalid_coordinates_bearing_date_and_source_are_rejected(self):
        invalid_documents = (
            VALID_DOCUMENT.replace("36.123456", "91.0"),
            VALID_DOCUMENT.replace("135.0", "360.0"),
            VALID_DOCUMENT.replace("2026-08-06", '"not-a-date"'),
            VALID_DOCUMENT.replace('source = "현장 영상 검증"', 'source = ""'),
        )
        for document in invalid_documents:
            with self.subTest(document=document):
                with self.assertRaises(CctvDirectionConfigError):
                    load_text(document)

    def test_eight_way_direction_labels_follow_north_zero_clockwise(self):
        expected = {
            0: "북",
            45: "북동",
            90: "동",
            135: "남동",
            180: "남",
            225: "남서",
            270: "서",
            315: "북서",
            359.9: "북",
        }
        for bearing, label in expected.items():
            with self.subTest(bearing=bearing):
                self.assertEqual(direction_label(bearing), label)


if __name__ == "__main__":
    unittest.main()
