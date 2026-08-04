import datetime as dt
import tempfile
import unittest
from pathlib import Path

from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.application.facility_groups import (
    FacilityGroupCatalog,
    FacilityGroupError,
)
from safety_dashboard.application.notifications import build_telegram_messages
from safety_dashboard.application.selection import action_snapshot, filter_snapshot
from safety_dashboard.domain import (
    DashboardSnapshot,
    DashboardSummary,
    DataHealth,
    Facility,
    GeoPoint,
    RiskGrade,
    Warning,
    WarningFeed,
    WarningLevel,
)
from safety_dashboard.domain.risk_policy import RiskPolicy


ROOT = Path(__file__).parents[1]
CATALOG_PATH = ROOT / "safety_dashboard/config/facility_groups.toml"
POLICY = RiskPolicy.load(ROOT / "safety_dashboard/config/risk_policy.toml")


class FacilityGroupTests(unittest.TestCase):
    def setUp(self):
        self.catalog = FacilityGroupCatalog.load(CATALOG_PATH)
        self.facilities = CsvFacilityRepository(ROOT / "facilities_info.csv").list_monitored()

    def test_real_facility_counts_match_six_groups(self):
        counts = self.catalog.counts(self.facilities)
        self.assertEqual(sum(counts.values()), 103)
        self.assertEqual(counts["air"], 55)
        self.assertEqual(counts["water"], 21)
        self.assertEqual(counts["farming_collection"], 8)
        self.assertEqual(counts["farming_plastic"], 3)
        self.assertEqual(counts["wastewater"], 2)
        self.assertEqual(counts["other"], 14)

    def test_unknown_future_type_uses_fallback_group(self):
        self.assertEqual(self.catalog.group_for_type("새로운 시설 유형").id, "other")

    def test_real_facilities_filter_to_expected_map_counts(self):
        now = dt.datetime(2026, 8, 3, 10, 0)
        assessments = tuple(POLICY.assess(item, (), now) for item in self.facilities)
        snapshot = DashboardSnapshot(
            generated_at=now,
            warning_feed=WarningFeed((), DataHealth.LIVE, now),
            facilities=self.facilities,
            assessments=assessments,
            summary=DashboardSummary(0, 0, 0, 0, WarningLevel.UNKNOWN),
            policy_version=POLICY.version,
        )
        air = filter_snapshot(snapshot, self.catalog, ("air",), tuple(RiskGrade))
        plastic = filter_snapshot(
            snapshot, self.catalog, ("farming_plastic",), tuple(RiskGrade)
        )
        self.assertEqual(len(air.facilities), 55)
        self.assertEqual(len(plastic.facilities), 3)

    def test_duplicate_type_mapping_is_rejected(self):
        duplicate = b"""
[groups.one]
label = "one"
facility_types = ["same"]
[groups.two]
label = "two"
facility_types = ["same"]
[groups.other]
label = "other"
fallback = true
"""
        with tempfile.NamedTemporaryFile(suffix=".toml") as file:
            file.write(duplicate)
            file.flush()
            with self.assertRaises(FacilityGroupError):
                FacilityGroupCatalog.load(file.name)


class SnapshotSelectionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = FacilityGroupCatalog.load(CATALOG_PATH)
        now = dt.datetime(2026, 8, 3, 10, 0)
        self.warning_air = Warning(
            "air-warning", "기상청", "L107", "L10701", "경상북도", "포항시",
            "호우", "경보", WarningLevel.WARNING,
        )
        self.warning_water = Warning(
            "water-warning", "기상청", "L116", "L11601", "부산광역시", "부산",
            "강풍", "주의보", WarningLevel.ADVISORY,
        )
        air = Facility("air", "대기 시설", "대기측정소", GeoPoint(36, 129), "포항시")
        water = Facility("water", "수질 시설", "수질측정소", GeoPoint(35, 129), "부산")
        plastic = Facility(
            "plastic", "폐비닐 시설", "영농폐비닐 재활용시설",
            GeoPoint(36, 128), "구미시",
        )
        assessments = (
            POLICY.assess(air, (self.warning_air,), now),
            POLICY.assess(water, (self.warning_water,), now),
            POLICY.assess(plastic, (), now),
        )
        self.snapshot = DashboardSnapshot(
            generated_at=now,
            warning_feed=WarningFeed(
                (self.warning_air, self.warning_water), DataHealth.LIVE, now
            ),
            facilities=(air, water, plastic),
            assessments=assessments,
            summary=DashboardSummary(2, 2, 1, 0, WarningLevel.WARNING),
            policy_version=POLICY.version,
        )

    def test_filter_keeps_matching_facilities_warnings_and_summary(self):
        filtered = filter_snapshot(
            self.snapshot,
            self.catalog,
            ("air", "farming_plastic"),
            tuple(RiskGrade),
        )
        self.assertEqual({item.id for item in filtered.facilities}, {"air", "plastic"})
        self.assertEqual([item.id for item in filtered.warning_feed.warnings], ["air-warning"])
        self.assertEqual(filtered.summary.active_warning_count, 1)
        self.assertEqual(filtered.summary.affected_facility_count, 1)
        self.assertEqual(filtered.summary.high_risk_count, 1)

    def test_grade_filter_controls_map_scope(self):
        filtered = filter_snapshot(
            self.snapshot, self.catalog, self.catalog.ids, (RiskGrade.NONE,)
        )
        self.assertEqual([item.id for item in filtered.facilities], ["plastic"])
        self.assertEqual(filtered.warning_feed.warnings, ())

    def test_action_snapshot_contains_only_checked_affected_facilities(self):
        filtered = filter_snapshot(
            self.snapshot, self.catalog, self.catalog.ids, tuple(RiskGrade)
        )
        selected = action_snapshot(filtered, ("water", "plastic"))
        self.assertEqual([item.id for item in selected.facilities], ["water"])
        self.assertEqual([item.id for item in selected.warning_feed.warnings], ["water-warning"])
        self.assertEqual(selected.summary.affected_facility_count, 1)

        messages = build_telegram_messages(selected.assessments)
        self.assertIn("수질 시설", messages[0])
        self.assertNotIn("대기 시설", messages[0])

    def test_empty_action_selection_is_empty(self):
        filtered = filter_snapshot(
            self.snapshot, self.catalog, self.catalog.ids, tuple(RiskGrade)
        )
        selected = action_snapshot(filtered, ())
        self.assertEqual(selected.facilities, ())
        self.assertEqual(selected.warning_feed.warnings, ())


if __name__ == "__main__":
    unittest.main()
