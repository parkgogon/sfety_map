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
ZONE_BG_COLOR = (243, 246, 249, 255)     # #F3F6F9 (영남권 시군구 기본 배경)
ZONE_BORDER_COLOR = (203, 213, 225, 255) # #CBD5E1 (시군구 경계선)

WARNING_FILL = {
    WarningLevel.CRITICAL: (217, 45, 32, 110),  # 경보/중대 (연한 빨강 반투명)
    WarningLevel.WARNING: (217, 45, 32, 95),    # 경보
    WarningLevel.ADVISORY: (217, 119, 6, 85),   # 주의보 (연한 주황 반투명)
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

# 영남권 주요 거점 지명 좌표 (위도, 경도)
MAJOR_CITIES = [
    ("대구", 35.87, 128.60),
    ("부산", 35.18, 129.07),
    ("울산", 35.54, 129.31),
    ("포항", 36.02, 129.36),
    ("안동", 36.56, 128.73),
    ("구미", 36.12, 128.34),
    ("경주", 35.85, 129.22),
    ("창원", 35.23, 128.68),
    ("진주", 35.18, 128.08),
    ("통영", 34.85, 128.43),
    ("거제", 34.89, 128.62),
    ("김천", 36.14, 128.11),
    ("상주", 36.41, 128.16),
    ("영주", 36.80, 128.62),
    ("밀양", 35.50, 128.75),
    ("거창", 35.68, 127.91),
    ("울진", 36.99, 129.40),
]


class StaticSafetyMapRenderer:
    """영남권 103개 시설 및 특보 구역을 렌더링하는 대형 정적 지도 생성기."""

    def __init__(self, zone_geojson_path: Path | str | None = None, font_path: Path | str | None = None) -> None:
        self.zone_path = Path(zone_geojson_path) if zone_geojson_path else DEFAULT_ZONE_PATH
        self.font_path = Path(font_path) if font_path else Path(__file__).parents[2] / "fonts" / "NotoSansKR-Regular.ttf"
        self.bold_font_path = Path(__file__).parents[2] / "fonts" / "NotoSansKR-Bold.ttf"
        self._zone_features: list[dict[str, Any]] = []
        self._load_zones()

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
    def _project(lon: float, lat: float, width: int, height: int, pad: int = 14) -> tuple[int, int]:
        """위경도 종횡비(Equirectangular projection)를 보정하여 픽셀 좌표로 변환."""
        w_avail = width - 2 * pad
        h_avail = height - 2 * pad

        geo_w = (MAX_LON - MIN_LON) * ASPECT_CORRECTION
        geo_h = (MAX_LAT - MIN_LAT)

        scale = min(w_avail / geo_w, h_avail / geo_h)
        offset_x = pad + (w_avail - geo_w * scale) / 2.0
        offset_y = pad + (h_avail - geo_h * scale) / 2.0

        x = offset_x + (lon - MIN_LON) * ASPECT_CORRECTION * scale
        y = offset_y + (MAX_LAT - lat) * scale
        return int(round(x)), int(round(y))

    def _get_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        target_path = self.bold_font_path if bold and self.bold_font_path.exists() else self.font_path
        if target_path.exists():
            try:
                return ImageFont.truetype(str(target_path), size)
            except Exception:
                pass
        return ImageFont.load_default()

    def render_png(
        self,
        snapshot: DashboardSnapshot,
        width: int = 760,
        height: int = 550,
        top_facility_ranks: dict[str, int] | None = None,
    ) -> bytes:
        """DashboardSnapshot을 바탕으로 영남권 지명, 정갈한 특보 라벨, TOP4 번호 뱃지가 표기된 와이드 지도를 생성합니다."""
        img = Image.new("RGBA", (width, height), BG_COLOR)
        draw = ImageDraw.Draw(img, "RGBA")

        city_font = self._get_font(12, bold=False)
        warning_tag_font = self._get_font(12, bold=True)
        badge_font = self._get_font(13, bold=True)

        # 1. 특보 구역 매핑 & 발효 구역 수집 (복수 특보 집계)
        zone_warnings: dict[str, list[tuple[str, WarningLevel]]] = {}
        for warning in snapshot.warning_feed.warnings:
            level = warning.level
            w_type = warning.warning_type
            for key in (warning.region_code, warning.region):
                if key:
                    zone_warnings.setdefault(key, []).append((w_type, level))

        warning_centroids: list[tuple[int, int, str, WarningLevel, str]] = []

        # 2. 영남권 시·군·구 폴리곤 렌더링
        for feature in self._zone_features:
            props = feature.get("properties", {})
            reg_id = str(props.get("regId") or props.get("id") or props.get("regid") or "")
            reg_name = str(props.get("name") or props.get("regName") or "")
            geom = shape(feature.get("geometry", {}))

            warn_list = zone_warnings.get(reg_id) or zone_warnings.get(reg_name) or []

            warning_level = None
            warning_types_str = ""
            if warn_list:
                # 가장 높은 단계 기준 (경보 우선)
                levels = [l for _, l in warn_list]
                if any(l in (WarningLevel.WARNING, WarningLevel.CRITICAL) for l in levels):
                    warning_level = WarningLevel.WARNING
                else:
                    warning_level = WarningLevel.ADVISORY

                # 특보 종류 텍스트 조합 (최대 2종 + 외 N건)
                types = list(dict.fromkeys(t for t, _ in warn_list))
                if len(types) == 1:
                    warning_types_str = types[0]
                elif len(types) == 2:
                    warning_types_str = f"{types[0]}·{types[1]}"
                else:
                    warning_types_str = f"{types[0]}·{types[1]} 외 {len(types) - 2}건"

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

            # 특보 발효 구역 중심점 저장
            if warning_level and not geom.is_empty:
                centroid = geom.centroid
                cx, cy = self._project(centroid.x, centroid.y, width, height)
                clean_name = reg_name.replace("경상북도", "").replace("경상남도", "").strip()
                warning_centroids.append((cx, cy, clean_name, warning_level, warning_types_str))

        # 3. 주요 도시 지명 텍스트 라벨링 (배경 가이드)
        for name, lat, lon in MAJOR_CITIES:
            cx, cy = self._project(lon, lat, width, height)
            draw.ellipse((cx - 2.5, cy - 2.5, cx + 2.5, cy + 2.5), fill=(148, 163, 184, 255))
            draw.text((cx + 4, cy - 6), name, font=city_font, fill=(100, 116, 139, 220))

        # 4. 소관시설 마커 렌더링 (단일 정렬 및 TOP4 번호 뱃지 연계)
        ranks = top_facility_ranks or {}
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
            fid = assessment.facility.id

            # TOP 4 시설 번호 뱃지 (Circle + 숫자 1,2,3,4: 흰색 배경 + 등급색 외곽선 + 등급색 숫자)
            if fid in ranks:
                rank_num = str(ranks[fid])
                badge_r = 13.0
                # 정적 Halo 외곽 링
                draw.ellipse(
                    (cx - badge_r - 4, cy - badge_r - 4, cx + badge_r + 4, cy + badge_r + 4),
                    fill=(*col[:3], 65),
                )
                # 원형 뱃지 본체 (선명한 흰색 배경)
                draw.ellipse(
                    (cx - badge_r, cy - badge_r, cx + badge_r, cy + badge_r),
                    fill=(255, 255, 255, 255),
                    outline=col,
                    width=3,
                )
                # 뱃지 내부 숫자 텍스트 중앙 정렬 (선명한 등급색 굵은 텍스트)
                t_bbox = draw.textbbox((cx, cy), rank_num, font=badge_font)
                tw = t_bbox[2] - t_bbox[0]
                th = t_bbox[3] - t_bbox[1]
                draw.text(
                    (cx - tw / 2, cy - th / 2 - 2),
                    rank_num,
                    font=badge_font,
                    fill=col,
                )
            elif grade is RiskGrade.HIGH:
                r = 8.5
                # 정적 Halo 외곽 링
                draw.ellipse((cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4), fill=(217, 45, 32, 70))
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col, outline=(255, 255, 255, 255), width=2)
            elif grade is RiskGrade.MEDIUM:
                r = 6.5
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col, outline=(255, 255, 255, 255), width=1)
            elif grade is RiskGrade.LOW:
                r = 4.5
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col, outline=(255, 255, 255, 255), width=1)
            else:
                r = 3.0
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col, outline=(255, 255, 255, 255), width=1)

        # 5. 특보 발효 구역 텍스트 뱃지 (거리 기반 겹침 방지)
        placed_boxes: list[tuple[int, int, int, int]] = []
        for cx, cy, reg_name, level, w_type in warning_centroids:
            sub_tag = f"{w_type} {'경보' if level in (WarningLevel.WARNING, WarningLevel.CRITICAL) else '주의보'}"
            full_text = f"{reg_name} [{sub_tag}]"

            tag_col = (185, 28, 28, 255) if level in (WarningLevel.WARNING, WarningLevel.CRITICAL) else (194, 65, 12, 255)
            bg_col = (255, 241, 242, 245) if level in (WarningLevel.WARNING, WarningLevel.CRITICAL) else (255, 247, 237, 245)

            bbox = draw.textbbox((cx, cy), full_text, font=warning_tag_font)
            bw = bbox[2] - bbox[0] + 10
            bh = bbox[3] - bbox[1] + 6
            bx = cx - bw // 2
            by = (cy - 12) - bh // 2

            # 겹침 검사 (기존 뱃지와 너무 가까우면 건너뛰어 깔끔함 유지)
            collided = False
            for obx, oby, obw, obh in placed_boxes:
                if abs(bx - obx) < (bw + obw) * 0.45 and abs(by - oby) < (bh + obh) * 0.7:
                    collided = True
                    break
            if collided:
                continue

            placed_boxes.append((bx, by, bw, bh))
            draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=4, fill=bg_col, outline=tag_col, width=1)
            draw.text((bx + 5, by + 2), full_text, font=warning_tag_font, fill=tag_col)

        # 6. 지도 외곽 보더
        draw.rectangle((0, 0, width - 1, height - 1), outline=(203, 213, 225, 255), width=1)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
