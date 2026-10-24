"""외부 지도·기상 조회 없이 만드는 A4 주변 시설 보고서."""

from __future__ import annotations

import math
import unicodedata
from collections import Counter
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import MethodReturnValue, WrapMode

from safety_dashboard.application.contacts import _PHONE
from safety_dashboard.application.nearby_report import KST, NearbyReport, bearing_radians
from safety_dashboard.adapters.pdf_report import NAVY, TEAL, INK, MUTED, LINE, CARD_BG, WHITE


def report_text(value: str) -> str:
    text = "".join(" " if unicodedata.category(c).startswith("C") else c for c in str(value))
    return " ".join(_PHONE.sub("", text).split()) or "-"


def format_distance(meters: float) -> str:
    return f"{math.floor(meters + 0.5)}m" if meters < 1000 else f"{meters / 1000:.1f}km"


class _NearbyPdf(FPDF):
    def header(self):
        self.set_fill_color(*TEAL)
        self.rect(12, 10, 186, 1.3, "F")
        self.set_text_color(*NAVY)
        self.set_font("Ko", "B", 14)
        self.set_xy(12, 16)
        self.cell(186, 9, "기준점 주변 시설 현황 보고서")
        self.set_y(29)

    def footer(self):
        self.set_xy(12, 282)
        self.set_font("Ko", "", 7)
        self.set_text_color(*MUTED)
        self.cell(150, 5, "직선거리 참고자료 · 반경 내 위치는 실제 피해·영향 판정이 아닙니다.")
        self.cell(36, 5, f"{self.page_no()} / {{nb}}", align="R")


