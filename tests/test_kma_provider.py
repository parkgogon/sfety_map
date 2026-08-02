import datetime as dt
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from data_providers.kma_provider import (
    KMAProvider,
    WARNING_COLUMNS,
    _warning_frame,
    filter_warning_scope,
    parse_warning_response,
)


RAW_WARNING_RESPONSE = """
# REG_UP,REG_UP_KO,REG_ID,REG_KO,TM_FC,TM_EF,WRN,LVL,CMD,ED_TM
L1070000,경상북도,L1070500,경산시,202608021000,202608021100,폭염,중대경보,변경,
L1073100,경주시,L1073110,경주시중북부,202608021000,202608021100,폭염,중대경보,변경,
L1140200,달성군,L1140220,달성군남부,202608021000,202608021100,폭염,중대경보,변경,
L1072700,안동시,L1072730,안동시서부,202607221600,202607221800,열대야,주의,발표,
L1150000,부산광역시,L1082600,부산중부,202607291600,202607301100,폭염,중대경보,변경,
L1160000,울산광역시,L1082900,울산서부,202608011000,202608011100,폭염,중대경보,변경,
L1010000,서울특별시,L1010100,서울동부,202608011000,202608011100,폭염,경보,변경,
"""


class KMAProviderTests(unittest.TestCase):
    def test_parser_preserves_codes_and_times(self):
        records = parse_warning_response(RAW_WARNING_RESPONSE)
        self.assertEqual(len(records), 7)
        self.assertEqual(records[1]["region_code"], "L1073110")
        self.assertEqual(records[1]["region"], "경주시중북부")
        self.assertEqual(records[1]["issued_at"], dt.datetime(2026, 8, 2, 10, 0))
        self.assertEqual(records[1]["effective_at"], dt.datetime(2026, 8, 2, 11, 0))

    def test_code_scope_keeps_nested_and_metropolitan_zones(self):
        frame = _warning_frame(parse_warning_response(RAW_WARNING_RESPONSE), status="ok")
        scoped = filter_warning_scope(
            frame,
            ("L107", "L108", "L114", "L115", "L116"),
        )
        self.assertEqual(len(scoped), 6)
        self.assertEqual(list(scoped.columns), WARNING_COLUMNS)
        self.assertEqual(scoped.attrs["fetch_status"], "ok")
        self.assertEqual(
            set(scoped["region"]),
            {
                "경산시",
                "경주시중북부",
                "달성군남부",
                "안동시서부",
                "부산중부",
                "울산서부",
            },
        )

    @patch.object(KMAProvider, "_fetch_warning_zones")
    def test_warning_zone_loader_uses_bundled_fallback(self, fetch_zones):
        fetch_zones.side_effect = requests.RequestException("offline")
        path = Path(__file__).parents[1] / "data" / "kma_warning_zones.geojson.gz"
        boundaries, status, note = KMAProvider.get_warning_zones(path)
        self.assertEqual(status, "fallback")
        self.assertIn("내장본", note)
        codes = {
            feature["properties"]["regid"]
            for feature in boundaries["features"]
        }
        self.assertIn("L1072400", codes)
        self.assertIn("L1082800", codes)


if __name__ == "__main__":
    unittest.main()
