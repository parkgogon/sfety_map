import datetime as dt
import unittest
from pathlib import Path

from safety_dashboard.adapters.pdf_report import GRADE_COLOR
from safety_dashboard.domain import Facility, GeoPoint, RiskGrade, Warning, WarningLevel
from safety_dashboard.domain.risk_policy import RISK_GRADE_COLORS, RiskPolicy
from safety_dashboard.ui.map_view import COLORS


POLICY_PATH = (
    Path(__file__).parents[1]
    / "safety_dashboard"
    / "config"
    / "risk_policy.toml"
)



def warning(kind: str, raw_level: str, level: WarningLevel) -> Warning:
    return Warning(
        id=f"{kind}:{raw_level}",
        source="KMA",
        region_up_code="L1070000",
        region_code="L1072400",
        region_up="경상북도",
        region="포항시",
        warning_type=kind,
        raw_level=raw_level,
        level=level,
    )


class RiskPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = RiskPolicy.load(POLICY_PATH)
        self.facility = Facility(
            id="3049",
            name="테스트 시설",
            facility_type="대기측정소",
            location=GeoPoint(36.0, 129.3),
            address="경북 포항시",
        )

    def test_policy_is_directly_readable_and_versioned(self):
        self.assertEqual(self.policy.version, "2026.08-v1")
        self.assertEqual(
            self.policy.warning_matrix["호우"][WarningLevel.WARNING],
            RiskGrade.HIGH,
        )
        self.assertEqual(
            self.policy.warning_matrix["폭염"][WarningLevel.WARNING],
            RiskGrade.MEDIUM,
        )

    def test_highest_grade_wins_without_losing_reasons(self):
        assessment = self.policy.assess(
            self.facility,
            [
                warning("폭염", "주의", WarningLevel.ADVISORY),
                warning("호우", "경보", WarningLevel.WARNING),
            ],
            assessed_at=dt.datetime(2026, 8, 3, 9, 0),
        )
        self.assertEqual(assessment.grade, RiskGrade.HIGH)
        self.assertEqual(len(assessment.reasons), 2)

    def test_unknown_warning_is_unassessed_not_low(self):
        assessment = self.policy.assess(
            self.facility,
            [warning("새로운특보", "발표", WarningLevel.UNKNOWN)],
        )
        self.assertEqual(assessment.grade, RiskGrade.UNASSESSED)
        self.assertEqual(
            self.policy.definition(RiskGrade.UNASSESSED).color,
            "#7C3AED",
        )

    def test_no_warning_is_none(self):
        self.assertEqual(
            self.policy.assess(self.facility, []).grade,
            RiskGrade.NONE,
        )
        self.assertEqual(
            self.policy.definition(RiskGrade.NONE).meaning,
            "특보의 영향권에 들지 않음",
        )
        self.assertEqual(
            self.policy.definition(RiskGrade.UNASSESSED).meaning,
            "기준 미등록 특보로 위험등급 판정불가",
        )

    def test_product_palette_matches_policy_map_css_and_pdf(self):
        expected_hex = {
            RiskGrade.HIGH: "#D92D20",
            RiskGrade.MEDIUM: "#C2410C",
            RiskGrade.LOW: "#8A6D00",
            RiskGrade.NONE: "#176B87",
            RiskGrade.UNASSESSED: "#7C3AED",
        }
        expected_rgb = {
            grade: tuple(bytes.fromhex(color.removeprefix("#")))
            for grade, color in expected_hex.items()
        }
        self.assertEqual(
            {grade: self.policy.definition(grade).color for grade in expected_hex},
            expected_hex,
        )
        self.assertEqual(COLORS, expected_hex)
        self.assertEqual(GRADE_COLOR, expected_rgb)
        for grade, color in expected_hex.items():
            self.assertEqual(RISK_GRADE_COLORS[grade], color)
            self.assertEqual(RISK_GRADE_COLORS[grade.value], color)


        tokens = (
            Path(__file__).parents[1]
            / "safety_dashboard"
            / "ui"
            / "design_tokens.css"
        ).read_text(encoding="utf-8")
        for color in (*expected_hex.values(), "#667085"):
            self.assertIn(color.lower(), tokens)
        self.assertEqual(len({*expected_hex.values(), "#667085"}), 6)


if __name__ == "__main__":
    unittest.main()
