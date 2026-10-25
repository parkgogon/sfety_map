"""기상·지도 필터·전파 선택과 독립적인 기준점 주변 시설 조회."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Iterable

from safety_dashboard.domain.models import Facility, GeoPoint

EARTH_RADIUS_METERS = 6371008.8  # field_web/locationReference.ts와 동일
KST = dt.timezone(dt.timedelta(hours=9))


def distance_meters(a: GeoPoint, b: GeoPoint) -> float:
    lat = math.radians(b.latitude - a.latitude)
    lon = math.radians(b.longitude - a.longitude)
    h = math.sin(lat / 2) ** 2 + math.cos(math.radians(a.latitude)) * math.cos(
        math.radians(b.latitude)
    ) * math.sin(lon / 2) ** 2
    return EARTH_RADIUS_METERS * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def bearing_radians(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    lon = math.radians(b.longitude - a.longitude)
    return math.atan2(math.sin(lon) * math.cos(lat2),
                      math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon))


@dataclass(frozen=True)
class NearbyFacility:
    facility: Facility
    meters: float


@dataclass(frozen=True)
class NearbyReport:
    point: GeoPoint
    label: str
    address: str
    radius_km: float
    facilities: tuple[NearbyFacility, ...]
    total_count: int
    generated_at: dt.datetime

    @classmethod
    def build(cls, point: GeoPoint, label: str, address: str, radius_km: float,
              facilities: Iterable[Facility], *, generated_at: dt.datetime | None = None) -> NearbyReport:
        catalog = tuple(facilities)
        if not catalog:
            raise ValueError("시설 자료가 비어 있습니다.")
        for coordinate in (point, *(f.location for f in catalog)):
            if not (math.isfinite(coordinate.latitude) and math.isfinite(coordinate.longitude)
                    and -90 <= coordinate.latitude <= 90 and -180 <= coordinate.longitude <= 180):
                raise ValueError("유효한 시설·기준점 좌표가 필요합니다.")
        if not math.isfinite(radius_km) or not 0.1 <= radius_km <= 50:
            raise ValueError("반경은 0.1~50km여야 합니다.")
        if len({f.id for f in catalog}) != len(catalog):
            raise ValueError("시설 ID가 중복되었습니다.")
        nearby = (NearbyFacility(f, distance_meters(point, f.location)) for f in catalog)
        rows = tuple(sorted((r for r in nearby if r.meters <= radius_km * 1000),
                            key=lambda r: (r.meters, r.facility.id)))
        return cls(point, label, address, radius_km, rows, len(catalog),
                   generated_at or dt.datetime.now(KST))
