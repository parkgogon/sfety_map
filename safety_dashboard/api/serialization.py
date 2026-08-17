"""도메인 snapshot을 개인정보가 제거된 공개 API 응답으로 변환한다."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any, Mapping
from urllib.parse import urlsplit

from safety_dashboard.adapters.cctv import OFFICIAL_MAP_URL, SOURCE_PAGE_URL
from safety_dashboard.adapters.kma import KMA_PUBLIC_DELAY_MESSAGE
from safety_dashboard.application.contacts import public_contact
from safety_dashboard.application.cctv_directions import direction_label
from safety_dashboard.application.facility_groups import FacilityGroupCatalog
from safety_dashboard.domain.enums import DataHealth, RiskGrade, WarningLevel
from safety_dashboard.domain.models import (
    CctvFeed,
    DashboardSnapshot,
    Warning,
    WeatherLayerFeed,
    WeatherObservation,
)
from safety_dashboard.domain.risk_policy import RiskPolicy


KST = dt.timezone(dt.timedelta(hours=9))
UNAVAILABLE_GRADE = "UNAVAILABLE"


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=KST)
    return value.isoformat()


def serialize_weather(
    facility_id: str,
    observation: WeatherObservation,
) -> dict[str, Any]:
    """시설 위치 격자의 실제 KMA 초단기실황을 공개 응답으로 변환합니다."""

    return {
        "api_version": "v1",
        "facility_id": facility_id,
        "status": observation.health.value,
        "observed_at": _iso(observation.observed_at),
        "temperature_c": observation.temperature_c,
        "rainfall_1h_mm": observation.rainfall_1h_mm,
        "wind_speed_ms": observation.wind_speed_ms,
        "wind_direction_deg": observation.wind_direction_deg,
        "detail": observation.message,
        "source": "기상청 초단기실황",
        "actual_data": True,
    }


def serialize_weather_layer(feed: WeatherLayerFeed) -> dict[str, Any]:
    """관제 권역 실황 격자를 React 지도용 응답으로 변환합니다."""

    points = []
    for item in feed.points:
        base = {
            "grid_x": item.grid_x,
            "grid_y": item.grid_y,
            "latitude": round(item.location.latitude, 6),
            "longitude": round(item.location.longitude, 6),
        }
        if feed.kind.value == "wind":
            base.update(
                {
                    "u_ms": item.u_ms,
                    "v_ms": item.v_ms,
                    "speed_ms": item.speed_ms,
                    "direction_to_deg": item.direction_to_deg,
                }
            )
        else:
            base["value"] = item.value
        points.append(base)
    return {
        "api_version": "v1",
        "layer": feed.kind.value,
        "status": feed.health.value,
        "observed_at": _iso(feed.observed_at),
        "fetched_at": _iso(feed.fetched_at),
        "unit": feed.unit,
        "points": points,
        "detail": feed.message,
        "source": "기상청 동네예보 격자 실황",
        "scope": "대구·경북·부산·울산·경남",
        "actual_data": True,
    }


def serialize_cctv(
    facility_id: str,
    feed: CctvFeed,
    *,
    direction_warning: str = "",
) -> dict[str, Any]:
    """ITS 영상 주소와 검증된 방향 정보만 React에 전달합니다."""

    cctvs = []
    for item in feed.cctvs:
        scheme = urlsplit(item.video_url).scheme.lower()
        cctvs.append(
            {
                "id": item.id,
                "name": item.name,
                "latitude": item.location.latitude,
                "longitude": item.location.longitude,
                "distance_km": round(item.distance_km, 3),
                "road_type": item.road_type,
                "video_url": item.video_url,
                "video_format": item.video_format,
                "embed_allowed": (
                    scheme == "https" and "MP4" in item.video_format.upper()
                ),
                "updated_at": _iso(item.updated_at),
                "bearing_deg": item.bearing_deg,
                "direction_label": (
                    direction_label(item.bearing_deg)
                    if item.bearing_deg is not None
                    else ""
                ),
                "direction_verified_on": (
                    item.direction_verified_on.isoformat()
                    if item.direction_verified_on is not None
                    else None
                ),
                "direction_source": item.direction_source,
            }
        )
    return {
        "api_version": "v1",
        "facility_id": facility_id,
        "status": feed.status.value,
        "fetched_at": _iso(feed.fetched_at),
        "detail": feed.detail,
        "direction_warning": direction_warning,
        "radius_km": 20,
        "limit": 5,
        "cctvs": cctvs,
        "source": "ITS 국가교통정보센터 도로 CCTV",
        "source_url": SOURCE_PAGE_URL,
        "official_map_url": OFFICIAL_MAP_URL,
        "actual_data": True,
    }


def _level_rank(level: WarningLevel) -> int:
    return {
        WarningLevel.UNKNOWN: 0,
        WarningLevel.ADVISORY: 1,
        WarningLevel.WARNING: 2,
        WarningLevel.CRITICAL: 3,
    }[level]


def _warning_color(level: WarningLevel) -> str:
    return {
        WarningLevel.CRITICAL: "#8F1010",
        WarningLevel.WARNING: "#D92D20",
        WarningLevel.ADVISORY: "#E87817",
        WarningLevel.UNKNOWN: "#667085",
    }[level]


def _warning_payload(warning: Warning) -> dict[str, Any]:
    return {
        "id": warning.id,
        "source": warning.source,
        "region_code": warning.region_code,
        "region": warning.region,
        "region_up": warning.region_up,
        "type": warning.warning_type,
        "raw_level": warning.raw_level,
        "level": warning.level.value,
        "command": warning.command,
        "issued_at": _iso(warning.issued_at),
        "effective_at": _iso(warning.effective_at),
    }


def _warning_zones(
    snapshot: DashboardSnapshot,
    zone_data: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not zone_data:
        return {"type": "FeatureCollection", "features": []}
    features = {
        str(item.get("properties", {}).get("regid", "")): item
        for item in zone_data.get("features", [])
    }
    grouped: dict[str, list[Warning]] = defaultdict(list)
    for warning in snapshot.warning_feed.warnings:
        if warning.region_code in features:
            grouped[warning.region_code].append(warning)

    result = []
    for code, warnings in grouped.items():
        primary = max(warnings, key=lambda item: _level_rank(item.level))
        source_feature = features[code]
        result.append(
            {
                "type": "Feature",
                "properties": {
                    "region_code": code,
                    "region": primary.region,
                    "label": " / ".join(
                        dict.fromkeys(
                            f"{item.warning_type} {item.raw_level}"
                            for item in warnings
                        )
                    ),
                    "level": primary.level.value,
                    "color": _warning_color(primary.level),
                },
                "geometry": source_feature.get("geometry"),
            }
        )
    return {"type": "FeatureCollection", "features": result}


def serialize_monitoring(
    snapshot: DashboardSnapshot,
    catalog: FacilityGroupCatalog,
    policy: RiskPolicy,
    zone_data: Mapping[str, Any] | None,
    zone_health: DataHealth,
    zone_detail: str,
) -> dict[str, Any]:
    """React가 추가 계산 없이 렌더링할 수 있는 하나의 관제 응답을 만든다."""

    feed_unavailable = snapshot.warning_feed.health is DataHealth.ERROR
    assessment_by_id = {
        assessment.facility.id: assessment for assessment in snapshot.assessments
    }
    facilities = []
    for facility in snapshot.facilities:
        assessment = assessment_by_id[facility.id]
        group = catalog.group_for_type(facility.facility_type)
        if feed_unavailable:
            grade = UNAVAILABLE_GRADE
            grade_label = "조회 불가"
            color = "#667085"
            meaning = "기상청 데이터 미수신으로 위험등급 판정불가"
            action = "새로고침 후 KMA 상태를 다시 확인"
        else:
            definition = policy.definition(assessment.grade)
            grade = assessment.grade.value
            grade_label = definition.label if assessment.grade is not RiskGrade.NONE else "영향 없음"
            color = definition.color
            meaning = definition.meaning
            action = definition.action

        reasons = [
            {
                "warning_id": reason.warning_id,
                "type": reason.warning_type,
                "raw_level": reason.raw_level,
                "grade": reason.grade.value,
                "region": reason.region,
            }
            for reason in assessment.reasons
        ]
        facilities.append(
            {
                "id": facility.id,
                "name": facility.name,
                "type": facility.facility_type,
                "group_id": group.id,
                "group_label": group.label,
                "latitude": facility.location.latitude,
                "longitude": facility.location.longitude,
                "address": facility.address,
                "public_contact": public_contact(facility),
                "grade": grade,
                "grade_label": grade_label,
                "grade_color": color,
                "meaning": meaning,
                "recommended_action": action,
                "reasons": reasons,
            }
        )

    group_counts = catalog.counts(snapshot.facilities)
    summary = None if feed_unavailable else {
        "active_warning_count": snapshot.summary.active_warning_count,
        "affected_facility_count": snapshot.summary.affected_facility_count,
        "high_risk_count": snapshot.summary.high_risk_count,
        "unassessed_count": snapshot.summary.unassessed_count,
        "highest_warning_level": snapshot.summary.highest_warning_level.value,
    }
    return {
        "api_version": "v1",
        "generated_at": _iso(snapshot.generated_at),
        "status": {
            "health": snapshot.warning_feed.health.value,
            "fetched_at": _iso(snapshot.warning_feed.fetched_at),
            "detail": (
                KMA_PUBLIC_DELAY_MESSAGE
                if feed_unavailable
                else snapshot.warning_feed.message
            ),
            "zone_health": zone_health.value,
            "zone_detail": zone_detail,
        },
        "policy": {
            "version": snapshot.policy_version,
            "temporary": False,
        },
        "summary": summary,
        "groups": [
            {
                "id": group.id,
                "label": group.label,
                "count": group_counts[group.id],
            }
            for group in catalog.groups
        ],
        "warnings": [
            _warning_payload(warning) for warning in snapshot.warning_feed.warnings
        ],
        "warning_zones": _warning_zones(snapshot, zone_data),
        "facilities": facilities,
        "notices": list(snapshot.notices),
    }
