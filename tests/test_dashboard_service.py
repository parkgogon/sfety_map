import unittest

import pandas as pd

from services.dashboard_service import build_telegram_message


class DashboardServiceTests(unittest.TestCase):
    def test_telegram_message_escapes_dynamic_html(self):
        affected = pd.DataFrame(
            [
                {
                    "facility_name": "<시설&1>",
                    "grade": "상",
                    "matched_warnings": [
                        {"type": "호우", "level": "<경보>"},
                    ],
                }
            ]
        )
        message = build_telegram_message(affected)
        self.assertIn("&lt;시설&amp;1&gt;", message)
        self.assertNotIn("<시설&1>", message)


if __name__ == "__main__":
    unittest.main()
