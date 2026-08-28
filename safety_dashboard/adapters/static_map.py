"""소관권역(영남권) 특보 발효 현황 및 소관시설 위험도 정적 지도 렌더러."""

from __future__ import annotations

import gzip
import io
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import MultiPolygon, Polygon, shape

from safety_dashboard.domain.enums import RiskGrade, WarningLevel
from safety_dashboard.domain.models import DashboardSnapshot

# 영남권 지리적 바운딩 박스 (경도, 위도)
MIN_LON, MAX_LON = 127.35, 129.85
MIN_LAT, MAX_LAT = 34.60, 37.25
MEAN_LAT = (MIN_LAT + MAX_LAT) / 2.0  # 약 35.925도

# 종횡비 보정 계수 (경도 1도당 거리 / 위도 1도당 거리 = cos(lat))
ASPECT_CORRECTION = math.cos(math.radians(MEAN_LAT))  # 약 0.81

# 기본 데이터 경로
DEFAULT_ZONE_PATH = Path(__file__).parents[2] / "data" / "kma_warning_zones.geojson.gz"

# 색상 상수 (RGBA)
BG_COLOR = (248, 250, 252, 255)          # #F8FAFC
ZONE_BG_COLOR = (241, 245, 249, 255)     # #F1F5F9 (영남권 시군구 기본 배경)
ZONE_BORDER_COLOR = (203, 213, 225, 255) # #CBD5E1 (시군구 경계선)

WARNING_FILL = {
    WarningLevel.CRITICAL: (217, 45, 32, 100),  # 경보/중대 (연한 빨강 반투명)
    WarningLevel.WARNING: (217, 45, 32, 85),    # 경보
    WarningLevel.ADVISORY: (217, 119, 6, 75),   # 주의보 (연한 주황 반투명)
}
WARNING_STROKE = {
    WarningLevel.CRITICAL: (185, 28, 28, 255),
    WarningLevel.WARNING: (217, 45, 32, 255),
    WarningLevel.ADVISORY: (217, 119, 6, 255),
}

MARKER_COLOR = {
    RiskGrade.HIGH: (217, 45, 32, 255),        # #D92D20
    RiskGrade.MEDIUM: (194, 65, 12, 255),      # #C2410C
    RiskGrade.LOW: (138, 109, 0, 255),         # #8A6D00
    RiskGrade.UNASSESSED: (124, 58, 237, 255), # #7C3AED
    RiskGrade.NONE: (100, 116, 139, 255),      # #64748B
}


