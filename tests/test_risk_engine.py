import unittest

import pandas as pd

from risk_engine import (
    assess_facility_risk,
    calculate_warning_score,
    classify_grade,
)


class RiskEngineTests(unittest.TestCase):
    def test_critical_warning_multiplier(self):
        self.assertEqual(calculate_warning_score("태풍", "중대경보"), 10.0)
        self.assertEqual(classify_grade(10.0), "상")

    def test_multiple_warnings_use_highest_score(self):
        facility = pd.Series(
            {
                "name": "포항 테스트 시설",
                "address": "경북 포항시 남구",
                "latitude": 36.0,
                "longitude": 129.3,
                "시설구분": "기타",
            }
        )
        warnings = pd.DataFrame(
            [
                {
                    "region_up": "경상북도",
                    "region": "포항시",
                    "type": "폭염",
                    "level": "주의",
                },
                {
                    "region_up": "경상북도",
                    "region": "포항시",
                    "type": "호우",
                    "level": "경보",
                },
            ]
        )
        result = assess_facility_risk(facility, warnings)
        self.assertEqual(result["max_warning_score"], 6.0)
        self.assertEqual(result["grade"], "중")
        self.assertEqual(len(result["matched_warnings"]), 2)


if __name__ == "__main__":
    unittest.main()

