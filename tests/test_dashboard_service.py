import unittest

import pandas as pd

from services.dashboard_service import build_telegram_messages


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
        message = build_telegram_messages(affected)[0]
        self.assertIn("&lt;시설&amp;1&gt;", message)
        self.assertNotIn("<시설&1>", message)

    def test_telegram_message_lists_every_facility_without_omission(self):
        affected = pd.DataFrame(
            [
                {
                    "facility_name": f"시설 {index:02d}",
                    "grade": "중",
                    "total_score": 4,
                    "matched_warnings": [
                        {
                            "type": "폭염",
                            "level": "경보",
                            "region": "포항시",
                        }
                    ],
                }
                for index in range(31)
            ]
        )

        messages = build_telegram_messages(affected, max_length=700)
        combined = "\n".join(messages)

        self.assertGreater(len(messages), 1)
        self.assertNotIn("외 ", combined)
        self.assertTrue(all(len(message) <= 700 for message in messages))
        for index in range(31):
            self.assertEqual(combined.count(f"시설 {index:02d}"), 1)

    def test_telegram_message_keeps_all_distinct_warnings(self):
        affected = pd.DataFrame(
            [
                {
                    "facility_name": "복합 특보 시설",
                    "grade": "상",
                    "matched_warnings": [
                        {"type": "폭염", "level": "경보", "region": "포항시"},
                        {"type": "열대야", "level": "주의", "region": "포항시"},
                        {"type": "폭염", "level": "경보", "region": "포항시"},
                    ],
                }
            ]
        )
        message = build_telegram_messages(affected)[0]
        self.assertEqual(message.count("폭염 경보"), 1)
        self.assertEqual(message.count("열대야 주의"), 1)


if __name__ == "__main__":
    unittest.main()
