"""도메인 snapshot을 Folium 지도로 표현합니다."""

from __future__ import annotations

import html
from collections import defaultdict
from typing import Any

import folium
from folium.plugins import MarkerCluster

from safety_dashboard.domain.enums import RiskGrade, WarningLevel
from safety_dashboard.domain.models import DashboardSnapshot


COLORS = {
    RiskGrade.HIGH: "#D92D20",
    RiskGrade.MEDIUM: "#E87817",
    RiskGrade.LOW: "#B58900",
    RiskGrade.UNASSESSED: "#667085",
    RiskGrade.NONE: "#247BA0",
}


def build_monitoring_map(
    snapshot: DashboardSnapshot,
    boundary_data: dict[str, Any] | None,
) -> folium.Map:
    map_obj = folium.Map(location=[36.0, 128.5], zoom_start=7, tiles=None, control_scale=True)
    folium.TileLayer(
        "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
        attr="&copy; OpenStreetMap &copy; CARTO",
        name="기본 지도",
    ).add_to(map_obj)
    _add_warning_zones(map_obj, snapshot, boundary_data)

    cluster = MarkerCluster(
        name="소관 시설",
        options={"showCoverageOnHover": False, "maxClusterRadius": 38},
    ).add_to(map_obj)
    assessments = {item.facility.id: item for item in snapshot.assessments}
    for facility in snapshot.facilities:
        assessment = assessments[facility.id]
        reasons = ", ".join(
            dict.fromkeys(f"{item.warning_type} {item.raw_level}" for item in assessment.reasons)
        ) or "현재 영향 특보 없음"
        popup = (
            '<div style="font-family:sans-serif;min-width:220px;line-height:1.5">'
            f"<b>{html.escape(facility.name)}</b> · {_grade_label(assessment.grade)}<br>"
            f"{html.escape(facility.facility_type)}<hr style='margin:6px 0'>"
            f"{html.escape(reasons)}<br><small>{html.escape(facility.address)}</small></div>"
        )
        folium.CircleMarker(
            [facility.location.latitude, facility.location.longitude],
            radius=7 if assessment.grade is not RiskGrade.NONE else 4,
            color="#ffffff",
            weight=1.5,
            fill=True,
            fill_color=COLORS[assessment.grade],
            fill_opacity=0.95,
            tooltip=f"{facility.name} · {_grade_label(assessment.grade)}",
            popup=folium.Popup(popup, max_width=320),
        ).add_to(cluster)
    folium.LayerControl(collapsed=True).add_to(map_obj)
    return map_obj


def _add_warning_zones(
    map_obj: folium.Map,
    snapshot: DashboardSnapshot,
    boundary_data: dict[str, Any] | None,
) -> None:
    if not boundary_data:
        return
    features = {
        str(feature.get("properties", {}).get("regid", "")): feature
        for feature in boundary_data.get("features", [])
    }
    grouped: dict[str, list] = defaultdict(list)
    for warning in snapshot.warning_feed.warnings:
        if warning.region_code in features:
            grouped[warning.region_code].append(warning)
    for code, warnings in grouped.items():
        primary = max(warnings, key=lambda item: _level_rank(item.level))
        color = {
            WarningLevel.CRITICAL: "#8F1010",
            WarningLevel.WARNING: "#D92D20",
            WarningLevel.ADVISORY: "#E87817",
            WarningLevel.UNKNOWN: "#667085",
        }[primary.level]
        label = " / ".join(
            dict.fromkeys(f"{item.warning_type} {item.raw_level}" for item in warnings)
        )
        folium.GeoJson(
            {"type": "FeatureCollection", "features": [features[code]]},
            style_function=lambda _, c=color: {
                "fillColor": c, "color": c, "weight": 1.2, "fillOpacity": 0.28,
            },
            tooltip=html.escape(f"{primary.region} · {label}"),
        ).add_to(map_obj)


def _level_rank(level: WarningLevel) -> int:
    return {
        WarningLevel.UNKNOWN: 0, WarningLevel.ADVISORY: 1,
        WarningLevel.WARNING: 2, WarningLevel.CRITICAL: 3,
    }[level]


def _grade_label(grade: RiskGrade) -> str:
    return {
        RiskGrade.HIGH: "상", RiskGrade.MEDIUM: "중", RiskGrade.LOW: "하",
        RiskGrade.UNASSESSED: "미판정", RiskGrade.NONE: "없음",
    }[grade]
