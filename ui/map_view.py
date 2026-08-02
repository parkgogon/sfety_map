"""Folium 기반 통합 관제 지도 생성."""

from __future__ import annotations

import html
import datetime as dt
from collections import defaultdict
from typing import Any

import folium
import pandas as pd
from folium.plugins import MarkerCluster

from core.region_resolver import (
    dominant_warning,
    warning_level_rank,
)
from risk_engine import WARNING_TYPE_WEIGHTS


CENTER = [36.0, 128.5]

FACILITY_ICONS = {
    "대기측정소": ("cloud", "#607d8b"),
    "수질측정소": ("tint", "#087fb6"),
    "공공하수처리시설": ("tint", "#07847c"),
    "시험실": ("flask", "#7b4cad"),
    "청사": ("building", "#43546a"),
    "홍보관": ("bullhorn", "#d97706"),
    "영농폐비닐 재활용시설": ("recycle", "#388e3c"),
    "재활용품 비축기지": ("cubes", "#795548"),
    "영농폐기물 수거사업소": ("truck", "#6d4c41"),
    "미래폐자원 거점수거센터": ("dot-circle-o", "#00695c"),
    "압수폐기물 보관창고": ("archive", "#795548"),
    "기타": ("map-marker", "#687386"),
}


def _warning_style(level: object) -> tuple[str, float]:
    rank = warning_level_rank(level)
    if rank >= 4:
        return "#9d1414", 0.62
    if rank == 3:
        return "#dc3a2d", 0.48
    if rank == 2:
        return "#f0a12b", 0.32
    return "#e2b84f", 0.24


def _format_warning_time(value: object) -> str:
    if value is None or bool(pd.isna(value)):
        return "-"
    if isinstance(value, (dt.datetime, pd.Timestamp)):
        return value.strftime("%m-%d %H:%M")
    text = str(value).strip()
    return text or "-"


def _boundary_region_code(feature: dict[str, Any]) -> str:
    properties = feature.get("properties", {})
    return str(
        properties.get("regid")
        or properties.get("regId")
        or properties.get("id")
        or ""
    ).strip()


def build_map(
    facilities: pd.DataFrame,
    warnings: pd.DataFrame,
    boundary_data: dict[str, Any] | None,
) -> folium.Map:
    """시설 마커와 우선순위가 반영된 특보 폴리곤을 생성합니다."""

    map_obj = folium.Map(
        location=CENTER,
        zoom_start=7,
        tiles=None,
        control_scale=True,
    )
    folium.TileLayer(
        tiles=(
            "https://{s}.basemaps.cartocdn.com/"
            "rastertiles/voyager/{z}/{x}/{y}{r}.png"
        ),
        attr=(
            '&copy; <a href="https://www.openstreetmap.org/copyright">'
            "OpenStreetMap</a> &copy; CARTO"
        ),
        name="기본 지도",
    ).add_to(map_obj)

    if boundary_data:
        features_by_code = {
            _boundary_region_code(feature): feature
            for feature in boundary_data.get("features", [])
            if _boundary_region_code(feature)
        }
        warnings_by_boundary: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in warnings.to_dict("records"):
            region_code = str(row.get("region_code", "")).strip()
            if region_code in features_by_code:
                warnings_by_boundary[region_code].append(row)

        rendered_zones = []
        for region_code, candidates in warnings_by_boundary.items():
            if not candidates:
                continue
            primary = dominant_warning(candidates, WARNING_TYPE_WEIGHTS)
            rendered_zones.append(
                (
                    warning_level_rank(primary.get("level")),
                    region_code,
                    candidates,
                    primary,
                )
            )

        for _, region_code, candidates, primary in sorted(rendered_zones):
            feature = features_by_code[region_code]
            properties = feature.get("properties", {})
            name = str(
                properties.get("regko_fullname")
                or properties.get("regKo")
                or primary.get("region")
                or region_code
            )
            color, opacity = _warning_style(primary.get("level"))
            warning_labels = sorted(
                {
                    (
                        f"{item.get('type', '')} {item.get('level', '')}"
                        f" · 발표 {_format_warning_time(item.get('issued_at'))}"
                        f" · 발효 {_format_warning_time(item.get('effective_at'))}"
                    )
                    for item in candidates
                }
            )
            tooltip = html.escape(f"{name} · {' / '.join(warning_labels)}")
            folium.GeoJson(
                {"type": "FeatureCollection", "features": [feature]},
                style_function=lambda _, c=color, o=opacity: {
                    "fillColor": c,
                    "color": c,
                    "weight": 1.5,
                    "fillOpacity": o,
                },
                tooltip=tooltip,
            ).add_to(map_obj)

    cluster = MarkerCluster(
        name="소관시설",
        options={
            "showCoverageOnHover": False,
            "spiderfyOnMaxZoom": True,
            "maxClusterRadius": 42,
        },
    ).add_to(map_obj)

    for _, facility in facilities.iterrows():
        category = str(facility.get("시설구분", "기타"))
        icon_name, icon_color = FACILITY_ICONS.get(
            category,
            ("map-marker", "#687386"),
        )
        name = html.escape(str(facility.get("name", "")))
        address = html.escape(str(facility.get("address", "")))
        manager = html.escape(str(facility.get("부서 담당자", "-")))
        category_safe = html.escape(category)
        popup = f"""
        <div style="font-family:sans-serif;min-width:210px;line-height:1.5">
            <strong style="color:#15233d">{name}</strong><br>
            <span style="color:#687386">{category_safe}</span><hr style="margin:6px 0">
            담당 {manager}<br>
            <span style="font-size:11px;color:#687386">{address}</span>
        </div>
        """
        folium.Marker(
            location=[facility["latitude"], facility["longitude"]],
            tooltip=f"{name} · {category_safe}",
            popup=folium.Popup(popup, max_width=300),
            icon=folium.Icon(
                color="white",
                icon_color=icon_color,
                icon=icon_name,
                prefix="fa",
            ),
        ).add_to(cluster)

    legend = """
    <div style="position:fixed;bottom:24px;left:16px;z-index:9999;
        background:rgba(255,255,255,.94);border:1px solid #dce3ec;
        border-radius:8px;padding:7px 9px;font:11px sans-serif;color:#344054;">
        <b>특보 단계</b>&nbsp;
        <span style="color:#9d1414">● 중대경보</span>&nbsp;
        <span style="color:#dc3a2d">● 경보</span>&nbsp;
        <span style="color:#f0a12b">● 주의</span>
    </div>
    """
    map_obj.get_root().html.add_child(folium.Element(legend))
    return map_obj
