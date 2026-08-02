import unittest

import pandas as pd

from report_generator import generate_html_report


class ReportGeneratorTests(unittest.TestCase):
    def test_html_report_escapes_dynamic_values(self):
        warnings = pd.DataFrame(
            [
                {
                    "region_up": "<경북>",
                    "region": "포항시",
                    "type": "호우<script>",
                    "level": "경보",
                    "source": "기상청",
                }
            ]
        )
        grade_groups = {
            "상": pd.DataFrame(
                [
                    {
                        "facility_name": "<시설>",
                        "facility_type": "기타",
                        "manager": "담당&자",
                        "matched_warnings": [
                            {"type": "호우", "level": "<경보>"},
                        ],
                    }
                ]
            )
        }

        report = generate_html_report(warnings, grade_groups)
        self.assertIn("&lt;시설&gt;", report)
        self.assertIn("담당&amp;자", report)
        self.assertNotIn("<script>", report)


if __name__ == "__main__":
    unittest.main()

