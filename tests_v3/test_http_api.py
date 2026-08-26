import dataclasses
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from safety_dashboard.api.app import create_app
from safety_dashboard.api.service import MonitoringApiService
from safety_dashboard.api.settings import ApiSettings
from safety_dashboard.api.serialization import serialize_monitoring
from safety_dashboard.adapters.facility_csv import CsvFacilityRepository, FacilityDataError
from safety_dashboard.application.facility_groups import FacilityGroup, FacilityGroupCatalog
from safety_dashboard.application.monitoring import MonitoringService
from safety_dashboard.domain import (
    DashboardSnapshot,
    DashboardSummary,
    DataHealth,
    Facility,
    GeoPoint,
    RiskGrade,
    Warning,
    WarningFeed,
    WarningLevel,
)
from safety_dashboard.domain.risk_policy import RiskPolicy
from safety_dashboard.monitoring.snapshot import MonitoringSnapshot


KST = dt.timezone(dt.timedelta(hours=9))
TEST_ZONES = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"regid": "L1070300", "regko": "구미시"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [127.0, 35.0],
                        [130.0, 35.0],
                        [130.0, 37.0],
                        [127.0, 37.0],
                        [127.0, 35.0],
                    ]
                ],
            },
        }
    ],
}


class _Repository:
    def __init__(self, facilities):
        self.facilities = facilities

    def list_monitored(self):
        return self.facilities


class _Provider:
    def __init__(self, feed):
        self.feed = feed

    def fetch_active(self):
        return self.feed


class _Matcher:
    def matches(self, facility, warning):
        return facility.id == "F-1"


class _ApiService:
    def __init__(self):
        self.calls = []

    def monitoring(self, force_refresh=False, simulation=False):
        self.calls.append((force_refresh, simulation))
        return {"api_version": "v1", "facilities": []}


class _SnapshotStore:
    def __init__(self, snapshot=None, *, error=None):
        self.snapshot = snapshot
        self.error = error
        self.load_count = 0

    def load_latest(self):
        self.load_count += 1
        if self.error is not None:
            raise self.error
        return self.snapshot

    def save_latest(self, _snapshot):
        raise AssertionError("공개 API는 snapshot을 저장하면 안 됩니다.")


class MonitoringApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = RiskPolicy.load("safety_dashboard/config/risk_policy.toml")
        cls.catalog = FacilityGroupCatalog(
            (
                FacilityGroup("air", "대기측정소", ("대기측정소",)),
                FacilityGroup("other", "기타시설", (), fallback=True),
            )
        )
        cls.now = dt.datetime(2026, 8, 11, 9, 0)
        cls.facilities = (
            Facility(
                "F-1",
                "테스트 측정소",
                "대기측정소",
                GeoPoint(36.0, 128.0),
                "경북 구미시 테스트로 1",
                "환경서비스처 대기관리부",
                "홍길동 대리(010-1234-5678)",
            ),
            Facility(
                "F-2",
                "영향 없음 시설",
                "새 시설 유형",
                GeoPoint(35.9, 128.1),
                "경북 구미시 테스트로 2",
            ),
        )
        cls.warning = Warning(
            "W-1",
            "기상청",
            "L1070000",
            "L1070300",
            "경상북도",
            "구미시",
            "호우",
            "경보",
            WarningLevel.WARNING,
            issued_at=cls.now,
            effective_at=cls.now,
        )

    def snapshot(self, health=DataHealth.LIVE):
        feed = WarningFeed(
            (self.warning,) if health is DataHealth.LIVE else (),
            health,
            self.now,
            "KMA 장애" if health is DataHealth.ERROR else "",
        )
        return MonitoringService(
            _Repository(self.facilities),
            _Provider(feed),
            _Matcher(),
            self.policy,
        ).get_snapshot(self.now)

    def test_serialization_removes_phone_and_keeps_group_and_reason(self):
        zone_data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "regid": "L1070300",
                        "internal": "API에 노출하면 안 되는 원본 속성",
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[128, 36], [129, 36], [128, 37], [128, 36]]],
                    },
                }
            ],
        }
        payload = serialize_monitoring(
            self.snapshot(), self.catalog, self.policy,
            zone_data, DataHealth.LIVE, "최신 경계",
        )
        first = payload["facilities"][0]
        second = payload["facilities"][1]
        self.assertEqual(first["grade"], RiskGrade.HIGH.value)
        self.assertEqual(first["reasons"][0]["type"], "호우")
        self.assertEqual(first["public_contact"], "환경서비스처 대기관리부 · 홍길동 대리")
        self.assertNotIn("010", str(payload))
        self.assertEqual(second["group_id"], "other")
        self.assertEqual(second["meaning"], "특보의 영향권에 들지 않음")
        self.assertEqual(payload["warning_zones"]["features"][0]["properties"]["label"], "호우 경보")
        self.assertNotIn("internal", str(payload["warning_zones"]))

    def test_kma_error_is_unavailable_not_no_impact(self):
        payload = serialize_monitoring(
            self.snapshot(DataHealth.ERROR), self.catalog, self.policy,
            None, DataHealth.FALLBACK, "내장 경계",
        )
        self.assertIsNone(payload["summary"])
        self.assertEqual(
            payload["status"]["detail"],
            "KMA 특보 자료 수신이 지연되고 있습니다. "
            "공식 특보를 함께 확인해 주세요.",
        )
        self.assertNotIn("KMA 장애", payload["status"]["detail"])
        self.assertTrue(all(item["grade"] == "UNAVAILABLE" for item in payload["facilities"]))
        self.assertTrue(all(item["grade_label"] == "조회 불가" for item in payload["facilities"]))
        self.assertTrue(all(item["grade_color"] == "#667085" for item in payload["facilities"]))
        self.assertTrue(all(
            item["meaning"] == "기상청 데이터 미수신으로 위험등급 판정불가"
            for item in payload["facilities"]
        ))

    def test_http_route_forwards_manual_refresh_without_http_cache(self):
        service = _ApiService()
        client = TestClient(create_app(service))
        response = client.get("/api/v1/monitoring?refresh=true")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["api_version"], "v1")
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(service.calls, [(True, False)])
        simulation = client.get("/api/v1/monitoring?mode=simulation")
        self.assertEqual(simulation.status_code, 200)
        self.assertEqual(service.calls[-1], (False, True))
        self.assertEqual(
            client.get("/api/v1/monitoring?mode=unknown").status_code,
            422,
        )
        self.assertEqual(client.get("/api/v1/health").json()["status"], "ok")

    def test_simulation_uses_existing_scenario_without_calling_kma(self):
        store = _SnapshotStore(error=AssertionError("모의훈련은 저장본을 읽지 않습니다."))
        service = MonitoringApiService(ApiSettings(kma_api_key=""))
        service._monitoring_snapshot_store = store
        service._zones = lambda _: (  # type: ignore[method-assign]
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"regid": "L1070300", "regko": "구미시"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[127.0, 35.0], [130.0, 35.0], [130.0, 37.0],
                                 [127.0, 37.0], [127.0, 35.0]]
                            ],
                        },
                    }
                ],
            },
            DataHealth.LIVE,
            "테스트 경계",
        )
        with patch(
            "safety_dashboard.api.service.KmaWarningProvider",
            side_effect=AssertionError("모의훈련에서 KMA를 호출하면 안 됩니다."),
        ):
            payload = service.monitoring(simulation=True)

        self.assertEqual(payload["status"]["health"], DataHealth.SIMULATION.value)
        self.assertEqual(len(payload["warnings"]), 4)
        self.assertTrue(
            all(item["source"] == "모의훈련" for item in payload["warnings"])
        )
        self.assertEqual(store.load_count, 0)

    def test_fresh_firestore_snapshot_is_used_without_kma_call(self):
        current = dt.datetime(2026, 8, 11, 9, 5, tzinfo=KST)
        stored = MonitoringSnapshot.capture(
            self.snapshot(DataHealth.LIVE),
            stored_at=current - dt.timedelta(minutes=4),
        )
        store = _SnapshotStore(stored)
        service = MonitoringApiService(
            ApiSettings(kma_api_key="unused"),
            clock=lambda: current,
            monitoring_snapshot_store=store,
        )
        service._zones = lambda _: (  # type: ignore[method-assign]
            TEST_ZONES,
            DataHealth.FALLBACK,
            "내장 경계",
        )

        with patch(
            "safety_dashboard.api.service.KmaWarningProvider",
            side_effect=AssertionError("최신 저장본이 있으면 KMA를 재조회하면 안 됩니다."),
        ):
            payload = service.monitoring()

        self.assertEqual(store.load_count, 1)
        self.assertEqual(payload["status"]["health"], DataHealth.LIVE.value)
        self.assertEqual(payload["generated_at"], "2026-08-11T09:00:00+09:00")
        self.assertEqual(payload["summary"]["affected_facility_count"], 1)
        self.assertEqual(len(payload["facilities"]), 2)

    def test_stale_firestore_snapshot_is_fallback_when_kma_fails(self):
        current = dt.datetime(2026, 8, 11, 10, 0, tzinfo=KST)
        stored = MonitoringSnapshot.capture(
            self.snapshot(DataHealth.LIVE),
            stored_at=current - dt.timedelta(hours=1),
        )
        store = _SnapshotStore(stored)
        service = MonitoringApiService(
            ApiSettings(
                kma_api_key="",
                monitoring_snapshot_fresh_seconds=900,
            ),
            clock=lambda: current,
            monitoring_snapshot_store=store,
        )
        service._zones = lambda _: (  # type: ignore[method-assign]
            TEST_ZONES,
            DataHealth.FALLBACK,
            "내장 경계",
        )

        payload = service.monitoring()

        self.assertEqual(payload["status"]["health"], DataHealth.STALE.value)
        self.assertEqual(payload["status"]["fetched_at"], "2026-08-11T09:00:00+09:00")
        self.assertEqual(payload["summary"]["affected_facility_count"], 1)
        self.assertIn("마지막 정상 자료", payload["status"]["detail"])

    def test_snapshot_store_error_falls_back_to_existing_kma_path(self):
        store = _SnapshotStore(error=RuntimeError("Firestore 장애"))
        service = MonitoringApiService(
            ApiSettings(kma_api_key=""),
            monitoring_snapshot_store=store,
        )
        service._zones = lambda _: (  # type: ignore[method-assign]
            TEST_ZONES,
            DataHealth.FALLBACK,
            "내장 경계",
        )

        payload = service.monitoring()

        self.assertEqual(store.load_count, 1)
        self.assertEqual(payload["status"]["health"], DataHealth.ERROR.value)
        self.assertIsNone(payload["summary"])

    def test_snapshot_with_different_policy_is_not_reused(self):
        source = self.snapshot(DataHealth.LIVE)
        old_policy_dashboard = dataclasses.replace(
            source,
            policy_version="old-policy",
            assessments=tuple(
                dataclasses.replace(item, policy_version="old-policy")
                for item in source.assessments
            ),
        )
        store = _SnapshotStore(
            MonitoringSnapshot.capture(old_policy_dashboard)
        )
        service = MonitoringApiService(
            ApiSettings(kma_api_key=""),
            monitoring_snapshot_store=store,
        )
        service._zones = lambda _: (  # type: ignore[method-assign]
            TEST_ZONES,
            DataHealth.FALLBACK,
            "내장 경계",
        )

        payload = service.monitoring()

        self.assertEqual(store.load_count, 1)
        self.assertEqual(payload["status"]["health"], DataHealth.ERROR.value)
        self.assertIsNone(payload["summary"])

    def test_forced_refresh_is_shared_during_server_cooldown(self):
        clock = [100.0]
        service = MonitoringApiService(
            ApiSettings(
                kma_api_key="",
                monitoring_cache_seconds=300,
                monitoring_refresh_cooldown_seconds=60,
            ),
            monotonic=lambda: clock[0],
        )
        builds = []

        def build_payload(_now, *, simulation=False):
            builds.append(simulation)
            return {"build": len(builds), "simulation": simulation}

        service._build_payload = build_payload  # type: ignore[method-assign]

        first = service.monitoring()
        clock[0] = 110.0
        repeated = service.monitoring(force_refresh=True)
        self.assertIs(repeated, first)
        self.assertEqual(builds, [False])

        clock[0] = 161.0
        refreshed = service.monitoring(force_refresh=True)
        self.assertEqual(refreshed["build"], 2)
        self.assertEqual(builds, [False, False])

    def test_kma_failure_keeps_last_successful_monitoring_as_stale(self):
        clock = [100.0]
        service = MonitoringApiService(
            ApiSettings(
                kma_api_key="",
                monitoring_cache_seconds=300,
                monitoring_refresh_cooldown_seconds=60,
            ),
            monotonic=lambda: clock[0],
        )
        live_snapshot = self.snapshot(DataHealth.LIVE)
        error_snapshot = self.snapshot(DataHealth.ERROR)
        service._build_snapshot = Mock(  # type: ignore[method-assign]
            side_effect=(
                (
                    live_snapshot,
                    self.catalog,
                    self.policy,
                    None,
                    DataHealth.FALLBACK,
                    "내장 경계",
                ),
                (
                    error_snapshot,
                    self.catalog,
                    self.policy,
                    None,
                    DataHealth.FALLBACK,
                    "내장 경계",
                ),
            )
        )

        live = service.monitoring()
        clock[0] = 161.0
        stale = service.monitoring(force_refresh=True)

        self.assertEqual(live["status"]["health"], DataHealth.LIVE.value)
        self.assertEqual(stale["status"]["health"], DataHealth.STALE.value)
        self.assertEqual(stale["generated_at"], live["generated_at"])
        self.assertEqual(
            stale["status"]["fetched_at"],
            live["status"]["fetched_at"],
        )
        self.assertEqual(stale["summary"], live["summary"])
        self.assertEqual(stale["warnings"], live["warnings"])
        self.assertEqual(
            [item["grade"] for item in stale["facilities"]],
            [item["grade"] for item in live["facilities"]],
        )
        self.assertIn("마지막 정상 자료", stale["status"]["detail"])

    def test_cold_start_kma_failure_remains_unavailable(self):
        service = MonitoringApiService(ApiSettings(kma_api_key=""))
        error_snapshot = self.snapshot(DataHealth.ERROR)
        service._build_snapshot = Mock(  # type: ignore[method-assign]
            return_value=(
                error_snapshot,
                self.catalog,
                self.policy,
                None,
                DataHealth.FALLBACK,
                "내장 경계",
            )
        )

        payload = service.monitoring()

        self.assertEqual(payload["status"]["health"], DataHealth.ERROR.value)
        self.assertIsNone(payload["summary"])
        self.assertTrue(
            all(item["grade"] == "UNAVAILABLE" for item in payload["facilities"])
        )


class FacilityCsvValidationTests(unittest.TestCase):
    def test_duplicate_facility_id_blocks_deployment_data(self):
        header = "name,address,latitude,longitude,담당부서,시설코드,시설구분,부서 담당자\n"
        rows = (
            "시설1,경북 구미시,36.0,128.0,부서,1001,기타,담당자\n"
            "시설2,경북 구미시,36.1,128.1,부서,1001.0,기타,담당자\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "facilities.csv"
            path.write_text(header + rows, encoding="utf-8")
            with self.assertRaisesRegex(FacilityDataError, "중복"):
                CsvFacilityRepository(path).list_monitored()


if __name__ == "__main__":
    unittest.main()
