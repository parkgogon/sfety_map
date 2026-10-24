import datetime as dt
from pathlib import Path
import unittest
from unittest.mock import patch

import requests

from safety_dashboard.adapters.kma import WarningZoneRepository, parse_warning_response
from safety_dashboard.domain import DataHealth
from safety_dashboard.domain.risk_policy import RiskPolicy

ROOT = Path(__file__).resolve().parents[1]


class KmaContractTests(unittest.TestCase):
    def test_parser_preserves_nested_and_metropolitan_zone_codes_and_times(self):
        records = (
            ("L1073100", "경주시", "L1073110", "경주시중북부"),
            ("L1140200", "달성군", "L1140220", "달성군남부"),
            ("L1150000", "부산광역시", "L1082600", "부산중부"),
            ("L1160000", "울산광역시", "L1082900", "울산서부"),
            ("L1010000", "서울특별시", "L1010100", "서울동부"),
        )
        text = "\n".join(
            ",".join(
                (*row, "202608021000", "202608021100", "폭염", "중대경보", "변경", "")
            )
            for row in records
        )
        warnings = parse_warning_response(
            text, RiskPolicy.load(ROOT / "safety_dashboard/config/risk_policy.toml")
        )
        self.assertEqual(
            {item.region_code for item in warnings}, {row[2] for row in records[:-1]}
        )
        self.assertTrue(
            all(item.issued_at == dt.datetime(2026, 8, 2, 10) for item in warnings)
        )
        self.assertTrue(
            all(item.effective_at == dt.datetime(2026, 8, 2, 11) for item in warnings)
        )

    @patch(
        "safety_dashboard.adapters.kma.requests.get",
        side_effect=requests.ConnectionError("offline"),
    )
    def test_zone_failure_uses_official_bundled_geometry(self, _get):
        zones, health, detail = WarningZoneRepository(
            ROOT / "data/kma_warning_zones.geojson.gz"
        ).load()
        self.assertIs(health, DataHealth.FALLBACK)
        self.assertIn("내장본", detail)
        codes = {feature["properties"]["regid"] for feature in zones["features"]}
        self.assertTrue({"L1072400", "L1082800"}.issubset(codes))
