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

    def layer(self, kind, mode="live"):
        self.calls.append((kind, mode))
        return {
            "api_version": "v1",
            "layer": kind.value,
            "status": "SIMULATION" if mode == "simulation" else "LIVE",
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


class SimulationWeatherLayerTests(unittest.TestCase):
    def setUp(self):
        from safety_dashboard.simulation.scenarios import (
            DEFAULT_SCENARIO,
            MULTI_HAZARD_SCENARIO,
            create_simulation_warnings,
        )
        from safety_dashboard.simulation.weather_layers import (
            SimulationWeatherLayerProvider,
        )
        from safety_dashboard.domain.risk_policy import RiskPolicy

        self.scenario = DEFAULT_SCENARIO
        self.policy = RiskPolicy.load("safety_dashboard/config/risk_policy.toml")
        self.scope = load_monitoring_scope(
            Path("data/kma_warning_zones.geojson.gz")
        )
        self.provider = SimulationWeatherLayerProvider(
            self.scope, scenario=self.scenario
        )

    def test_simulation_warnings_match_scenario_definition(self):
        from safety_dashboard.simulation.scenarios import create_simulation_warnings

        warnings = create_simulation_warnings(self.policy, self.scenario)
        self.assertEqual(len(warnings), 4)
        warning_map = {w.region: (w.warning_type, w.raw_level) for w in warnings}
        self.assertEqual(warning_map["포항시"], ("호우", "경보"))
        self.assertEqual(warning_map["구미시"], ("강풍", "주의보"))
        self.assertEqual(warning_map["대구중부"], ("폭염", "경보"))
        self.assertEqual(warning_map["안동시"], ("태풍", "경보"))

    def test_simulation_provider_is_deterministic(self):
        moment = dt.datetime(2026, 8, 29, 12, 0, tzinfo=KST)
        feed1 = self.provider.fetch(WeatherLayerKind.TEMPERATURE, moment)
        feed2 = self.provider.fetch(WeatherLayerKind.TEMPERATURE, moment)
        self.assertEqual(feed1.health, DataHealth.SIMULATION)
        self.assertEqual(len(feed1.points), len(feed2.points))
        self.assertEqual(
            [p.value for p in feed1.points],
            [p.value for p in feed2.points],
        )

    def test_temperature_assumption_ranges(self):
        moment = dt.datetime(2026, 8, 29, 12, 0, tzinfo=KST)
        feed = self.provider.fetch(WeatherLayerKind.TEMPERATURE, moment)
        # 대구 폭염 중심 근처 (lat ~35.87, lon ~128.60)
        daegu_points = [
            p for p in feed.points
            if abs(p.location.latitude - 35.8714) < 0.15
            and abs(p.location.longitude - 128.6014) < 0.15
        ]
        self.assertTrue(daegu_points)
        max_daegu_temp = max(p.value for p in daegu_points)
        self.assertTrue(35.0 <= max_daegu_temp <= 38.0, f"Daegu temp {max_daegu_temp} not in 35~38")

    def test_rainfall_assumption_ranges(self):
        moment = dt.datetime(2026, 8, 29, 12, 0, tzinfo=KST)
        feed = self.provider.fetch(WeatherLayerKind.RAINFALL, moment)
        # 포항 호우 중심 근처 (lat ~36.02, lon ~129.34)
        pohang_points = [
            p for p in feed.points
            if abs(p.location.latitude - 36.0190) < 0.15
            and abs(p.location.longitude - 129.3435) < 0.15
        ]
        self.assertTrue(pohang_points)
        max_pohang_rain = max(p.value for p in pohang_points)
        self.assertTrue(30.0 <= max_pohang_rain <= 50.0, f"Pohang rain {max_pohang_rain} not in 30~50")

        # 안동 태풍 주변 강수 (lat ~36.57, lon ~128.73)
        andong_points = [
            p for p in feed.points
            if abs(p.location.latitude - 36.5684) < 0.2
            and abs(p.location.longitude - 128.7294) < 0.2
        ]
        self.assertTrue(andong_points)
        max_andong_rain = max(p.value for p in andong_points)
        self.assertTrue(20.0 <= max_andong_rain <= 40.0, f"Andong rain {max_andong_rain} not in 20~40")

    def test_wind_assumption_ranges(self):
        moment = dt.datetime(2026, 8, 29, 12, 0, tzinfo=KST)
        feed = self.provider.fetch(WeatherLayerKind.WIND, moment)
        # 안동 태풍 중심 근처
        andong_points = [
            p for p in feed.points
            if abs(p.location.latitude - 36.5684) < 0.2
            and abs(p.location.longitude - 128.7294) < 0.2
        ]
        self.assertTrue(andong_points)
        max_andong_wind = max(p.speed_ms for p in andong_points)
        self.assertTrue(20.0 <= max_andong_wind <= 28.0, f"Andong wind {max_andong_wind} not in 20~28")

        # 구미 강풍 중심 근처
        gumi_points = [
            p for p in feed.points
            if abs(p.location.latitude - 36.1195) < 0.15
            and abs(p.location.longitude - 128.3446) < 0.15
        ]
        self.assertTrue(gumi_points)
        max_gumi_wind = max(p.speed_ms for p in gumi_points)
        self.assertTrue(12.0 <= max_gumi_wind <= 16.0, f"Gumi wind {max_gumi_wind} not in 12~16")


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
        self.assertEqual(first["actual_data"], True)
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

    def test_simulation_mode_is_isolated_from_live_cache(self):
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
        sim_data = service.layer(WeatherLayerKind.TEMPERATURE, mode="simulation")
        self.assertEqual(sim_data["status"], "SIMULATION")
        self.assertEqual(sim_data["actual_data"], False)
        self.assertEqual(sim_data["scenario_id"], "multi_hazard_demo")
        self.assertEqual(sim_data["source"], "모의훈련 시나리오")
        # live provider 호출이 발생하지 않아야 함
        self.assertEqual(provider.calls, 0)

        # live 호출은 독립적으로 live provider를 호출
        live_data = service.layer(WeatherLayerKind.TEMPERATURE, mode="live")
        self.assertEqual(live_data["status"], "LIVE")
        self.assertEqual(live_data["actual_data"], True)
        self.assertEqual(provider.calls, 1)

    def test_http_route_validates_kind_and_mode(self):
        layer_service = _RouteLayerService()
        client = TestClient(
            create_app(_MonitoringService(), _ContextService(), layer_service)
        )
        # 1. live 기본값
        response = client.get(
            "/api/v1/weather/layers/wind",
            headers={"Accept-Encoding": "gzip"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["layer"], "wind")
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(layer_service.calls[-1], (WeatherLayerKind.WIND, "live"))

        # 2. simulation 모드 쿼리
        response_sim = client.get("/api/v1/weather/layers/rainfall?mode=simulation")
        self.assertEqual(response_sim.status_code, 200)
        self.assertEqual(response_sim.json()["status"], "SIMULATION")
        self.assertEqual(layer_service.calls[-1], (WeatherLayerKind.RAINFALL, "simulation"))

        # 3. 잘못된 kind는 422
        self.assertEqual(
            client.get("/api/v1/weather/layers/radar").status_code,
            422,
        )

        # 4. 잘못된 mode는 422
        self.assertEqual(
            client.get("/api/v1/weather/layers/wind?mode=unknown").status_code,
            422,
        )


if __name__ == "__main__":
    unittest.main()
