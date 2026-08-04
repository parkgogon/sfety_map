"""도메인 snapshot을 Folium 지도로 표현합니다."""

from __future__ import annotations

import html
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import folium
from folium.plugins import MarkerCluster

from safety_dashboard.domain.enums import RiskGrade, WarningLevel
from safety_dashboard.domain.models import DashboardSnapshot, NearbyCctv


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
    focus_facility_id: str = "",
    nearby_cctvs: Sequence[NearbyCctv] = (),
    cctv_focus_facility_id: str = "",
) -> folium.Map:
    focus_facility = next(
        (
            item
            for item in snapshot.facilities
            if item.id == str(focus_facility_id)
        ),
        None,
    )
    location = (
        [focus_facility.location.latitude, focus_facility.location.longitude]
        if focus_facility
        else [36.0, 128.5]
    )
    map_obj = folium.Map(
        location=location,
        zoom_start=13 if focus_facility else 7,
        tiles=None,
        control_scale=True,
    )
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
    cctv_focus = next(
        (
            item
            for item in snapshot.facilities
            if item.id == str(cctv_focus_facility_id)
        ),
        None,
    )
    if nearby_cctvs:
        _add_cctv_markers(map_obj, nearby_cctvs)
        if cctv_focus:
            folium.CircleMarker(
                [cctv_focus.location.latitude, cctv_focus.location.longitude],
                radius=11,
                color="#142746",
                weight=3,
                fill=False,
                tooltip=f"CCTV 기준 시설 · {html.escape(cctv_focus.name)}",
            ).add_to(map_obj)
            map_obj.fit_bounds(
                [
                    [cctv_focus.location.latitude, cctv_focus.location.longitude],
                    *[
                        [item.location.latitude, item.location.longitude]
                        for item in nearby_cctvs
                    ],
                ],
                padding=(28, 28),
                max_zoom=12,
            )
    if focus_facility:
        folium.CircleMarker(
            [focus_facility.location.latitude, focus_facility.location.longitude],
            radius=13,
            color="#142746",
            weight=4,
            fill=False,
            tooltip=f"선택 시설 · {focus_facility.name}",
        ).add_to(map_obj)
    folium.LayerControl(collapsed=True).add_to(map_obj)
    return map_obj


def _add_cctv_markers(
    map_obj: folium.Map,
    cctvs: Sequence[NearbyCctv],
) -> None:
    layer = folium.FeatureGroup(name="인근 교통 CCTV", show=True).add_to(map_obj)
    for cctv in cctvs:
        popup = (
            '<div style="font-family:sans-serif;min-width:210px;line-height:1.5">'
            f"<b>{html.escape(cctv.name)}</b><br>"
            f"{html.escape(cctv.road_type)} · 시설에서 {cctv.distance_km:.1f}km<br>"
            "<small>마커를 누르면 큰 영상 작업창이 열립니다.</small></div>"
        )
        folium.Marker(
            [cctv.location.latitude, cctv.location.longitude],
            tooltip=(
                f"CCTV · {html.escape(cctv.name)} · {cctv.distance_km:.1f}km"
            ),
            popup=folium.Popup(popup, max_width=300),
            icon=folium.Icon(
                color="cadetblue",
                icon="video-camera",
                prefix="fa",
            ),
        ).add_to(layer)


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
