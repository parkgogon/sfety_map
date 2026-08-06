"""도메인 snapshot을 Folium 지도로 표현합니다."""

from __future__ import annotations

import html
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import folium
from branca.element import MacroElement, Template
from folium.plugins import MarkerCluster

from safety_dashboard.application.cctv_directions import (
    describe_cctv_direction,
)
from safety_dashboard.domain.enums import RiskGrade, WarningLevel
from safety_dashboard.domain.models import DashboardSnapshot, NearbyCctv


COLORS = {
    RiskGrade.HIGH: "#D92D20",
    RiskGrade.MEDIUM: "#E87817",
    RiskGrade.LOW: "#B58900",
    RiskGrade.UNASSESSED: "#667085",
    RiskGrade.NONE: "#247BA0",
}


class _MobileMapInteractionControl(MacroElement):
    """모바일에서 페이지 스크롤을 우선하는 Leaflet 제어입니다."""

    _template = Template(
        """
        {% macro header(this, kwargs) %}
        <style>
          .mobile-map-interaction-control {
            background: #ffffff;
            border: 1px solid rgba(20, 39, 70, .28);
            border-radius: 7px;
            box-shadow: 0 1px 5px rgba(20, 39, 70, .22);
          }
          .mobile-map-interaction-control button {
            align-items: center;
            background: #ffffff;
            border: 0;
            border-radius: 7px;
            color: #142746;
            cursor: pointer;
            display: flex;
            font: 700 13px/1.2 sans-serif;
            gap: 5px;
            min-height: 42px;
            padding: 8px 10px;
            white-space: nowrap;
          }
          .mobile-map-interaction-control button[data-locked="false"] {
            background: #142746;
            color: #ffffff;
          }
        </style>
        {% endmacro %}
        {% macro script(this, kwargs) %}
        (function () {
          const map = {{ this._parent.get_name() }};
          let viewportWidth = window.innerWidth;
          try {
            if (window.top && window.top !== window) {
              viewportWidth = window.top.innerWidth;
            }
          } catch (error) {
            // 다른 origin으로 호스팅되는 경우 iframe 폭을 안전하게 사용한다.
          }
          const isMobile = viewportWidth <= 700;
          if (!isMobile) return;

          const container = map.getContainer();
          const handlers = [
            map.dragging,
            map.touchZoom,
            map.doubleClickZoom,
            map.boxZoom,
            map.keyboard,
            map.scrollWheelZoom
          ].filter(Boolean).map((handler) => ({
            handler: handler,
            initiallyEnabled: handler.enabled()
          }));
          let locked = true;
          let button;

          function setLocked(nextLocked) {
            locked = nextLocked;
            handlers.forEach(({handler, initiallyEnabled}) => {
              if (locked) handler.disable();
              else if (initiallyEnabled) handler.enable();
            });
            container.style.touchAction = locked ? 'pan-y' : 'none';
            container.dataset.mobileInteraction = locked ? 'locked' : 'active';
            if (button) {
              button.dataset.locked = String(locked);
              button.setAttribute('aria-pressed', String(!locked));
              button.setAttribute(
                'aria-label',
                locked ? '지도 조작 켜기' : '페이지 스크롤 우선'
              );
              button.innerHTML = locked
                ? '<span aria-hidden="true">🔒</span><span>지도 조작 켜기</span>'
                : '<span aria-hidden="true">🔓</span><span>페이지 스크롤 우선</span>';
            }
          }

          const MobileControl = L.Control.extend({
            options: {position: 'topright'},
            onAdd: function () {
              const wrapper = L.DomUtil.create(
                'div',
                'mobile-map-interaction-control leaflet-control'
              );
              button = L.DomUtil.create('button', '', wrapper);
              button.type = 'button';
              L.DomEvent.disableClickPropagation(wrapper);
              L.DomEvent.disableScrollPropagation(wrapper);
              L.DomEvent.on(button, 'click', function (event) {
                L.DomEvent.stop(event);
                setLocked(!locked);
              });
              return wrapper;
            }
          });

          map.addControl(new MobileControl());
          setLocked(true);
        })();
        {% endmacro %}
        """
    )

    def __init__(self) -> None:
        super().__init__()
        self._name = "MobileMapInteractionControl"


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
    _MobileMapInteractionControl().add_to(map_obj)
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
    return map_obj


def _add_cctv_markers(
    map_obj: folium.Map,
    cctvs: Sequence[NearbyCctv],
) -> None:
    layer = folium.FeatureGroup(name="인근 교통 CCTV", show=True).add_to(map_obj)
    for cctv in cctvs:
        direction_text = describe_cctv_direction(cctv)
        folium.Marker(
            [cctv.location.latitude, cctv.location.longitude],
            tooltip=(
                f"CCTV · {html.escape(cctv.name)} · "
                f"{cctv.distance_km:.1f}km · {html.escape(direction_text)}"
            ),
            icon=(
                _verified_cctv_icon(cctv.bearing_deg)
                if cctv.bearing_deg is not None
                else folium.Icon(
                    color="cadetblue",
                    icon="video-camera",
                    prefix="fa",
                )
            ),
        ).add_to(layer)


def _verified_cctv_icon(bearing_deg: float) -> folium.DivIcon:
    """검증된 고정 방향만 카메라 배지와 화살표로 표시합니다."""

    bearing = f"{bearing_deg:.1f}"
    marker_html = (
        f'<div class="cctv-direction-marker" data-bearing="{bearing}" '
        'style="position:relative;width:42px;height:42px;">'
        '<div class="cctv-direction-arrow" '
        'style="position:absolute;left:19px;top:1px;width:4px;height:20px;'
        'background:#0e7490;border-radius:3px;transform-origin:2px 20px;'
        f'transform:rotate({bearing}deg);box-shadow:0 1px 2px rgba(0,0,0,.3);">'
        '<span style="position:absolute;left:-4px;top:-5px;width:0;height:0;'
        'border-left:6px solid transparent;border-right:6px solid transparent;'
        'border-bottom:9px solid #0e7490;"></span></div>'
        '<div style="position:absolute;left:7px;top:13px;width:28px;height:28px;'
        'display:flex;align-items:center;justify-content:center;border-radius:50%;'
        'background:#0e7490;color:#fff;border:2px solid #fff;'
        'box-shadow:0 1px 4px rgba(0,0,0,.4);">'
        '<i class="fa fa-video-camera" aria-hidden="true"></i></div></div>'
    )
    return folium.DivIcon(
        html=marker_html,
        icon_size=(42, 42),
        icon_anchor=(21, 21),
    )


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
