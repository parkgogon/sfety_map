import datetime as dt
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from safety_dashboard.api.app import create_app
from safety_dashboard.api.context_service import (
    FacilityContextService,
    FacilityNotFoundError,
)
from safety_dashboard.api.settings import ApiSettings
from safety_dashboard.application.context_info import KST
from safety_dashboard.application.cctv_directions import CctvDirectionCatalog
from safety_dashboard.domain import (
    ContextStatus,
    CctvFeed,
    DataHealth,
    GeoPoint,
    NearbyCctv,
    WeatherObservation,
)


class _Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class _WeatherProvider:
    def __init__(self, health=DataHealth.LIVE, raises=False):
        self.health = health
        self.raises = raises
        self.calls = 0

    def fetch(self, location, now=None):
        self.calls += 1
        if self.raises:
            raise RuntimeError("secret-bearing-provider-error")
        return WeatherObservation(
            observed_at=dt.datetime(2026, 8, 12, 6, 0, tzinfo=KST),
            health=self.health,
            temperature_c=28.5 if self.health is DataHealth.LIVE else None,
            rainfall_1h_mm=0,
            wind_speed_ms=2.3,
            wind_direction_deg=225,
            message="test weather",
        )


class _CctvProvider:
    def __init__(self, status=ContextStatus.LIVE, raises=False):
        self.status = status
        self.raises = raises
        self.calls = 0
        self.arguments = []

    def fetch_nearby(self, location, radius_km=20, limit=5):
        self.calls += 1
        self.arguments.append((location, radius_km, limit))
        if self.raises:
            raise RuntimeError("secret-bearing-provider-error")
        item = NearbyCctv(
            id="C-1",
            name="국도 CCTV",
            location=GeoPoint(36.01, 128.01),
            distance_km=1.5,
            road_type="국도",
            video_url="https://example.com/cctv.mp4",
            video_format="MP4",
        )
        return CctvFeed(
            status=self.status,
            cctvs=(item,) if self.status is ContextStatus.LIVE else (),
            fetched_at=dt.datetime(2026, 8, 12, 6, 1, tzinfo=KST),
            detail="test cctv",
        )


class _MonitoringService:
    def monitoring(self, force_refresh=False, simulation=False):
        return {"api_version": "v1", "facilities": []}


class _RouteContext:
    def weather(self, facility_id):
        if facility_id == "missing":
            raise FacilityNotFoundError(facility_id)
        return {"api_version": "v1", "facility_id": facility_id, "status": "LIVE"}

    def cctv(self, facility_id):
        if facility_id == "missing":
            raise FacilityNotFoundError(facility_id)
        return {"api_version": "v1", "facility_id": facility_id, "status": "ERROR"}


class FacilityContextServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        path = Path(self.directory.name) / "facilities.csv"
        path.write_text(
            "name,address,latitude,longitude,담당부서,시설코드,시설구분,부서 담당자\n"
            "테스트 시설,경북 구미시,36.0,128.0,환경부서,F-1,기타,홍길동\n",
            encoding="utf-8",
        )
        self.settings = ApiSettings(
            kma_api_key="key",
            its_cctv_api_key="key",
            facility_path=path,
            weather_cache_seconds=600,
            cctv_cache_seconds=60,
            context_error_cache_seconds=30,
        )

    def tearDown(self):
        self.directory.cleanup()

    def service(self, weather=None, cctv=None, clock=None):
        return FacilityContextService(
            self.settings,
            weather_provider=weather or _WeatherProvider(),
            cctv_provider=cctv or _CctvProvider(),
            direction_catalog=CctvDirectionCatalog.empty(),
            monotonic=clock or _Clock(),
        )

    def test_weather_and_cctv_have_independent_success_caches(self):
        clock = _Clock()
        weather = _WeatherProvider()
        cctv = _CctvProvider()
        service = self.service(weather, cctv, clock)

        first_weather = service.weather("F-1")
        service.weather("F-1")
        first_cctv = service.cctv("F-1")
        service.cctv("F-1")
        self.assertEqual(weather.calls, 1)
        self.assertEqual(cctv.calls, 1)
        self.assertEqual(first_weather["temperature_c"], 28.5)
        self.assertTrue(first_weather["actual_data"])
        self.assertTrue(first_cctv["cctvs"][0]["embed_allowed"])
        self.assertEqual(cctv.arguments[0][1:], (20, 5))

        clock.value = 61
        service.cctv("F-1")
        service.weather("F-1")
        self.assertEqual(cctv.calls, 2)
        self.assertEqual(weather.calls, 1)

        clock.value = 601
        service.weather("F-1")
        self.assertEqual(weather.calls, 2)

    def test_provider_errors_become_retryable_context_status(self):
        clock = _Clock()
        weather = _WeatherProvider(raises=True)
        cctv = _CctvProvider(raises=True)
        service = self.service(weather, cctv, clock)

        self.assertEqual(service.weather("F-1")["status"], "ERROR")
        self.assertEqual(service.cctv("F-1")["status"], "ERROR")
        clock.value = 29
        service.weather("F-1")
        service.cctv("F-1")
        self.assertEqual((weather.calls, cctv.calls), (1, 1))
        clock.value = 31
        service.weather("F-1")
        service.cctv("F-1")
        self.assertEqual((weather.calls, cctv.calls), (2, 2))

    def test_unknown_facility_is_not_sent_to_external_providers(self):
        weather = _WeatherProvider()
        cctv = _CctvProvider()
        service = self.service(weather, cctv)
        with self.assertRaises(FacilityNotFoundError):
            service.weather("missing")
        with self.assertRaises(FacilityNotFoundError):
            service.cctv("missing")
        self.assertEqual((weather.calls, cctv.calls), (0, 0))


class FacilityContextRouteTests(unittest.TestCase):
    def test_read_only_routes_and_404_are_stable(self):
        client = TestClient(create_app(_MonitoringService(), _RouteContext()))
        weather = client.get("/api/v1/facilities/F-1/weather")
        cctv = client.get("/api/v1/facilities/F-1/cctv")
        self.assertEqual(weather.status_code, 200)
        self.assertEqual(cctv.status_code, 200)
        self.assertEqual(weather.headers["cache-control"], "private, no-store")
        self.assertEqual(cctv.json()["status"], "ERROR")
        self.assertEqual(
            client.get("/api/v1/facilities/missing/weather").status_code,
            404,
        )
        self.assertEqual(
            client.get("/api/v1/facilities/missing/cctv").status_code,
            404,
        )


if __name__ == "__main__":
    unittest.main()
