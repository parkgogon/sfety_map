"""KMA 기상특보와 연관된 결정적 모의훈련 기상 레이어 생성기."""

from __future__ import annotations

import datetime as dt
import math
import threading
from pathlib import Path
from typing import Sequence

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep

from safety_dashboard.adapters.weather_layers import (
    GRID_HEIGHT,
    GRID_WIDTH,
    KST,
    wind_metrics,
)
from safety_dashboard.domain.enums import DataHealth, WeatherLayerKind
from safety_dashboard.domain.models import (
    GeoPoint,
    WeatherGridPoint,
    WeatherLayerFeed,
)
from safety_dashboard.simulation.scenarios import (
    DEFAULT_SCENARIO,
    SimulationScenario,
)

# KMA 표준 Lambert Conformal Conic (LCC) 투영 상수
_RE = 6371.00877
_GRID = 5.0
_SLAT1 = 30.0
_SLAT2 = 60.0
_OLON = 126.0
_OLAT = 38.0
_XO = 43
_YO = 136

_PI = math.pi
_DEGRAD = _PI / 180.0
_RADDEG = 180.0 / _PI

_re = _RE / _GRID
_slat1 = _SLAT1 * _DEGRAD
_slat2 = _SLAT2 * _DEGRAD
_olon = _OLON * _DEGRAD
_olat = _OLAT * _DEGRAD

_sn = math.tan(_PI * 0.25 + _slat2 * 0.5) / math.tan(_PI * 0.25 + _slat1 * 0.5)
_sn = math.log(math.cos(_slat1) / math.cos(_slat2)) / math.log(_sn)
_sf = math.tan(_PI * 0.25 + _slat1 * 0.5)
_sf = math.pow(_sf, _sn) * math.cos(_slat1) / _sn
_ro = math.tan(_PI * 0.25 + _olat * 0.5)
_ro = _re * _sf / math.pow(_ro, _sn)


