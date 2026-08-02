"""기상특보 구역과 시설 주소/지도 경계를 연결하는 규칙."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from shapely.geometry import Point, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid


_ADMIN_SUFFIX = re.compile(r"(특별자치도|특별자치시|광역시|특별시|도|시|군|구)$")
_AMBIGUOUS_DISTRICTS = {"중구", "남구", "북구", "동구", "서구"}
_DAEGU_BOUNDARIES = (
    "중구",
    "남구",
    "북구",
    "동구",
    "서구",
    "수성구",
    "달서구",
    "달성군",
)

KMA_WARNING_SCOPE_PREFIXES = ("L107", "L108", "L114", "L115", "L116")


def _feature_region_code(feature: Mapping[str, Any]) -> str:
    properties = feature.get("properties", {})
    return str(
        properties.get("regid")
        or properties.get("regId")
        or properties.get("id")
        or ""
    ).strip()


def _polygonal_geometry(geometry: BaseGeometry) -> BaseGeometry:
    """유효한 Polygon/MultiPolygon만 남겨 반환합니다."""

    repaired = geometry if geometry.is_valid else make_valid(geometry)
    if repaired.geom_type in {"Polygon", "MultiPolygon"}:
        return repaired
    if repaired.geom_type == "GeometryCollection":
        polygon_parts = [
            part
            for part in repaired.geoms
            if part.geom_type in {"Polygon", "MultiPolygon"}
        ]
        if polygon_parts:
            return unary_union(polygon_parts)
    raise ValueError(f"지원하지 않는 특보구역 도형입니다: {repaired.geom_type}")


def normalize_warning_zone_data(
    boundary_data: Mapping[str, Any],
    code_prefixes: Sequence[str] = KMA_WARNING_SCOPE_PREFIXES,
) -> dict[str, Any]:
    """기상청 GeoJSON을 검증하고 소관 육상 특보구역만 정규화합니다."""

    if boundary_data.get("type") != "FeatureCollection":
        raise ValueError("특보구역 데이터가 GeoJSON FeatureCollection이 아닙니다.")

    crs_name = str(
        boundary_data.get("crs", {}).get("properties", {}).get("name", "")
    )
    if crs_name and "CRS84" not in crs_name:
        raise ValueError(f"지원하지 않는 특보구역 좌표계입니다: {crs_name}")

    normalized_features: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    prefixes = tuple(str(prefix) for prefix in code_prefixes)

    for feature in boundary_data.get("features", []):
        region_code = _feature_region_code(feature)
        if not region_code.startswith(prefixes):
            continue
        if region_code in seen_codes:
            raise ValueError(f"중복된 특보구역 코드입니다: {region_code}")

        geometry_data = feature.get("geometry")
        if not geometry_data:
            raise ValueError(f"특보구역 도형이 없습니다: {region_code}")
        polygon = _polygonal_geometry(shape(geometry_data))

        properties = dict(feature.get("properties", {}))
        properties["regid"] = region_code
        properties.setdefault(
            "regko_fullname",
            properties.get("regKo") or properties.get("regko") or region_code,
        )
        normalized_features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": mapping(polygon),
            }
        )
        seen_codes.add(region_code)

    if not normalized_features:
        raise ValueError("소관 권역의 특보구역 도형을 찾지 못했습니다.")

    return {
        "type": "FeatureCollection",
        "name": str(boundary_data.get("name", "KMA warning areas")),
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "features": normalized_features,
    }


@dataclass(frozen=True)
class WarningZoneIndex:
    """특보구역 코드로 도형과 GeoJSON Feature를 조회하는 불변 인덱스."""

    features: Mapping[str, Mapping[str, Any]]
    geometries: Mapping[str, BaseGeometry]

    @classmethod
    def from_geojson(cls, boundary_data: Mapping[str, Any]) -> "WarningZoneIndex":
        features: dict[str, Mapping[str, Any]] = {}
        geometries: dict[str, BaseGeometry] = {}
        for feature in boundary_data.get("features", []):
            code = _feature_region_code(feature)
            if not code:
                continue
            if code in features:
                raise ValueError(f"중복된 특보구역 코드입니다: {code}")
            polygon = _polygonal_geometry(shape(feature.get("geometry")))
            features[code] = feature
            geometries[code] = polygon
        if not features:
            raise ValueError("특보구역 인덱스를 생성할 수 없습니다.")
        return cls(features=features, geometries=geometries)

    def has_region(self, region_code: object) -> bool:
        return str(region_code or "").strip() in self.geometries

    def covers(
        self,
        region_code: object,
        latitude: object,
        longitude: object,
    ) -> bool:
        code = str(region_code or "").strip()
        geometry = self.geometries.get(code)
        if geometry is None:
            return False
        try:
            point = Point(float(longitude), float(latitude))
        except (TypeError, ValueError):
            return False
        return bool(geometry.covers(point))

    def feature_for(self, region_code: object) -> Mapping[str, Any] | None:
        return self.features.get(str(region_code or "").strip())

    def distance(
        self,
        region_code: object,
        latitude: object,
        longitude: object,
    ) -> float | None:
        code = str(region_code or "").strip()
        geometry = self.geometries.get(code)
        if geometry is None:
            return None
        try:
            point = Point(float(longitude), float(latitude))
        except (TypeError, ValueError):
            return None
        return float(geometry.distance(point))


def _compact(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def _base_admin_name(value: object) -> str:
    return _ADMIN_SUFFIX.sub("", _compact(value))


def _parent_keywords(region_up: object) -> tuple[str, ...]:
    parent = _compact(region_up)
    if "대구" in parent:
        return ("대구",)
    if "경상북도" in parent or "경북" in parent:
        return ("경상북도", "경북")
    return (_base_admin_name(parent),) if parent else ()


def facility_matches_warning(
    address: object,
    region: object,
    region_up: object = "",
) -> bool:
    """시설 주소가 특보 구역에 포함되는지 보수적으로 판단합니다.

    KMA의 ``대구중부``처럼 행정구역명과 일치하지 않는 특보 구역은
    누락 방지를 위해 대구 소재 시설 전체에 적용합니다. 향후 KMA 특보구역
    코드가 확보되면 이 규칙을 코드 기반 매핑으로 교체할 수 있습니다.
    """

    address_text = _compact(address)
    region_text = _compact(region)
    if not address_text or not region_text:
        return False

    if region_text.startswith("대구") and region_text not in {
        "대구광역시",
        "대구시",
    }:
        return "대구" in address_text

    region_base = _base_admin_name(region_text)
    direct_match = region_text in address_text or (
        bool(region_base) and region_base in address_text
    )
    if not direct_match:
        return False

    if region_text in _AMBIGUOUS_DISTRICTS:
        parents = _parent_keywords(region_up)
        return not parents or any(keyword in address_text for keyword in parents)

    return True


def warning_matches_facility(
    facility: Mapping[str, object],
    warning: Mapping[str, object],
    zone_index: WarningZoneIndex | None = None,
) -> bool:
    """시설 좌표를 우선 사용하고, 제한된 해안 오차만 주소로 보정합니다."""

    region_code = warning.get("region_code", "")
    if zone_index is not None and zone_index.has_region(region_code):
        if zone_index.covers(
            region_code,
            facility.get("latitude"),
            facility.get("longitude"),
        ):
            return True
        # 부두·항만 시설 좌표가 해안선 밖에 수십~수백 m 찍힌 경우에만
        # 동일 행정구역 주소를 확인해 좁은 오차 범위 안에서 보정합니다.
        distance = zone_index.distance(
            region_code,
            facility.get("latitude"),
            facility.get("longitude"),
        )
        return bool(
            distance is not None
            and distance <= 0.0025
            and facility_matches_warning(
                facility.get("address", ""),
                warning.get("region", ""),
                warning.get("region_up", ""),
            )
        )
    return facility_matches_warning(
        facility.get("address", ""),
        warning.get("region", ""),
        warning.get("region_up", ""),
    )


def boundary_names_for_warning(
    region: object,
    available_names: Iterable[str],
) -> list[str]:
    """특보 구역에 해당하는 GeoJSON 경계 이름을 반환합니다."""

    region_text = _compact(region)
    available = set(available_names)

    if region_text in available:
        return [region_text]

    if region_text.startswith("대구"):
        return [name for name in _DAEGU_BOUNDARIES if name in available]

    region_base = _base_admin_name(region_text)
    return [
        name
        for name in available
        if _base_admin_name(name) == region_base
    ]


def warning_level_rank(level: object) -> int:
    """특보 단계 비교용 우선순위를 반환합니다."""

    text = _compact(level)
    if any(token in text for token in ("중대", "심각", "위급")):
        return 4
    if "경보" in text:
        return 3
    if "주의" in text:
        return 2
    return 1


def dominant_warning(
    warnings: Sequence[Mapping[str, object]],
    type_weights: Mapping[str, int],
) -> Mapping[str, object]:
    """동일 지역의 여러 특보 중 시각적으로 우선 표시할 특보를 선택합니다."""

    if not warnings:
        return {}
    return max(
        warnings,
        key=lambda item: (
            warning_level_rank(item.get("level")),
            type_weights.get(str(item.get("type", "")), 1),
        ),
    )
