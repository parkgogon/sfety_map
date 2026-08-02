import unittest
import gzip
import json
from pathlib import Path

from core.region_resolver import (
    WarningZoneIndex,
    boundary_names_for_warning,
    dominant_warning,
    facility_matches_warning,
    normalize_warning_zone_data,
    warning_matches_facility,
    warning_level_rank,
)


class RegionResolverTests(unittest.TestCase):
    def test_matches_regular_city(self):
        self.assertTrue(
            facility_matches_warning(
                "경북 포항시 남구 신항로 99",
                "포항시",
                "경상북도",
            )
        )

    def test_ambiguous_district_requires_parent_region(self):
        self.assertFalse(
            facility_matches_warning(
                "울산 남구 산업로 1",
                "남구",
                "대구광역시",
            )
        )
        self.assertTrue(
            facility_matches_warning(
                "대구 남구 중앙대로 1",
                "남구",
                "대구광역시",
            )
        )

    def test_kma_daegu_zone_is_conservative(self):
        self.assertTrue(
            facility_matches_warning(
                "대구 수성구 달구벌대로 1",
                "대구중부",
                "대구광역시",
            )
        )
        self.assertFalse(
            facility_matches_warning(
                "경북 구미시 산동읍 1",
                "대구중부",
                "대구광역시",
            )
        )

    def test_daegu_zone_expands_to_map_boundaries(self):
        available = {"중구", "남구", "북구", "포항시"}
        self.assertEqual(
            boundary_names_for_warning("대구중부", available),
            ["중구", "남구", "북구"],
        )

    def test_dominant_warning_prefers_level_then_type(self):
        warnings = [
            {"type": "태풍", "level": "주의"},
            {"type": "폭염", "level": "경보"},
        ]
        selected = dominant_warning(warnings, {"태풍": 5, "폭염": 2})
        self.assertEqual(selected["type"], "폭염")
        self.assertGreater(
            warning_level_rank("중대경보"),
            warning_level_rank("경보"),
        )

    def test_spatial_matching_distinguishes_subzones(self):
        boundary_data = normalize_warning_zone_data(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"regid": "L1140210", "regko_fullname": "달성군북부"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[128.0, 35.8], [128.2, 35.8], [128.2, 36.0], [128.0, 36.0], [128.0, 35.8]]],
                        },
                    },
                    {
                        "type": "Feature",
                        "properties": {"regid": "L1140220", "regko_fullname": "달성군남부"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[128.0, 35.5], [128.2, 35.5], [128.2, 35.7], [128.0, 35.7], [128.0, 35.5]]],
                        },
                    },
                ],
            }
        )
        index = WarningZoneIndex.from_geojson(boundary_data)
        facility = {
            "address": "대구 달성군 다사읍",
            "latitude": 35.9,
            "longitude": 128.1,
        }
        self.assertTrue(
            warning_matches_facility(
                facility,
                {"region_code": "L1140210", "region": "달성군북부"},
                index,
            )
        )
        self.assertFalse(
            warning_matches_facility(
                facility,
                {"region_code": "L1140220", "region": "달성군남부"},
                index,
            )
        )

    def test_coastal_coordinate_tolerance_requires_matching_address(self):
        boundary_data = normalize_warning_zone_data(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"regid": "L1072400"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [129.0, 36.0],
                                    [129.2, 36.0],
                                    [129.2, 36.2],
                                    [129.0, 36.2],
                                    [129.0, 36.0],
                                ]
                            ],
                        },
                    }
                ],
            }
        )
        index = WarningZoneIndex.from_geojson(boundary_data)
        warning = {
            "region_code": "L1072400",
            "region_up": "경상북도",
            "region": "포항시",
        }
        near_coast = {
            "address": "경북 포항시 북구 항구동",
            "latitude": 36.1,
            "longitude": 129.201,
        }
        wrong_address = {**near_coast, "address": "경북 영덕군 강구면"}
        self.assertTrue(warning_matches_facility(near_coast, warning, index))
        self.assertFalse(warning_matches_facility(wrong_address, warning, index))

    def test_bundled_kma_boundaries_include_repaired_coastal_and_subzones(self):
        path = Path(__file__).parents[1] / "data" / "kma_warning_zones.geojson.gz"
        with gzip.open(path, "rt", encoding="utf-8") as file:
            index = WarningZoneIndex.from_geojson(json.load(file))

        expected_codes = {
            "L1070200",  # 군위군
            "L1072200",  # 영덕군
            "L1072400",  # 포항시
            "L1073110",  # 경주시중북부
            "L1140100",  # 대구중부
            "L1140210",  # 달성군북부
            "L1140220",  # 달성군남부
        }
        self.assertTrue(expected_codes.issubset(index.geometries))
        self.assertTrue(all(index.geometries[code].is_valid for code in expected_codes))
        overlap = index.geometries["L1072200"].intersection(
            index.geometries["L1072400"]
        ).area
        self.assertLess(overlap, 0.000002)

        self.assertTrue(index.covers("L1140210", 35.885500, 128.503345))
        self.assertFalse(index.covers("L1140220", 35.885500, 128.503345))
        self.assertTrue(index.covers("L1140220", 35.725220, 128.435776))
        self.assertFalse(index.covers("L1140210", 35.725220, 128.435776))


if __name__ == "__main__":
    unittest.main()
