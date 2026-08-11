import datetime as dt
import unittest
from pathlib import Path
from unittest.mock import Mock

from safety_dashboard.adapters.current_weather import CurrentWeatherProvider, KST
from safety_dashboard.application.map_selection import resolve_map_selection
from safety_dashboard.domain import (
    DashboardSnapshot,
    DashboardSummary,
    DataHealth,
    Facility,
    GeoPoint,
    RiskGrade,
    WarningFeed,
    WarningLevel,
)
from safety_dashboard.domain.risk_policy import RiskPolicy
from safety_dashboard.ui.map_view import build_monitoring_map


class _Response:
    def __init__(self, *, text="", payload=None):
        self.text = text
        self._payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class CurrentWeatherTests(unittest.TestCase):
    def test_missing_key_never_calls_network(self):
        session = Mock()
        observation = CurrentWeatherProvider("", session=session).fetch(
            GeoPoint(36.0, 128.0)
        )
        self.assertIs(observation.health, DataHealth.ERROR)
        self.assertIn("API 키", observation.message)
        session.get.assert_not_called()

    def test_grid_and_observation_are_parsed_without_default_coordinates(self):
        session = Mock()
        session.get.side_effect = [
            _Response(text="# header\n128.0,36.0,87,93\n"),
            _Response(
                payload={
                    "response": {
                        "header": {"resultCode": "00"},
                        "body": {
                            "items": {
                                "item": [
                                    {"category": "T1H", "obsrValue": "31.2"},
                                    {"category": "RN1", "obsrValue": "4.5"},
                                    {"category": "WSD", "obsrValue": "3.1"},
                                    {"category": "VEC", "obsrValue": "225"},
                                ]
                            }
                        },
                    }
                }
            ),
        ]
        reference = dt.datetime(2026, 8, 10, 10, 35, tzinfo=KST)
        observation = CurrentWeatherProvider("key", session=session).fetch(
            GeoPoint(36.0, 128.0), reference
        )
        self.assertIs(observation.health, DataHealth.LIVE)
        self.assertEqual(observation.observed_at.hour, 9)
        self.assertEqual(observation.temperature_c, 31.2)
        self.assertEqual(observation.rainfall_1h_mm, 4.5)
        self.assertEqual(observation.wind_speed_ms, 3.1)
        self.assertEqual(observation.wind_direction_deg, 225.0)
        self.assertEqual(session.get.call_args_list[1].kwargs["params"]["nx"], "87")
        self.assertEqual(session.get.call_args_list[1].kwargs["params"]["ny"], "93")

    def test_invalid_grid_returns_error_instead_of_daegu_fallback(self):
        session = Mock()
        session.get.return_value = _Response(text="# no grid\n")
        observation = CurrentWeatherProvider("key", session=session).fetch(
            GeoPoint(35.0, 129.0)
        )
        self.assertIs(observation.health, DataHealth.ERROR)
        self.assertEqual(session.get.call_count, 1)

    def test_grid_lookup_is_cached_for_the_same_facility_location(self):
        observation_payload = {
            "response": {
                "header": {"resultCode": "00"},
                "body": {
                    "items": {
                        "item": [
                            {
                                "category": "T1H",
                                "obsrValue": "27",
                                "baseDate": "20260812",
                                "baseTime": "0600",
                            }
                        ]
                    }
                },
            }
        }
        session = Mock()
        session.get.side_effect = [
            _Response(text="128.0,36.0,87,93\n"),
            _Response(payload=observation_payload),
            _Response(payload=observation_payload),
        ]
        provider = CurrentWeatherProvider("key", session=session)
        point = GeoPoint(36.0, 128.0)
        provider.fetch(point)
        provider.fetch(point)

        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(
            sum("dfs_xy_lonlat" in call.args[0] for call in session.get.call_args_list),
            1,
        )


class FieldMapSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = RiskPolicy.load("safety_dashboard/config/risk_policy.toml")

    def snapshot(self):
        now = dt.datetime(2026, 8, 10, 6, 0)
        facilities = (
            Facility("same-1", "공유좌표 1", "기타", GeoPoint(36, 128), "주소1"),
            Facility("same-2", "공유좌표 2", "기타", GeoPoint(36, 128), "주소2"),
        )
        assessments = tuple(
            self.policy.assess(item, (), now) for item in facilities
        )
        return DashboardSnapshot(
            generated_at=now,
            warning_feed=WarningFeed((), DataHealth.LIVE, now),
            facilities=facilities,
            assessments=assessments,
            summary=DashboardSummary(0, 0, 0, 0, WarningLevel.UNKNOWN),
            policy_version=self.policy.version,
        )

    def test_tooltip_id_distinguishes_facilities_with_same_coordinates(self):
        snapshot = self.snapshot()
        selection = resolve_map_selection(
            snapshot,
            (),
            "시설 · 공유좌표 2 · 없음 · 시설 ID · same-2",
            {"lat": 36.0, "lng": 128.0},
        )
        self.assertIsNotNone(selection)
        self.assertEqual(selection.facility_id, "same-2")

    def test_field_map_has_grade_layers_and_unlocked_mobile_control(self):
        markup = build_monitoring_map(
            self.snapshot(),
            None,
            mobile_initially_locked=False,
            grade_layers=True,
        ).get_root().render()
        self.assertIn("시설 ID · same-1", markup)
        self.assertIn("initialLocked = false", markup)
        self.assertIn("L.control.layers", markup)


class FieldMobileLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.app_source = (root / "app.py").read_text()
        cls.page_source = (root / "safety_dashboard/ui/pages/field_map.py").read_text()
        cls.styles = (root / "safety_dashboard/ui/style.css").read_text()
        cls.tokens = (root / "safety_dashboard/ui/design_tokens.css").read_text()

    def test_mobile_uses_compact_field_status_and_hides_redundant_copy(self):
        self.assertIn('class="status-strip field-status-strip"', self.page_source)
        self.assertIn('class="field-status-mobile"', self.page_source)
        self.assertIn('key="field-map-caption"', self.page_source)
        self.assertIn('key="field-detail-title"', self.page_source)
        self.assertNotIn('class="mobile-only mobile-map-help"', self.page_source)
        self.assertIn(".field-intro { display: none; }", self.styles)
        self.assertIn(".st-key-field-map-caption,", self.styles)
        self.assertIn(".st-key-field-detail-title,", self.styles)
        self.assertIn(
            ':has(> .st-key-field-map-caption)',
            self.styles,
        )

    def test_mobile_field_map_is_viewport_width_square(self):
        self.assertIn("height=650", self.page_source)
        self.assertIn(
            "height: calc(100vw - 1.6rem) !important;",
            self.styles,
        )

    def test_active_navigation_forces_nested_icon_and_label_white(self):
        self.assertIn(
            '.st-key-role-navigation a[aria-current="page"] span,',
            self.styles,
        )
        self.assertIn(
            "color: var(--color-on-strong) !important;",
            self.styles,
        )

    def test_shared_design_tokens_are_loaded_before_page_styles(self):
        self.assertIn('safety_dashboard/ui/design_tokens.css', self.app_source)
        self.assertIn('safety_dashboard/ui/style.css', self.app_source)
        self.assertLess(
            self.app_source.index('safety_dashboard/ui/design_tokens.css'),
            self.app_source.index('safety_dashboard/ui/style.css'),
        )
        self.assertIn("--color-risk-high: #d92d20;", self.tokens)
        self.assertIn("--touch-target-min: 44px;", self.tokens)


if __name__ == "__main__":
    unittest.main()
