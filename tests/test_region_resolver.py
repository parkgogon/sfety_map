import unittest

from core.region_resolver import (
    boundary_names_for_warning,
    dominant_warning,
    facility_matches_warning,
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


if __name__ == "__main__":
    unittest.main()

