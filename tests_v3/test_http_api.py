import datetime as dt
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from safety_dashboard.api.app import create_app
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
        self.refresh_values = []

    def monitoring(self, force_refresh=False):
        self.refresh_values.append(force_refresh)
        return {"api_version": "v1", "facilities": []}


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
        self.assertEqual(payload["warning_zones"]["features"][0]["properties"]["label"], "호우 경보")
        self.assertNotIn("internal", str(payload["warning_zones"]))

    def test_kma_error_is_unavailable_not_no_impact(self):
        payload = serialize_monitoring(
            self.snapshot(DataHealth.ERROR), self.catalog, self.policy,
            None, DataHealth.FALLBACK, "내장 경계",
        )
        self.assertIsNone(payload["summary"])
        self.assertTrue(all(item["grade"] == "UNAVAILABLE" for item in payload["facilities"]))
        self.assertTrue(all(item["grade_label"] == "조회 불가" for item in payload["facilities"]))

    def test_http_route_forwards_manual_refresh_without_http_cache(self):
        service = _ApiService()
        client = TestClient(create_app(service))
        response = client.get("/api/v1/monitoring?refresh=true")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["api_version"], "v1")
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(service.refresh_values, [True])
        self.assertEqual(client.get("/api/v1/health").json()["status"], "ok")


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
