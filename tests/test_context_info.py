import datetime as dt
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import requests

from safety_dashboard.adapters.disaster_messages import (
    SafetyDataDisasterMessageProvider,
    parse_disaster_response,
)
from safety_dashboard.application.context_info import (
    KST,
    build_news_search_url,
    resolve_facility_region,
    select_relevant_disaster_messages,
)
from safety_dashboard.domain import (
    ContextStatus,
    DisasterMessage,
    Facility,
    GeoPoint,
)


class RegionTests(unittest.TestCase):
    def test_real_address_variants_are_normalized(self):
        cases = {
            "경북 포항시 남구 주소": ("경상북도", "포항시 남구"),
            "포항 북구 항구동": ("경상북도", "포항시 북구"),
            "대구시 달서구 성서공단로": ("대구광역시", "달서구"),
            "부산 진구 가야대로": ("부산광역시", "부산진구"),
            "울산 울준군 온산읍": ("울산광역시", "울주군"),
        }
        for address, expected in cases.items():
            with self.subTest(address=address):
                region = resolve_facility_region(address)
                self.assertIsNotNone(region)
                self.assertEqual((region.province, region.district), expected)
                self.assertEqual(region.query_name, expected[0])

    def test_unrecognized_address_returns_none(self):
        self.assertIsNone(resolve_facility_region("주소 미상"))


class DisasterMessageTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 5, 6, 0, tzinfo=KST)
        self.region = resolve_facility_region("경북 포항시 남구")

    def message(self, identifier, hours, kind, regions):
        return DisasterMessage(
            identifier,
            self.now - dt.timedelta(hours=hours),
            "긴급재난",
            kind,
            f"문자 {identifier}",
            (regions,),
        )

    def test_filter_applies_time_type_region_dedup_and_limit(self):
        values = [
            self.message("local", 1, "호우", "경상북도 포항시 남구"),
            self.message("province", 2, "산불", "경상북도 전체"),
            self.message("province-short", 2.5, "산불", "경북 전역"),
            self.message("nationwide", 2.7, "지진", "전국"),
            self.message("other", 1, "호우", "경상북도 구미시"),
            self.message("sibling", 1, "호우", "경상북도 포항시 북구"),
            self.message("old", 7, "호우", "경상북도 포항시"),
            self.message("irrelevant", 1, "감염병", "경상북도 포항시"),
            self.message("local", 3, "호우", "경상북도 포항시"),
        ]
        selected = select_relevant_disaster_messages(
            values, self.region, self.now - dt.timedelta(hours=6)
        )
        self.assertEqual(
            [item.id for item in selected],
            ["local", "province", "province-short", "nationwide"],
        )

    def test_official_response_fields_are_parsed(self):
        payload = {
            "body": {
                "totalCount": 1,
                "items": [
                    {
                        "SN": "123",
                        "CRT_DT": "2026/08/05 05:30:00",
                        "MSG_CN": "포항시 호우 안전안내",
                        "RCPTN_RGN_NM": "경상북도 포항시 남구",
                        "EMRG_STEP_NM": "안전안내",
                        "DST_SE_NM": "호우",
                    }
                ],
            }
        }
        messages = parse_disaster_response(payload)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].id, "123")
        self.assertEqual(messages[0].created_at.tzinfo, KST)
        self.assertEqual(messages[0].content, "포항시 호우 안전안내")

    def test_not_configured_provider_is_independent_state(self):
        feed = SafetyDataDisasterMessageProvider("").fetch_recent(
            self.region, self.now - dt.timedelta(hours=6)
        )
        self.assertEqual(feed.status, ContextStatus.NOT_CONFIGURED)
        self.assertEqual(feed.messages, ())

    @patch(
        "safety_dashboard.adapters.disaster_messages.requests.get",
        side_effect=requests.Timeout,
    )
    def test_provider_timeout_returns_error_without_raising(self, _get):
        feed = SafetyDataDisasterMessageProvider("test-key").fetch_recent(
            self.region, self.now - dt.timedelta(hours=6)
        )
        self.assertEqual(feed.status, ContextStatus.ERROR)
        self.assertEqual(feed.messages, ())
        self.assertNotIn("test-key", feed.detail)

    def test_news_link_uses_google_news_required_region_or_warnings_and_date(self):
        facility = Facility(
            "1", "포항 시설", "대기", GeoPoint(36, 129), "경북 포항시"
        )
        url = build_news_search_url(
            facility,
            self.region,
            ("호우", "호우", "강풍"),
            reference_date=dt.date(2026, 8, 5),
        )
        parsed = urlsplit(url)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual((parsed.netloc, parsed.path), ("www.google.com", "/search"))
        self.assertEqual(query["tbm"], ["nws"])
        self.assertEqual(query["hl"], ["ko"])
        self.assertEqual(query["gl"], ["KR"])
        self.assertEqual(query["as_q"], ["포항 남구 after:2026-07-29"])
        self.assertEqual(query["as_oq"], ["호우 강풍"])
        self.assertNotIn("재난", query["as_q"][0])

    def test_news_location_normalizes_province_and_metropolitan_regions(self):
        facility = Facility(
            "1", "시설", "대기", GeoPoint(36, 129), "주소"
        )
        cases = {
            "경북 구미시 주소": "구미",
            "경북 포항시 남구 주소": "포항 남구",
            "울산 남구 주소": "울산 남구",
            "부산 남구 주소": "부산 남구",
        }
        for address, expected in cases.items():
            with self.subTest(address=address):
                region = resolve_facility_region(address)
                url = build_news_search_url(
                    facility,
                    region,
                    ("호우",),
                    reference_date=dt.date(2026, 8, 5),
                )
                query = parse_qs(urlsplit(url).query)
                self.assertEqual(
                    query["as_q"],
                    [f"{expected} after:2026-07-29"],
                )

    def test_news_link_falls_back_to_facility_and_general_incident_terms(self):
        facility = Facility(
            "1", "해오름 시설", "대기", GeoPoint(36, 129), "주소 미상"
        )
        url = build_news_search_url(
            facility,
            None,
            (),
            reference_date=dt.date(2026, 8, 5),
        )
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["as_q"], ["해오름 시설 after:2026-07-29"])
        self.assertEqual(query["as_oq"], ["재난 사고 통제 대피"])


if __name__ == "__main__":
    unittest.main()
