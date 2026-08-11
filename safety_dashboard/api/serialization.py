"""도메인 snapshot을 개인정보가 제거된 공개 API 응답으로 변환한다."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any, Mapping

from safety_dashboard.application.contacts import public_contact
from safety_dashboard.application.facility_groups import FacilityGroupCatalog
from safety_dashboard.domain.enums import DataHealth, RiskGrade, WarningLevel
from safety_dashboard.domain.models import DashboardSnapshot, Warning
from safety_dashboard.domain.risk_policy import RiskPolicy


KST = dt.timezone(dt.timedelta(hours=9))
UNAVAILABLE_GRADE = "UNAVAILABLE"


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=KST)
    return value.isoformat()


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
            meaning = "KMA 자료를 확인하지 못해 현재 영향을 판정할 수 없음"
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
            "detail": snapshot.warning_feed.message,
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
