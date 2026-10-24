import datetime as dt
import unittest
from unittest.mock import Mock, patch

import requests

from safety_dashboard.adapters.cctv import (
    CctvDataError,
    ItsCctvProvider,
    parse_cctv_response,
)
from safety_dashboard.application.context_info import (
    KST,
    describe_cctv_timing,
    find_clicked_cctv,
)
from safety_dashboard.domain import ContextStatus, GeoPoint, NearbyCctv


ORIGIN = GeoPoint(36.0, 129.0)


def cctv_row(
    name: str,
    latitude: float,
    longitude: float,
    url: str = "https://video.example/cctv.mp4",
) -> dict:
    return {
        "cctvname": name,
        "coordx": str(longitude),
        "coordy": str(latitude),
        "cctvurl": url,
        "cctvformat": "MP4",
        "filecreatetime": "20260805063000",
    }


def json_payload(rows: list[dict]) -> dict:
    return {"response": {"datacount": len(rows), "data": rows}}


def response_with(payload: object) -> Mock:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    response.text = ""
    return response


class CctvParsingTests(unittest.TestCase):
    def test_json_and_xml_responses_are_normalized(self):
        parsed = parse_cctv_response(
            json_payload([cctv_row("포항 CCTV", 36.01, 129.01)]),
            "ex",
            ORIGIN,
        )
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].road_type, "고속도로")
        self.assertEqual(parsed[0].updated_at.tzinfo, KST)
        self.assertGreater(parsed[0].distance_km, 0)

        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <response><datacount>1</datacount><data>
          <cctvname>국도 CCTV</cctvname><coordx>129.02</coordx><coordy>36.02</coordy>
          <cctvurl>http://video.example/cctv.mp4</cctvurl>
          <cctvformat>MP4</cctvformat><filecreatetime>20260805063100</filecreatetime>
        </data></response>"""
        parsed_xml = parse_cctv_response(xml, "its", ORIGIN)
        self.assertEqual(len(parsed_xml), 1)
        self.assertEqual(parsed_xml[0].road_type, "국도")
        self.assertTrue(parsed_xml[0].video_url.startswith("http://"))

    def test_invalid_coordinates_and_video_urls_are_rejected(self):
        payload = json_payload(
            [cctv_row("오류", 36.01, 129.01, "javascript:alert(1)")]
        )
        with self.assertRaises(CctvDataError):
            parse_cctv_response(payload, "its", ORIGIN)

    def test_clicked_coordinates_select_only_cctv_marker(self):
        cctv = NearbyCctv(
            "one",
            "인근 CCTV",
            GeoPoint(36.01, 129.01),
            1.4,
            "국도",
            "https://video.example/one.mp4",
        )
        self.assertEqual(
            find_clicked_cctv((cctv,), {"lat": 36.010001, "lng": 129.010001}),
            cctv,
        )
        self.assertIsNone(
            find_clicked_cctv((cctv,), {"lat": 36.1, "lng": 129.1})
        )
        self.assertIsNone(find_clicked_cctv((cctv,), None))

    def test_timing_distinguishes_source_time_from_api_fetch_time(self):
        fetched_at = dt.datetime(2026, 8, 6, 6, 10, 30, tzinfo=KST)
        now = dt.datetime(2026, 8, 6, 6, 12, 0, tzinfo=KST)
        cctv = NearbyCctv(
            "one",
            "인근 CCTV",
            GeoPoint(36.01, 129.01),
            1.4,
            "국도",
            "https://video.example/one.mp4",
            updated_at=dt.datetime(2026, 8, 6, 6, 9, 0, tzinfo=KST),
        )
        source, fetched, known = describe_cctv_timing(cctv, fetched_at, now)
        self.assertTrue(known)
        self.assertIn("06:09:00", source)
        self.assertIn("약 3분 전", source)
        self.assertIn("06:10:30", fetched)
        self.assertIn("약 1분 전", fetched)

        missing_source, fetched, known = describe_cctv_timing(
            NearbyCctv(
                "two",
                "시각 없는 CCTV",
                GeoPoint(36.02, 129.02),
                2.0,
                "국도",
                "https://video.example/two.mp4",
            ),
            fetched_at,
            now,
        )
        self.assertFalse(known)
        self.assertIn("ITS 미제공", missing_source)
        self.assertIn("영상 주소 조회", fetched)


class CctvProviderTests(unittest.TestCase):
    @patch("safety_dashboard.adapters.cctv.requests.get")
    def test_missing_key_does_not_call_network(self, get: Mock):
        feed = ItsCctvProvider("").fetch_nearby(ORIGIN)
        self.assertEqual(feed.status, ContextStatus.NOT_CONFIGURED)
        self.assertEqual(feed.cctvs, ())
        get.assert_not_called()

    @patch("safety_dashboard.adapters.cctv.requests.get")
    def test_two_road_types_use_mp4_bounds_and_nearest_five(self, get: Mock):
        rows = [
            cctv_row(f"CCTV {index}", 36 + index * 0.01, 129)
            for index in range(1, 7)
        ]
        rows.append(cctv_row("20km 밖", 36.25, 129))
        rows.append(cctv_row("CCTV 1", 36.01, 129))

        def fake_get(_url, *, params, timeout):
            self.assertEqual(params["cctvType"], 5)
            self.assertEqual(params["getType"], "json")
            self.assertLess(params["minX"], ORIGIN.longitude)
            self.assertGreater(params["maxX"], ORIGIN.longitude)
            self.assertLess(params["minY"], ORIGIN.latitude)
            self.assertGreater(params["maxY"], ORIGIN.latitude)
            self.assertEqual(timeout, 7)
            return response_with(
                json_payload(rows if params["type"] == "ex" else [])
            )

        get.side_effect = fake_get
        feed = ItsCctvProvider("key").fetch_nearby(ORIGIN, radius_km=20, limit=5)
        self.assertEqual(feed.status, ContextStatus.LIVE)
        self.assertEqual(len(get.call_args_list), 2)
        self.assertEqual(
            [item.name for item in feed.cctvs],
            [f"CCTV {i}" for i in range(1, 6)],
        )
        self.assertTrue(all(item.distance_km <= 20 for item in feed.cctvs))

    @patch("safety_dashboard.adapters.cctv.requests.get")
    def test_partial_failure_keeps_successful_road_type(self, get: Mock):
        def fake_get(_url, *, params, timeout):
            del timeout
            if params["type"] == "its":
                raise requests.Timeout
            return response_with(json_payload([cctv_row("고속도로", 36.01, 129)]))

        get.side_effect = fake_get
        feed = ItsCctvProvider("key").fetch_nearby(ORIGIN)
        self.assertEqual(feed.status, ContextStatus.LIVE)
        self.assertEqual(len(feed.cctvs), 1)
        self.assertIn("일부 조회 실패", feed.detail)

    @patch(
        "safety_dashboard.adapters.cctv.requests.get",
        side_effect=requests.Timeout,
    )
    def test_all_timeouts_return_independent_error(self, _get: Mock):
        feed = ItsCctvProvider("secret-key").fetch_nearby(ORIGIN)
        self.assertEqual(feed.status, ContextStatus.ERROR)
        self.assertEqual(feed.cctvs, ())
        self.assertNotIn("secret-key", feed.detail)


if __name__ == "__main__":
    unittest.main()
