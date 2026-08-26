import datetime as dt
import unittest
from dataclasses import replace
from pathlib import Path

from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.adapters.kma import StaticWarningProvider, parse_warning_response
from safety_dashboard.application.monitoring import (
    MonitoringService,
    reassess_snapshot,
)
from safety_dashboard.application.notifications import build_telegram_messages
from safety_dashboard.domain import DataHealth, Facility, GeoPoint, RiskGrade, Warning, WarningLevel
from safety_dashboard.domain.risk_policy import RiskPolicy


ROOT = Path(__file__).parents[1]
POLICY = RiskPolicy.load(ROOT / "safety_dashboard/config/risk_policy.toml")


class MemoryFacilities:
    def __init__(self, values):
        self.values = values

    def list_monitored(self):
        return self.values


class MatchByAddress:
    def matches(self, facility, warning):
        return warning.region in facility.address


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.facilities = (
            Facility("1", "포항 <시설>", "측정소", GeoPoint(36, 129), "경북 포항시"),
            Facility("2", "부산 시설", "측정소", GeoPoint(35, 129), "부산 강서구"),
        )
        self.warning = Warning(
            "w1", "기상청", "L1070000", "L1072400", "경상북도", "포항시",
            "호우", "경보", WarningLevel.WARNING,
        )

    def test_one_snapshot_drives_summary_and_assessments(self):
        snapshot = MonitoringService(
            MemoryFacilities(self.facilities),
            StaticWarningProvider((self.warning,)),
            MatchByAddress(),
            POLICY,
        ).get_snapshot(dt.datetime(2026, 8, 3, 10, 0))
        self.assertEqual(snapshot.summary.active_warning_count, 1)
        self.assertEqual(snapshot.summary.affected_facility_count, 1)
        self.assertEqual(snapshot.summary.high_risk_count, 1)
        self.assertEqual(snapshot.assessments[0].grade, RiskGrade.HIGH)
        self.assertEqual(snapshot.assessments[1].grade, RiskGrade.NONE)

    def test_session_policy_reuses_saved_warning_facility_links(self):
        snapshot = MonitoringService(
            MemoryFacilities(self.facilities),
            StaticWarningProvider((self.warning,)),
            MatchByAddress(),
            POLICY,
        ).get_snapshot(dt.datetime(2026, 8, 3, 10, 0))
        matrix = dict(POLICY.warning_matrix)
        matrix["호우"] = {
            **matrix["호우"],
            WarningLevel.WARNING: RiskGrade.LOW,
        }
        temporary_policy = replace(
            POLICY,
            version="temporary-test",
            warning_matrix=matrix,
        )

        reassessed = reassess_snapshot(snapshot, temporary_policy)

        self.assertIs(reassessed.warning_feed, snapshot.warning_feed)
        self.assertEqual(reassessed.generated_at, snapshot.generated_at)
        self.assertEqual(reassessed.policy_version, "temporary-test")
        self.assertEqual(reassessed.assessments[0].grade, RiskGrade.LOW)
        self.assertEqual(reassessed.assessments[1].grade, RiskGrade.NONE)
        self.assertEqual(reassessed.summary.affected_facility_count, 1)
        self.assertEqual(reassessed.summary.high_risk_count, 0)

    def test_telegram_escapes_untrusted_facility_text(self):
        assessment = POLICY.assess(self.facilities[0], (self.warning,))
        message = build_telegram_messages(
            (assessment,), scope_label="대기 <측정소>"
        )[0]
        self.assertIn("포항 &lt;시설&gt;", message)
        self.assertNotIn("포항 <시설>", message)
        self.assertIn("대기 &lt;측정소&gt;", message)
        self.assertIn(POLICY.version, message)

    def test_scoped_telegram_pages_keep_every_selected_facility(self):
        assessments = tuple(
            POLICY.assess(
                replace(
                    self.facilities[0],
                    id=str(index),
                    name=f"선택 시설 {index:03}",
                ),
                (self.warning,),
            )
            for index in range(60)
        )
        messages = build_telegram_messages(
            assessments,
            max_length=700,
            scope_label="대기측정소 / 상·중·하·미판정",
        )
        self.assertTrue(all(len(message) <= 700 for message in messages))
        combined = "\n".join(messages)
        self.assertTrue(
            all(f"선택 시설 {index:03}" in combined for index in range(60))
        )

    def test_kma_parser_filters_scope_and_normalizes_level(self):
        text = "\n".join((
            "L1070000,경상북도,L1072400,포항시,202608031000,202608031100,호우,경보,발표,0",
            "L1010000,서울특별시,L1010100,서울,202608031000,202608031100,호우,경보,발표,0",
        ))
        values = parse_warning_response(text, POLICY)
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0].level, WarningLevel.WARNING)

    def test_real_facility_csv_has_stable_unique_ids(self):
        values = CsvFacilityRepository(ROOT / "facilities_info.csv").list_monitored()
        self.assertGreater(len(values), 0)
        self.assertEqual(len(values), len({item.id for item in values}))


if __name__ == "__main__":
    unittest.main()
