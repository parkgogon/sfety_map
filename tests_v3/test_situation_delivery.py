import datetime as dt
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from safety_dashboard.adapters.telegram import TelegramNotifier
from safety_dashboard.application.contacts import public_contact
from safety_dashboard.application.deep_links import (
    build_facility_url,
    dashboard_home_url,
    expand_scope_for_facility,
)
from safety_dashboard.application.facility_groups import FacilityGroupCatalog
from safety_dashboard.application.notifications import build_telegram_payloads
from safety_dashboard.domain import (
    DashboardSnapshot,
    DashboardSummary,
    DataHealth,
    Facility,
    GeoPoint,
    NearbyCctv,
    OutgoingTelegramMessage,
    RiskGrade,
    Warning,
    WarningFeed,
    WarningLevel,
)
from safety_dashboard.domain.risk_policy import RiskPolicy
from safety_dashboard.ui.map_view import build_monitoring_map


ROOT = Path(__file__).parents[1]
POLICY = RiskPolicy.load(ROOT / "safety_dashboard/config/risk_policy.toml")
CATALOG = FacilityGroupCatalog.load(
    ROOT / "safety_dashboard/config/facility_groups.toml"
)


def situation_snapshot() -> DashboardSnapshot:
    now = dt.datetime(2026, 8, 5, 6, 0)
    high_warning = Warning(
        "w-high", "기상청", "up", "area", "경상북도", "포항시",
        "호우", "경보", WarningLevel.WARNING,
        issued_at=now, effective_at=now,
    )
    unknown_warning = replace(
        high_warning,
        id="w-unknown",
        warning_type="미등록 <특보>",
        raw_level="알수없음",
        level=WarningLevel.UNKNOWN,
    )
    facilities = (
        Facility(
            "air & 1", "포항 <대기>", "대기측정소",
            GeoPoint(36.0, 129.0), "경북 포항시 남구",
            department="대기관리부", manager="김담당 대리(010-1234-5678)",
        ),
        Facility(
            "water", "포항 수질", "수질측정소",
            GeoPoint(36.1, 129.1), "경북 포항시 북구",
            department="유역관리부", manager="박담당 010 234 5678",
        ),
    )
    assessments = (
        POLICY.assess(facilities[0], (high_warning,), now),
        POLICY.assess(facilities[1], (unknown_warning,), now),
    )
    return DashboardSnapshot(
        generated_at=now,
        warning_feed=WarningFeed(
            (high_warning, unknown_warning), DataHealth.LIVE, now
        ),
        facilities=facilities,
        assessments=assessments,
        summary=DashboardSummary(2, 2, 1, 1, WarningLevel.WARNING),
        policy_version=POLICY.version,
    )


class PublicContactTests(unittest.TestCase):
    def test_phone_is_removed_and_department_and_name_remain(self):
        facility = Facility(
            "1", "시설", "기타", GeoPoint(36, 128), "대구",
            department="환경안전경영부",
            manager="강건호 대리(010-4429-2514)",
        )
        self.assertEqual(
            public_contact(facility),
            "환경안전경영부 · 강건호 대리",
        )

    def test_department_only_is_used_when_manager_is_only_a_phone(self):
        facility = Facility(
            "1", "시설", "기타", GeoPoint(36, 128), "대구",
            department="대기관리부", manager="010.1234.5678",
        )
        self.assertEqual(public_contact(facility), "대기관리부")

    def test_international_mobile_format_is_also_removed(self):
        facility = Facility(
            "1", "시설", "기타", GeoPoint(36, 128), "대구",
            department="대기관리부", manager="김담당 +82-10-1234-5678",
        )
        self.assertEqual(public_contact(facility), "대기관리부 · 김담당")


class DeepLinkTests(unittest.TestCase):
    def test_only_valid_https_base_url_builds_encoded_link(self):
        self.assertEqual(dashboard_home_url("http://example.com"), "")
        self.assertEqual(dashboard_home_url("https://user:pw@example.com"), "")
        self.assertEqual(
            build_facility_url("https://example.com/dashboard?old=1", "air & 1"),
            "https://example.com/dashboard?facility_id=air+%26+1",
        )

    def test_facility_group_and_current_grade_are_added_to_scope(self):
        snapshot = situation_snapshot()
        expanded = expand_scope_for_facility(
            snapshot,
            CATALOG,
            ["water"],
            [RiskGrade.LOW],
            "air & 1",
        )
        self.assertIsNotNone(expanded)
        self.assertEqual(expanded.facility_id, "air & 1")
        self.assertIn("air", expanded.group_ids)
        self.assertIn("water", expanded.group_ids)
        self.assertIn(RiskGrade.HIGH, expanded.grades)
        self.assertIn(RiskGrade.LOW, expanded.grades)
        self.assertIsNone(
            expand_scope_for_facility(snapshot, CATALOG, [], [], "missing")
        )