class StaticSafetyMapRenderer:
    """영남권 103개 시설 및 특보 구역을 렌더링하는 정적 지도 생성기."""

    def __init__(self, zone_geojson_path: Path | str | None = None) -> None:
        self.zone_path = Path(zone_geojson_path) if zone_geojson_path else DEFAULT_ZONE_PATH
        self._zone_features: list[dict[str, Any]] = []
        self._load_zones()

    def _load_zones() -> None:
        pass

    def _load_zones(self) -> None:
        if not self.zone_path.exists():
            return
        try:
            if self.zone_path.suffix == ".gz":
                with gzip.open(self.zone_path, "rt", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                with open(self.zone_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

            prefixes = ("L107", "L108", "L114", "L115", "L116")
            for feature in data.get("features", []):
                props = feature.get("properties", {})
                reg_id = str(props.get("regId") or props.get("id") or props.get("regid") or "")
                if any(reg_id.startswith(p) for p in prefixes):
                    self._zone_features.append(feature)
        except Exception:
            self._zone_features = []

    @staticmethod
    def _project(lon: float, lat: float, width: int, height: int, pad: int = 18) -> tuple[int, int]:
        """위경도 종횡비(Equirectangular projection)를 보정하여 픽셀 좌표로 변환."""
        w_avail = width - 2 * pad
        h_avail = height - 2 * pad

        # 실제 물리적 거리 비율 계산
        geo_w = (MAX_LON - MIN_LON) * ASPECT_CORRECTION
        geo_h = (MAX_LAT - MIN_LAT)

        # 캔버스 중앙에 꽉 차게 스케일링
        scale = min(w_avail / geo_w, h_avail / geo_h)
        offset_x = pad + (w_avail - geo_w * scale) / 2.0
        offset_y = pad + (h_avail - geo_h * scale) / 2.0

        x = offset_x + (lon - MIN_LON) * ASPECT_CORRECTION * scale
        y = offset_y + (MAX_LAT - lat) * scale
        return int(round(x)), int(round(y))

    def render_png(
        self,
        snapshot: DashboardSnapshot,
        width: int = 600,
        height: int = 540,
    ) -> bytes:
        """DashboardSnapshot을 바탕으로 영남권 안전지도 PNG 이미지를 생성합니다."""
        img = Image.new("RGBA", (width, height), BG_COLOR)
        draw = ImageDraw.Draw(img, "RGBA")

        # 1. 특보 구역 매핑
        active_warning_zones: dict[str, WarningLevel] = {}
        for warning in snapshot.warning_feed.warnings:
            code = warning.region_code
            if code:
                active_warning_zones[code] = warning.level
            name = warning.region
            if name:
                active_warning_zones[name] = warning.level

        # 2. 영남권 시·군·구 폴리곤 렌더링
        for feature in self._zone_features:
            props = feature.get("properties", {})
            reg_id = str(props.get("regId") or props.get("id") or props.get("regid") or "")
            reg_name = str(props.get("name") or props.get("regName") or "")
            geom = shape(feature.get("geometry", {}))

            warning_level = (
                active_warning_zones.get(reg_id)
                or active_warning_zones.get(reg_name)
            )

            fill_col = WARNING_FILL.get(warning_level, ZONE_BG_COLOR)
            stroke_col = WARNING_STROKE.get(warning_level, ZONE_BORDER_COLOR)
            stroke_w = 2 if warning_level in (WarningLevel.WARNING, WarningLevel.CRITICAL) else 1

            polygons = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
            for poly in polygons:
                if not isinstance(poly, Polygon) or poly.is_empty:
                    continue
                pts = [
                    self._project(x, y, width, height)
                    for x, y in poly.exterior.coords
                ]
                if len(pts) >= 3:
                    draw.polygon(pts, fill=fill_col, outline=stroke_col, width=stroke_w)

        # 3. 소관시설 마커 렌더링
        ranking = {
            RiskGrade.NONE: 0,
            RiskGrade.UNASSESSED: 1,
            RiskGrade.LOW: 2,
            RiskGrade.MEDIUM: 3,
            RiskGrade.HIGH: 4,
        }
        sorted_assessments = sorted(
            snapshot.assessments,
            key=lambda a: (ranking.get(a.grade, 0), a.facility.name),
        )

        for assessment in sorted_assessments:
            coord = assessment.facility.location
            if not coord:
                continue
            cx, cy = self._project(coord.longitude, coord.latitude, width, height)
            grade = assessment.grade
            col = MARKER_COLOR.get(grade, MARKER_COLOR[RiskGrade.NONE])

            if grade is RiskGrade.HIGH:
                r = 8
                draw.ellipse((cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2), fill=(217, 45, 32, 80))
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col, outline=(255, 255, 255, 255), width=2)
            elif grade is RiskGrade.MEDIUM:
                r = 6.5
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col, outline=(255, 255, 255, 255), width=2)
            elif grade is RiskGrade.LOW:
                r = 5
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col, outline=(255, 255, 255, 255), width=1)
            else:
                r = 3.5
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col, outline=(255, 255, 255, 255), width=1)

        # 4. 지도 외곽 보더
        draw.rectangle((0, 0, width - 1, height - 1), outline=(203, 213, 225, 255), width=1)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
