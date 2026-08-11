import datetime as dt
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from shapely.geometry import Polygon

from safety_dashboard.adapters.weather_layers import (
    GRID_HEIGHT,
    GRID_VALUE_COUNT,
    GRID_WIDTH,
    GridWeatherLayerProvider,
    KST,
    load_monitoring_scope,
    parse_grid_values,
    wind_metrics,
)
from safety_dashboard.api.app import create_app
from safety_dashboard.api.settings import ApiSettings
from safety_dashboard.api.weather_layer_service import WeatherLayerService
from safety_dashboard.domain import (
    DataHealth,
    GeoPoint,
    WeatherGridPoint,
    WeatherLayerFeed,
    WeatherLayerKind,
)


def _grid(value=-99.0, *, first=None):
    values = [value] * GRID_VALUE_COUNT
    if first is not None:
        values[0] = first
    return ",".join(str(item) for item in values)


class _Response:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")


class _GridSession:
    def __init__(self):
        self.calls = []
        self.data_attempts = 0

    def get(self, url, params, timeout):
        self.calls.append((url, dict(params), timeout))
        if "latlon" in url:
            axis = params["latlon"]
            values = [-99.0] * GRID_VALUE_COUNT
            values[0] = 36.1 if axis == "lat" else 128.3
            return _Response(
                f"{GRID_WIDTH},{GRID_HEIGHT}," + ",".join(map(str, values))
            )
        self.data_attempts += 1
        # 첫 번째 시각은 아직 발표되지 않은 상태를 재현합니다.
        return _Response(
            _grid(first=None if self.data_attempts == 1 else 27.4)
        )


class _Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class _LayerProvider:
    def __init__(self):
        self.calls = 0

    def fetch(self, kind, now=None):
        self.calls += 1
        live = self.calls == 1
        moment = dt.datetime(2026, 8, 12, 6, 50, tzinfo=KST)
        return WeatherLayerFeed(
            kind=kind,
            health=DataHealth.LIVE if live else DataHealth.ERROR,
            observed_at=moment,
            fetched_at=moment,
            unit="℃",
            points=(
                WeatherGridPoint(1, 1, GeoPoint(36.1, 128.3), value=27.4),
            ) if live else (),
            message="정상" if live else "장애",
        )


class _MonitoringService:
    def monitoring(self, force_refresh=False, simulation=False):
        return {"api_version": "v1", "facilities": []}


class _ContextService:
    def weather(self, facility_id):
        return {"api_version": "v1", "facility_id": facility_id}

    def cctv(self, facility_id):
        return {"api_version": "v1", "facility_id": facility_id}


class _RouteLayerService:
    def __init__(self):
        self.calls = []

    def layer(self, kind):
        self.calls.append(kind)
        return {
            "api_version": "v1",
            "layer": kind.value,
            "status": "LIVE",
            "points": [{"value": index} for index in range(200)],
        }


class WeatherLayerAdapterTests(unittest.TestCase):
    def test_grid_parser_accepts_dimension_header_and_rejects_wrong_size(self):
        text = f"{GRID_WIDTH},{GRID_HEIGHT}," + _grid(first=12.3)
        values = parse_grid_values(text)
        self.assertEqual(len(values), GRID_VALUE_COUNT)
        self.assertEqual(values[0], 12.3)
        with self.assertRaisesRegex(ValueError, "격자 크기"):
            parse_grid_values("1,2,3")

    def test_temperature_falls_back_and_keeps_coordinate_index(self):
        session = _GridSession()
        provider = GridWeatherLayerProvider(
            "key",
            Polygon(((128, 36), (129, 36), (129, 37), (128, 37))),
            session=session,
        )
        feed = provider.fetch(
            WeatherLayerKind.TEMPERATURE,
            dt.datetime(2026, 8, 12, 7, 5, tzinfo=KST),
        )
        self.assertEqual(feed.health, DataHealth.LIVE)
        self.assertEqual(feed.observed_at.strftime("%H:%M"), "06:40")
        self.assertEqual(len(feed.points), 1)
        self.assertEqual(feed.points[0].value, 27.4)
        self.assertEqual(feed.points[0].location, GeoPoint(36.1, 128.3))
        self.assertEqual((feed.points[0].grid_x, feed.points[0].grid_y), (1, 1))
        # 좌표는 첫 호출 후 provider 프로세스 동안 재사용합니다.
        provider.fetch(
            WeatherLayerKind.TEMPERATURE,
            dt.datetime(2026, 8, 12, 7, 15, tzinfo=KST),
        )
        coordinate_calls = [call for call in session.calls if "latlon" in call[0]]
        self.assertEqual(len(coordinate_calls), 2)

    def test_wind_direction_points_toward_flow(self):
        self.assertEqual(wind_metrics(1, 0), (1.0, 90.0))
        self.assertEqual(wind_metrics(0, 1), (1.0, 0.0))
        speed, direction = wind_metrics(-1, 0)
        self.assertEqual(speed, 1.0)
        self.assertEqual(direction, 270.0)

    def test_real_scope_contains_all_five_metropolitan_geometries(self):
        scope = load_monitoring_scope(
            Path("data/kma_warning_zones.geojson.gz")
        )
        self.assertTrue(scope.covers(__import__("shapely").geometry.Point(128.3, 36.1)))
        self.assertTrue(scope.covers(__import__("shapely").geometry.Point(129.05, 35.15)))


class WeatherLayerServiceTests(unittest.TestCase):
    def test_success_cache_and_stale_last_success(self):
        clock = _Clock()
        provider = _LayerProvider()
        settings = ApiSettings(
            kma_api_key="key",
            weather_layer_cache_seconds=600,
            weather_layer_error_cache_seconds=60,
        )
        service = WeatherLayerService(
            settings,
            provider=provider,
            monotonic=clock,
            now=lambda: dt.datetime(2026, 8, 12, 7, 0, tzinfo=KST),
        )
        first = service.layer(WeatherLayerKind.TEMPERATURE)
        service.layer(WeatherLayerKind.TEMPERATURE)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(first["status"], "LIVE")
        self.assertEqual(first["points"][0]["value"], 27.4)

        clock.value = 601
        stale = service.layer(WeatherLayerKind.TEMPERATURE)
        self.assertEqual(provider.calls, 2)
        self.assertEqual(stale["status"], "STALE")
        self.assertEqual(stale["points"], first["points"])
        self.assertIn("마지막 정상", stale["detail"])

        clock.value = 650
        service.layer(WeatherLayerKind.TEMPERATURE)
        self.assertEqual(provider.calls, 2)

    def test_http_route_validates_kind_and_is_gzipped(self):
        layer_service = _RouteLayerService()
        client = TestClient(
            create_app(_MonitoringService(), _ContextService(), layer_service)
        )
        response = client.get(
            "/api/v1/weather/layers/wind",
            headers={"Accept-Encoding": "gzip"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["layer"], "wind")
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.headers.get("content-encoding"), "gzip")
        self.assertEqual(layer_service.calls, [WeatherLayerKind.WIND])
        self.assertEqual(
            client.get("/api/v1/weather/layers/radar").status_code,
            422,
        )


if __name__ == "__main__":
    unittest.main()