class TelegramPayloadTests(unittest.TestCase):
    def test_summary_is_audible_and_all_details_are_silent_and_linked(self):
        snapshot = situation_snapshot()
        payloads = build_telegram_payloads(
            snapshot,
            scope_label="전체 <시설>",
            dashboard_base_url="https://dashboard.example/app",
        )
        self.assertFalse(payloads[0].silent)
        self.assertEqual(payloads[0].action_url, "https://dashboard.example/app")
        self.assertTrue(all(item.silent for item in payloads[1:]))
        self.assertIn("영향 특보</b>  2건", payloads[0].text)
        self.assertIn("상 1 · 미판정 1", payloads[0].text)
        self.assertIn("전체 &lt;시설&gt;", payloads[0].text)
        combined = "\n".join(item.text for item in payloads[1:])
        self.assertEqual(combined.count("포항 &lt;대기&gt;"), 1)
        self.assertEqual(combined.count("포항 수질"), 1)
        self.assertLess(combined.index("상 등급"), combined.index("미판정 등급"))
        self.assertIn("facility_id=air+%26+1", combined)
        self.assertIn("대기관리부 · 김담당 대리", combined)
        self.assertNotIn("010-1234-5678", combined)

    def test_low_only_summary_is_silent_and_invalid_base_has_no_links(self):
        source = situation_snapshot()
        low_facility = replace(source.facilities[0], id="low", name="하 시설")
        low_assessment = replace(
            source.assessments[0],
            facility=low_facility,
            grade=RiskGrade.LOW,
        )
        snapshot = replace(
            source,
            facilities=(low_facility,),
            assessments=(low_assessment,),
            warning_feed=replace(source.warning_feed, warnings=(source.warning_feed.warnings[0],)),
            summary=DashboardSummary(1, 1, 0, 0, WarningLevel.WARNING),
        )
        payloads = build_telegram_payloads(
            snapshot,
            dashboard_base_url="http://unsafe.example",
        )
        self.assertTrue(payloads[0].silent)
        self.assertEqual(payloads[0].action_url, "")
        self.assertNotIn("<a href", "\n".join(item.text for item in payloads))

    def test_detail_pages_keep_every_facility_within_limit(self):
        source = situation_snapshot()
        assessments = tuple(
            replace(
                source.assessments[0],
                facility=replace(
                    source.facilities[0],
                    id=f"facility-{index}",
                    name=f"선택 시설 {index:03}",
                ),
            )
            for index in range(60)
        )
        snapshot = replace(
            source,
            facilities=tuple(item.facility for item in assessments),
            assessments=assessments,
            warning_feed=replace(
                source.warning_feed,
                warnings=(source.warning_feed.warnings[0],),
            ),
            summary=DashboardSummary(1, 60, 60, 0, WarningLevel.WARNING),
        )
        payloads = build_telegram_payloads(snapshot, max_length=700)
        self.assertTrue(all(len(item.text) <= 700 for item in payloads))
        combined = "\n".join(item.text for item in payloads[1:])
        self.assertTrue(
            all(combined.count(f"선택 시설 {index:03}") == 1 for index in range(60))
        )

    def test_focused_map_uses_facility_coordinates_and_zoom(self):
        map_obj = build_monitoring_map(
            situation_snapshot(),
            None,
            focus_facility_id="air & 1",
        )
        self.assertEqual(map_obj.location, [36.0, 129.0])
        self.assertEqual(map_obj.options["zoom"], 13)
        markup = map_obj.get_root().render()
        self.assertIn("선택 시설", markup)
        self.assertIn("mobile-map-interaction-control", markup)
        self.assertIn("지도 조작 켜기", markup)
        self.assertIn("페이지 스크롤 우선", markup)
        self.assertIn("map.dragging", markup)
        self.assertIn("window.top.innerWidth", markup)
        self.assertIn("viewportWidth <= 700", markup)
        self.assertIn("container.style.touchAction", markup)
        self.assertIn("disableClickPropagation", markup)
        self.assertNotIn("L.control.layers", markup)

    def test_map_adds_distinct_cctv_layer_marker_and_focus_bounds(self):
        unknown_cctv = NearbyCctv(
            "cctv-one",
            "포항 교차로 CCTV",
            GeoPoint(36.02, 129.02),
            2.9,
            "국도",
            "https://video.example/cctv.mp4",
            "MP4",
        )
        verified_cctv = NearbyCctv(
            "cctv-two",
            "포항 해안로 CCTV",
            GeoPoint(36.03, 129.03),
            3.7,
            "고속도로",
            "https://video.example/cctv-two.mp4",
            "MP4",
            bearing_deg=135.0,
            direction_verified_on=dt.date(2026, 8, 6),
            direction_source="현장 영상 검증",
        )
        map_obj = build_monitoring_map(
            situation_snapshot(),
            None,
            nearby_cctvs=(unknown_cctv, verified_cctv),
            cctv_focus_facility_id="air & 1",
        )
        markup = map_obj.get_root().render()
        self.assertIn(
            "인근 교통 CCTV",
            [
                item.layer_name
                for item in map_obj._children.values()
                if hasattr(item, "layer_name")
            ],
        )
        self.assertIn("포항 교차로 CCTV", markup)
        self.assertIn("촬영방향 미확인", markup)
        self.assertIn("포항 해안로 CCTV", markup)
        self.assertIn("촬영방향 남동 135°", markup)
        self.assertIn("rotate(135.0deg)", markup)
        self.assertEqual(markup.count("cctv-direction-marker"), 1)
        self.assertNotIn("마커를 누르면 큰 영상 작업창이 열립니다", markup)
        self.assertIn("video-camera", markup)
        self.assertIn("fitBounds", markup)

    @patch("safety_dashboard.adapters.telegram.requests.post")
    def test_notifier_applies_delivery_and_inline_button(self, post: Mock):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"ok": True}
        post.return_value = response
        messages = [
            OutgoingTelegramMessage(
                "summary", False, "대시보드에서 확인", "https://example.com"
            ),
            OutgoingTelegramMessage("detail", True),
        ]
        result = TelegramNotifier("token", "chat").send_batch(messages)
        self.assertTrue(result.success)
        first = post.call_args_list[0].kwargs["json"]
        second = post.call_args_list[1].kwargs["json"]
        self.assertFalse(first["disable_notification"])
        self.assertEqual(
            first["reply_markup"]["inline_keyboard"][0][0]["url"],
            "https://example.com",
        )
        self.assertTrue(first["link_preview_options"]["is_disabled"])
        self.assertTrue(second["disable_notification"])
        self.assertNotIn("reply_markup", second)


if __name__ == "__main__":
    unittest.main()