def _grid_to_latlon(x: int, y: int) -> tuple[float, float]:
    """KMA 격자 좌표 (1-indexed x, y)를 WGS84 위경도 (lat, lon)로 변환합니다."""
    xn = x - _XO
    yn = _ro - y + _YO
    ra = math.sqrt(xn * xn + yn * yn)
    if _sn < 0.0:
        ra = -ra
    alat = math.pow((_re * _sf / ra), (1.0 / _sn))
    alat = 2.0 * math.atan(alat) - _PI * 0.5
    if math.fabs(xn) <= 0.0:
        theta = 0.0
    else:
        if math.fabs(yn) <= 0.0:
            theta = _PI * 0.5
            if xn < 0.0:
                theta = -theta
        else:
            theta = math.atan2(xn, yn)
    alon = theta / _sn + _olon
    lat = alat * _RADDEG
    lon = alon * _RADDEG
    return lat, lon


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 위경도 지점 사이의 평면 근사 거리를 km 단위로 계산합니다."""
    d_lat = (lat1 - lat2) * 111.0
    d_lon = (lon1 - lon2) * 111.0 * math.cos(math.radians((lat1 + lat2) * 0.5))
    return math.hypot(d_lat, d_lon)


class SimulationWeatherLayerProvider:
    """결정적(deterministic) 기상 가정을 기반으로 훈련 레이어를 생성합니다.

    외부 KMA API를 호출하지 않으며, 동일 입력에 대해 항상 동일한 결과를 반환합니다.
    """

    _UNITS = {
        WeatherLayerKind.TEMPERATURE: "℃",
        WeatherLayerKind.RAINFALL: "mm",
        WeatherLayerKind.WIND: "m/s",
    }

    def __init__(
        self,
        scope_geometry: BaseGeometry,
        *,
        scenario: SimulationScenario = DEFAULT_SCENARIO,
    ) -> None:
        self.scenario = scenario
        self._scope = prep(scope_geometry)
        self._coordinate_lock = threading.Lock()
        self._scope_points: tuple[tuple[int, int, float, float], ...] | None = None

    def fetch(
        self,
        kind: WeatherLayerKind,
        now: dt.datetime | None = None,
    ) -> WeatherLayerFeed:
        reference = now or dt.datetime.now(KST)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=KST)
        reference = reference.astimezone(KST).replace(minute=0, second=0, microsecond=0)

        points = self._generate_points(kind)
        return WeatherLayerFeed(
            kind=kind,
            health=DataHealth.SIMULATION,
            observed_at=reference,
            fetched_at=reference,
            unit=self._UNITS[kind],
            points=points,
            message="모의훈련 기상 시나리오",
            scenario_id=self.scenario.id,
            scenario_label=self.scenario.label,
        )

    def _get_scope_points(self) -> tuple[tuple[int, int, float, float], ...]:
        if self._scope_points is not None:
            return self._scope_points
        with self._coordinate_lock:
            if self._scope_points is not None:
                return self._scope_points
            result = []
            for y in range(1, GRID_HEIGHT + 1):
                for x in range(1, GRID_WIDTH + 1):
                    lat, lon = _grid_to_latlon(x, y)
                    if 31.0 <= lat <= 40.0 and 124.0 <= lon <= 132.0:
                        if self._scope.covers(Point(lon, lat)):
                            result.append((x, y, lat, lon))
            self._scope_points = tuple(result)
            return self._scope_points

    def _generate_points(
        self,
        kind: WeatherLayerKind,
    ) -> tuple[WeatherGridPoint, ...]:
        scope_points = self._get_scope_points()
        result: list[WeatherGridPoint] = []

        # 시나리오 중심 좌표
        andong = (36.5684, 128.7294)  # 태풍 경보
        gumi = (36.1195, 128.3446)    # 강풍 주의보
        pohang = (36.0190, 129.3435)  # 호우 경보
        daegu = (35.8714, 128.6014)   # 폭염 경보

        for x, y, lat, lon in scope_points:
            location = GeoPoint(round(lat, 6), round(lon, 6))

            if kind is WeatherLayerKind.TEMPERATURE:
                # 기본 배경 기온 (24.0 ~ 26.0℃)
                base_temp = 26.0 - (lat - 35.0) * 0.8
                # 대구 폭염 경보 영향 (피크 37.5℃, 35~38℃ 범위)
                d_daegu = _distance_km(lat, lon, daegu[0], daegu[1])
                heat_effect = (37.5 - base_temp) * math.exp(-0.5 * (d_daegu / 22.0) ** 2)
                value = round(base_temp + heat_effect, 1)
                result.append(WeatherGridPoint(x, y, location, value=value))

            elif kind is WeatherLayerKind.RAINFALL:
                # 포항 호우 경보 (피크 45.0mm, 30~50mm 범위)
                d_pohang = _distance_km(lat, lon, pohang[0], pohang[1])
                rain_pohang = 45.0 * math.exp(-0.5 * (d_pohang / 18.0) ** 2)

                # 안동 태풍 경보 주변 강수 (피크 32.0mm, 20~40mm 범위)
                d_andong = _distance_km(lat, lon, andong[0], andong[1])
                rain_andong = 32.0 * math.exp(-0.5 * (d_andong / 25.0) ** 2)

                total_rain = max(rain_pohang, rain_andong)
                value = round(total_rain, 1) if total_rain >= 0.1 else 0.0
                result.append(WeatherGridPoint(x, y, location, value=value))

            elif kind is WeatherLayerKind.WIND:
                # 기본 배경 바람 (풍속 약 2.0m/s 남서풍: u=1.41, v=1.41)
                u_total = 1.41
                v_total = 1.41

                # 구미 강풍 주의보 (피크 약 13.0m/s, 북서풍 -> 135도 방향)
                d_gumi = _distance_km(lat, lon, gumi[0], gumi[1])
                gumi_scale = math.exp(-0.5 * (d_gumi / 14.0) ** 2)
                gumi_speed = 13.0 * gumi_scale
                u_total += gumi_speed * math.sin(math.radians(135.0))
                v_total += gumi_speed * math.cos(math.radians(135.0))

                # 안동 태풍 경보 (피크 25.0m/s 반시계방향 회전 바람장 + 중심 유입각 20도)
                dx_andong = (lon - andong[1]) * 111.0 * math.cos(math.radians(andong[0]))
                dy_andong = (lat - andong[0]) * 111.0
                dist_andong = math.hypot(dx_andong, dy_andong)
                if dist_andong > 0.001:
                    angle_andong = math.atan2(dy_andong, dx_andong)
                    # 반시계 회전 + 20도 유입각
                    flow_angle = angle_andong + _PI * 0.5 + math.radians(20.0)
                    # Rankine vortex with Gaussian outer cutoff (RMW = 12km, peak 25m/s)
                    rmw = 12.0
                    typhoon_speed = (
                        25.0
                        * (dist_andong / rmw)
                        * math.exp(1.0 - (dist_andong / rmw))
                        * math.exp(-0.5 * (dist_andong / 32.0) ** 2)
                    )
                    u_total += typhoon_speed * math.cos(flow_angle)
                    v_total += typhoon_speed * math.sin(flow_angle)

                speed, direction = wind_metrics(u_total, v_total)
                result.append(
                    WeatherGridPoint(
                        x,
                        y,
                        location,
                        u_ms=round(u_total, 2),
                        v_ms=round(v_total, 2),
                        speed_ms=round(speed, 1),
                        direction_to_deg=round(direction, 1),
                    )
                )

        return tuple(result)
