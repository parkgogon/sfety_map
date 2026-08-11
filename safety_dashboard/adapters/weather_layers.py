"""KMA 동네예보 전체 격자를 지도용 실황 레이어로 변환합니다."""

from __future__ import annotations

import datetime as dt
import gzip
import json
import math
import re
import threading
from pathlib import Path
from typing import Any, Mapping

import requests
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.prepared import prep

from safety_dashboard.domain.enums import DataHealth, WeatherLayerKind
from safety_dashboard.domain.models import (
    GeoPoint,
    WeatherGridPoint,
    WeatherLayerFeed,
)


KST = dt.timezone(dt.timedelta(hours=9))
GRID_WIDTH = 149
GRID_HEIGHT = 253
GRID_VALUE_COUNT = GRID_WIDTH * GRID_HEIGHT
GRID_DATA_URL = (
    "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_odam_grd"
)
GRID_COORDINATE_URL = (
    "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_latlon_api"
)
SCOPE_REGION_CODES = (
    "L1070000",
    "L1080000",
    "L1140000",
    "L1150000",
    "L1160000",
)
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")


def parse_grid_values(text: str) -> tuple[float, ...]:
    """ASCII 격자 응답을 순서를 유지한 149×253 배열로 변환합니다."""

    values = [float(value) for value in _NUMBER.findall(str(text or ""))]
    if (
        len(values) == GRID_VALUE_COUNT + 2
        and int(values[0]) == GRID_WIDTH
        and int(values[1]) == GRID_HEIGHT
    ):
        values = values[2:]
    if len(values) != GRID_VALUE_COUNT:
        raise ValueError("기상청 격자 크기가 예상과 다릅니다.")
    return tuple(values)


def wind_metrics(u_ms: float, v_ms: float) -> tuple[float, float]:
    """동서·남북 성분을 풍속과 바람이 향하는 방위각으로 변환합니다."""

    speed = math.hypot(u_ms, v_ms)
    direction_to = (math.degrees(math.atan2(u_ms, v_ms)) + 360) % 360
    return speed, direction_to


def load_monitoring_scope(path: Path) -> BaseGeometry:
    """내장 특보구역의 5개 광역 도형을 하나의 관제 권역으로 만듭니다."""

    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as file:
        payload = json.load(file)
    geometries = []
    for feature in payload.get("features", []):
        properties: Mapping[str, Any] = feature.get("properties", {})
        code = str(
            properties.get("regid")
            or properties.get("regId")
            or properties.get("id")
            or ""
        )
        if code in SCOPE_REGION_CODES:
            geometries.append(shape(feature.get("geometry")))
    if len(geometries) != len(SCOPE_REGION_CODES):
        raise ValueError("관제 5개 권역 도형을 모두 찾지 못했습니다.")
    return unary_union(geometries)


