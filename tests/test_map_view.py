import datetime as dt
import gzip
import json
import unittest
from pathlib import Path

import pandas as pd

from ui.map_view import build_map


class MapViewTests(unittest.TestCase):
    def test_map_joins_warning_by_region_code_and_shows_times(self):
        path = Path(__file__).parents[1] / "data" / "kma_warning_zones.geojson.gz"
        with gzip.open(path, "rt", encoding="utf-8") as file:
            all_boundaries = json.load(file)
        boundary = next(
            feature
            for feature in all_boundaries["features"]
            if feature["properties"]["regid"] == "L1073110"
        )
        warnings = pd.DataFrame(
            [
                {
                    "region_code": "L1073110",
                    "region": "경주시중북부",
                    "type": "폭염",
                    "level": "중대경보",
                    "issued_at": dt.datetime(2026, 8, 2, 10, 0),
                    "effective_at": dt.datetime(2026, 8, 2, 11, 0),
                }
            ]
        )
        map_object = build_map(
            pd.DataFrame(columns=["latitude", "longitude"]),
            warnings,
            {"type": "FeatureCollection", "features": [boundary]},
        )
        markup = map_object.get_root().render()
        self.assertIn("경주시중북부", markup)
        self.assertIn("폭염 중대경보", markup)
        self.assertIn("발표 08-02 10:00", markup)
        self.assertIn("발효 08-02 11:00", markup)


if __name__ == "__main__":
    unittest.main()