class NearbyPdfReportRenderer:
    WIDTHS = (13, 34, 24, 17, 56, 42)
    HEADERS = ("위치도", "시설명", "유형", "직선거리", "주소", "담당부서")

    def __init__(self, font_path: str | Path):
        self.font_path = Path(font_path)

    def render(self, report: NearbyReport) -> bytes:
        pdf = _NearbyPdf(orientation="P", unit="mm", format="A4")
        pdf.set_margins(12, 14, 12)
        pdf.set_auto_page_break(False)
        for style, name in [("", "NotoSansKR-Regular.ttf"), ("B", "NotoSansKR-Bold.ttf")]:
            path = self.font_path.parent / name
            pdf.add_font("Ko", style, str(path if path.exists() else self.font_path))
        pdf.alias_nb_pages()
        pdf.set_title("기준점 주변 시설 현황 보고서")
        pdf.add_page()
        self._text(pdf, report_text(report.label), size=12, bold=True)
        self._text(pdf, report_text(report.address), size=8)
        self._text(pdf, f"기준점 {report.point.latitude:.5f}, {report.point.longitude:.5f}  |  "
                   f"생성 {report.generated_at.astimezone(KST):%Y.%m.%d %H:%M} KST", size=7, muted=True)
        pdf.ln(3)
        self._text(pdf, f"반경 {report.radius_km:g}km 안 등록시설 {len(report.facilities)}개소", size=13, bold=True)
        self._text(pdf, f"전체 소관시설 {report.total_count}개소 기준 · 지도 필터 및 전파 대상 선택과 무관", size=7, muted=True)
        counts = Counter(row.facility.facility_type for row in report.facilities)
        if counts:
            self._text(pdf, "  ·  ".join(f"{report_text(k)} {v}" for k, v in sorted(counts.items())), size=8)
        pdf.ln(3)
        groups, group_ids = self._map_groups(report)
        self._location_map(pdf, report, groups)
        pdf.ln(3)
        self._text(pdf, "가까운 시설 순서", size=10, bold=True)
        if not report.facilities:
            self._text(pdf, "반경 내 등록시설 0개소", size=11, bold=True)
            self._text(pdf, "조회 반경 안에 등록된 소관시설이 없습니다. 실제 피해 여부를 뜻하지 않습니다.", size=8)
        else:
            self._table_header(pdf)
            for row in report.facilities:
                f = row.facility
                values = [str(group_ids[f.id]), f.name, f.facility_type, format_distance(row.meters), f.address, f.department]
                self._row(pdf, [report_text(v) for v in values])
        return bytes(pdf.output())

    @staticmethod
    def _text(pdf: FPDF, text: str, size=9, bold=False, muted=False):
        pdf.set_font("Ko", "B" if bold else "", size)
        pdf.set_text_color(*(MUTED if muted else INK))
        pdf.set_x(12)
        pdf.multi_cell(186, size * 0.46 + 1, text, wrapmode=WrapMode.CHAR)
        pdf.set_x(12)

    @staticmethod
    def _map_groups(report: NearbyReport):
        # 원점으로부터 거리/방위를 보존하는 방위정거 위치도. 배경 도로를 가장하지 않는다.
        groups: list[dict] = []
        group_ids: dict[str, int] = {}
        for row in report.facilities:
            bearing = bearing_radians(report.point, row.facility.location)
            factor = row.meters / (report.radius_km * 1000) * 36
            x, y = math.sin(bearing) * factor, -math.cos(bearing) * factor
            group = next((g for g in groups if math.hypot(g["x"] - x, g["y"] - y) < 6), None)
            if group is None:
                group = dict(number=len(groups) + 1, x=x, y=y, count=0)
                groups.append(group)
            group["count"] += 1
            group_ids[row.facility.id] = group["number"]
        return groups, group_ids

    def _location_map(self, pdf: FPDF, report: NearbyReport, groups):
        top = pdf.get_y()
        cx, cy, radius = 105, top + 43, 36
        pdf.set_fill_color(*CARD_BG)
        pdf.set_draw_color(*LINE)
        pdf.rect(12, top, 186, 92, "DF")
        pdf.set_font("Ko", "", 7)
        pdf.set_text_color(*MUTED)
        pdf.set_xy(16, top + 3)
        pdf.cell(170, 5, "주변 시설 위치도 · 도로 없는 거리 참고도")
        for fraction in (0.5, 1):
            pdf.set_draw_color(*LINE)
            r = radius * fraction
            pdf.ellipse(cx - r, cy - r, r * 2, r * 2)
            pdf.set_xy(cx + 1, cy - r)
            pdf.cell(25, 4, f"{report.radius_km * fraction:g}km")
        pdf.set_draw_color(*TEAL)
        pdf.line(cx - 2, cy, cx + 2, cy)
        pdf.line(cx, cy - 2, cx, cy + 2)
        pdf.set_font("Ko", "B", 7)
        pdf.set_text_color(*NAVY)
        pdf.set_xy(cx + 3, cy - 2)
        pdf.cell(18, 4, "기준점")
        for g in groups:
            x, y = cx + g["x"], cy + g["y"]
            # 겹치는 실제 위치는 바꾸지 않고 번호 배지만 원점 밖으로 옮긴다.
            bx, by = (x + 8, y + 7) if math.hypot(x - cx, y - cy) < 8 else (x, y)
            if (bx, by) != (x, y):
                pdf.set_draw_color(*TEAL)
                pdf.line(x, y, bx, by)
            pdf.set_fill_color(*TEAL)
            pdf.ellipse(bx - 2.5, by - 2.5, 5, 5, "F")
            pdf.set_text_color(*WHITE)
            pdf.set_font("Ko", "B", 6.5)
            pdf.set_xy(bx - 2.5, by - 2.1)
            pdf.cell(5, 4, str(g["number"]), align="C")
            if g["count"] > 1:
                pdf.set_text_color(*TEAL)
                pdf.set_xy(bx + 3, by - 2)
                pdf.cell(15, 4, f"{g['count']}개소")
        pdf.set_draw_color(*NAVY)
        pdf.line(184, top + 21, 184, top + 12)
        pdf.line(184, top + 12, 182.7, top + 15)
        pdf.line(184, top + 12, 185.3, top + 15)
        pdf.set_text_color(*NAVY)
        pdf.set_xy(181, top + 7)
        pdf.cell(10, 4, "북 N")
        pdf.line(20, top + 78, 38, top + 78)
        pdf.line(20, top + 76, 20, top + 79)
        pdf.line(38, top + 76, 38, top + 79)
        pdf.set_xy(20, top + 79)
        pdf.cell(40, 4, f"{report.radius_km / 2:g}km")
        pdf.set_text_color(*MUTED)
        pdf.set_font("Ko", "", 6.8)
        pdf.set_xy(16, top + 86)
        pdf.cell(174, 4, "위치도 번호는 아래 목록과 연결됩니다. 같은 위치·밀집 시설은 묶어 표시합니다.")
        pdf.set_xy(12, top + 92)

    def _table_header(self, pdf: FPDF):
        pdf.set_font("Ko", "B", 7.5)
        pdf.set_text_color(*NAVY)
        pdf.set_fill_color(*CARD_BG)
        pdf.set_draw_color(*LINE)
        pdf.set_x(12)
        for width, title in zip(self.WIDTHS, self.HEADERS):
            pdf.cell(width, 7, title, border="B", fill=True)
        pdf.ln(7)

    def _row(self, pdf: FPDF, values: list[str]):
        pdf.set_font("Ko", "", 7.5)
        pdf.set_text_color(*INK)
        lines = [pdf.multi_cell(w - 2, 4.2, v, dry_run=True, output=MethodReturnValue.LINES,
                               wrapmode=WrapMode.CHAR) for w, v in zip(self.WIDTHS, values)]
        height = max(map(len, lines)) * 4.2 + 3
        if pdf.get_y() + height > 277 and pdf.get_y() > 36:
            pdf.add_page()
            self._table_header(pdf)
        continuation = False
        while any(lines):
            available = int((277 - pdf.get_y() - 3) / 4.2)
            if available < 1:
                pdf.add_page()
                self._table_header(pdf)
                available = int((277 - pdf.get_y() - 3) / 4.2)
            pdf.set_font("Ko", "", 7.5)
            pdf.set_text_color(*INK)
            count = min(available, max(map(len, lines)))
            top, x = pdf.get_y(), 12
            for column, (width, column_lines) in enumerate(zip(self.WIDTHS, lines)):
                chunk = column_lines[:count]
                del column_lines[:count]
                if continuation and column == 0 and not chunk:
                    chunk = [values[0]]
                for index, line in enumerate(chunk):
                    pdf.set_xy(x + 1, top + 1.5 + index * 4.2)
                    pdf.cell(width - 2, 4.2, line)
                x += width
            height = count * 4.2 + 3
            pdf.set_draw_color(*LINE)
            pdf.line(12, top + height, 198, top + height)
            pdf.set_xy(12, top + height)
            continuation = True