class GridWeatherLayerProvider:
    """실황 격자를 가져와 관제 권역의 지도 표시값만 반환합니다."""

    _VARIABLES = {
        WeatherLayerKind.TEMPERATURE: ("T1H",),
        WeatherLayerKind.RAINFALL: ("RN1",),
        WeatherLayerKind.WIND: ("UUU", "VVV"),
    }
    _UNITS = {
        WeatherLayerKind.TEMPERATURE: "℃",
        WeatherLayerKind.RAINFALL: "mm",
        WeatherLayerKind.WIND: "m/s",
    }

    def __init__(
        self,
        api_key: str,
        scope_geometry: BaseGeometry,
        *,
        timeout: float = 7,
        session: Any = requests,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.timeout = timeout
        self.session = session
        self._scope = prep(scope_geometry)
        self._coordinate_lock = threading.Lock()
        self._coordinates: tuple[tuple[float, float], ...] | None = None
        self._scope_indices: tuple[int, ...] | None = None

    def fetch(
        self,
        kind: WeatherLayerKind,
        now: dt.datetime | None = None,
    ) -> WeatherLayerFeed:
        reference = now or dt.datetime.now(KST)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=KST)
        reference = reference.astimezone(KST)
        fetched_at = dt.datetime.now(KST)
        if not self.api_key:
            return self._error(kind, reference, fetched_at, "KMA API 키가 설정되지 않았습니다.")

        try:
            coordinates, scope_indices = self._coordinate_data()
        except (requests.RequestException, ValueError, TypeError, KeyError):
            return self._error(
                kind,
                reference,
                fetched_at,
                "기상청 격자 위치를 확인하지 못했습니다.",
            )

        latest = _floor_ten_minutes(reference - dt.timedelta(minutes=10))
        for offset in (0, 10, 20):
            observed_at = latest - dt.timedelta(minutes=offset)
            try:
                variables = {
                    variable: self._fetch_variable(variable, observed_at)
                    for variable in self._VARIABLES[kind]
                }
                points = self._points(
                    kind,
                    variables,
                    coordinates,
                    scope_indices,
                )
            except (requests.RequestException, ValueError, TypeError, KeyError):
                continue
            if points:
                return WeatherLayerFeed(
                    kind=kind,
                    health=DataHealth.LIVE,
                    observed_at=observed_at,
                    fetched_at=fetched_at,
                    unit=self._UNITS[kind],
                    points=points,
                    message="기상청 동네예보 격자 실황",
                )
        return self._error(
            kind,
            latest,
            fetched_at,
            "최근 기상 격자 실황이 아직 제공되지 않았습니다.",
        )

    def _coordinate_data(
        self,
    ) -> tuple[tuple[tuple[float, float], ...], tuple[int, ...]]:
        if self._coordinates is not None and self._scope_indices is not None:
            return self._coordinates, self._scope_indices
        with self._coordinate_lock:
            if self._coordinates is not None and self._scope_indices is not None:
                return self._coordinates, self._scope_indices
            latitudes = self._fetch_coordinate("lat")
            longitudes = self._fetch_coordinate("lon")
            coordinates = tuple(zip(latitudes, longitudes, strict=True))
            indices = tuple(
                index
                for index, (latitude, longitude) in enumerate(coordinates)
                if (
                    31 <= latitude <= 44
                    and 123 <= longitude <= 133
                    and self._scope.covers(Point(longitude, latitude))
                )
            )
            if not indices:
                raise ValueError("관제 권역의 기상 격자가 없습니다.")
            self._coordinates = coordinates
            self._scope_indices = indices
            return coordinates, indices

    def _fetch_coordinate(self, axis: str) -> tuple[float, ...]:
        response = self.session.get(
            GRID_COORDINATE_URL,
            params={
                "fct": "VSRT",
                "latlon": axis,
                "disp": "A",
                "authKey": self.api_key,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return parse_grid_values(response.text)

    def _fetch_variable(
        self,
        variable: str,
        observed_at: dt.datetime,
    ) -> tuple[float, ...]:
        response = self.session.get(
            GRID_DATA_URL,
            params={
                "tmfc": observed_at.strftime("%Y%m%d%H%M"),
                "vars": variable,
                "authKey": self.api_key,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return parse_grid_values(response.text)

    def _points(
        self,
        kind: WeatherLayerKind,
        variables: Mapping[str, tuple[float, ...]],
        coordinates: tuple[tuple[float, float], ...],
        scope_indices: tuple[int, ...],
    ) -> tuple[WeatherGridPoint, ...]:
        result = []
        for index in scope_indices:
            latitude, longitude = coordinates[index]
            grid_x = index % GRID_WIDTH + 1
            grid_y = index // GRID_WIDTH + 1
            if kind is WeatherLayerKind.WIND:
                u_ms = variables["UUU"][index]
                v_ms = variables["VVV"][index]
                if not _valid(u_ms) or not _valid(v_ms):
                    continue
                speed, direction = wind_metrics(u_ms, v_ms)
                result.append(
                    WeatherGridPoint(
                        grid_x=grid_x,
                        grid_y=grid_y,
                        location=GeoPoint(latitude, longitude),
                        u_ms=round(u_ms, 1),
                        v_ms=round(v_ms, 1),
                        speed_ms=round(speed, 1),
                        direction_to_deg=round(direction, 1),
                    )
                )
                continue

            variable = self._VARIABLES[kind][0]
            value = variables[variable][index]
            if not _valid(value):
                continue
            if kind is WeatherLayerKind.RAINFALL:
                value = max(0.0, value)
            result.append(
                WeatherGridPoint(
                    grid_x=grid_x,
                    grid_y=grid_y,
                    location=GeoPoint(latitude, longitude),
                    value=round(value, 1),
                )
            )
        return tuple(result)

    @classmethod
    def _error(
        cls,
        kind: WeatherLayerKind,
        observed_at: dt.datetime,
        fetched_at: dt.datetime,
        message: str,
    ) -> WeatherLayerFeed:
        return WeatherLayerFeed(
            kind=kind,
            health=DataHealth.ERROR,
            observed_at=observed_at,
            fetched_at=fetched_at,
            unit=cls._UNITS[kind],
            points=(),
            message=message,
        )


def _floor_ten_minutes(value: dt.datetime) -> dt.datetime:
    return value.replace(
        minute=(value.minute // 10) * 10,
        second=0,
        microsecond=0,
    )


def _valid(value: float) -> bool:
    return math.isfinite(value) and value > -90
