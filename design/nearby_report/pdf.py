"""실제 지도 캡처를 받는 개발 전용 A4 시안. 운영 API와 별개다."""
from __future__ import annotations

import io
import hashlib
from fpdf import FPDF
from fpdf.enums import MethodReturnValue, WrapMode

from safety_dashboard.adapters.nearby_pdf_report import NearbyPdfReportRenderer, format_distance, report_text
from safety_dashboard.adapters.pdf_report import BLUE, CARD_BG, INK, LINE, MUTED, NAVY, TEAL, WHITE
from safety_dashboard.application.nearby_report import KST, NearbyReport
from design.nearby_report.model import summary


class _PreviewPdf(FPDF):
    def header(self):
        self.set_fill_color(*TEAL)
        self.rect(12, 9, 186, 1.3, "F")
        self.set_font("Ko", "B", 14)
        self.set_text_color(*NAVY)
        self.set_xy(12, 14)
        self.cell(163, 8, "기준점 주변 시설 현황 보고서")
        self.set_fill_color(*CARD_BG)
        self.set_text_color(*TEAL)
        self.set_font("Ko", "B", 7)
        self.cell(23, 7, "개발용 시안", align="C", fill=True)
        self.set_font("Ko", "", 7)
        self.set_text_color(*MUTED)
        self.set_xy(12, 24)
        self.cell(110, 5, "K-ECO 현장 안전지도 · 기준점 주변 소관시설 조회")
        self.cell(76, 5, self.generated_label, align="R")
        self.set_y(33)

    def footer(self):
        self.set_draw_color(*LINE)
        self.line(12, 281, 198, 281)
        self.set_xy(12, 283)
        self.set_font("Ko", "", 6.8)
        self.set_text_color(*MUTED)
        self.cell(155, 5, "직선거리 참고자료 · 반경 내 위치는 실제 피해·위험도 판정이 아닙니다.")
        self.cell(31, 5, f"{self.page_no()} / {{nb}}", align="R")


def validate_map(report: NearbyReport, metadata: dict) -> dict[str, int]:
    """지도·집계·목록의 시설 ID와 기준점을 검증한다. 실패는 백지 지도로 숨기지 않는다."""
    if any(metadata.get(key) != value for key, value in {
            "latitude": report.point.latitude, "longitude": report.point.longitude,
            "radius_km": report.radius_km}.items()):
        raise ValueError("기준점·반경이 지도 캡처와 다릅니다.")
    expected = {row.facility.id: row.facility.location for row in report.facilities}
    captured = metadata.get("facilities", [])
    if len(captured) != len(expected) or {item["id"] for item in captured} != expected.keys():
        raise ValueError("지도 캡처와 PDF의 대상 시설이 다릅니다.")
    for item in captured:
        point = expected[item["id"]]
        if (item["latitude"], item["longitude"]) != (point.latitude, point.longitude):
            raise ValueError("시설 좌표가 지도 캡처와 다릅니다.")
    ids = {}
    numbers = []
    for group in metadata["geometry"]["groups"]:
        if not group["ids"] or not isinstance(group["number"], int) or group["number"] < 1:
            raise ValueError("유효하지 않은 지도 번호입니다.")
        numbers.append(group["number"])
        for facility_id in group["ids"]:
            if facility_id in ids:
                raise ValueError("지도 번호에 시설이 중복되었습니다.")
            ids[facility_id] = group["number"]
    if ids.keys() != expected.keys() or len(set(numbers)) != len(numbers):
        raise ValueError("지도 번호에 누락·중복이 있습니다.")
    if metadata["summary"] != summary(report):
        raise ValueError("지도 입력과 보고서 집계가 다릅니다.")
    return ids


class NearbyPreviewRenderer(NearbyPdfReportRenderer):
    WIDTHS = (12, 40, 25, 17, 51, 41)
    HEADERS = ("지도", "시설명", "유형", "직선거리", "주소", "담당부서")

    def _section(self, pdf, number, title, note=""):
        if pdf.get_y() + 13 > 277:
            pdf.add_page()
        x, y = 12, pdf.get_y()
        pdf.set_draw_color(*LINE)
        pdf.line(x, y, 198, y)
        pdf.set_font("Ko", "B", 9)
        pdf.set_text_color(*NAVY)
        pdf.set_xy(x, y + 1.5)
        pdf.cell(115, 6, f"{number}  {title}")
        pdf.set_font("Ko", "", 6.8)
        pdf.set_text_color(*MUTED)
        pdf.cell(71, 6, note, align="R")
        pdf.set_xy(12, y + 8)

    @staticmethod
    def _block_text(pdf, text, x, y, width, *, size=8, bold=False, color=INK):
        pdf.set_font("Ko", "B" if bold else "", size)
        pdf.set_text_color(*color)
        pdf.set_xy(x, y)
        pdf.multi_cell(width, size * .43 + .7, report_text(text), wrapmode=WrapMode.CHAR)
        return pdf.get_y()

    def render(self, report: NearbyReport, map_png: bytes, metadata: dict) -> bytes:
        group_ids = validate_map(report, metadata)
        if not map_png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("실제 지도 PNG가 필요합니다.")
        if hashlib.sha256(map_png).hexdigest() != metadata.get("pngSha256"):
            raise ValueError("지도 이미지와 캡처 메타데이터가 다릅니다.")
        pdf = _PreviewPdf(orientation="P", unit="mm", format="A4")
        pdf.generated_label = report.generated_at.astimezone(KST).strftime("생성 %Y.%m.%d %H:%M KST")
        pdf.set_margins(12, 14, 12)
        pdf.set_auto_page_break(False)
        for style, name in [("", "NotoSansKR-Regular.ttf"), ("B", "NotoSansKR-Bold.ttf")]:
            path = self.font_path.parent / name
            pdf.add_font("Ko", style, str(path if path.exists() else self.font_path))
        pdf.alias_nb_pages()
        pdf.set_title("[검토 시안] 기준점 주변 시설 현황 보고서")
        pdf.add_page()
        stat = summary(report)
        y = self._block_text(pdf, report.label, 12, 33, 186, size=10.4, bold=True, color=NAVY)
        y = self._block_text(pdf, report.address or "주소 정보 없음", 12, y + .5, 186, size=7, color=MUTED)
        pdf.set_font("Ko", "", 7)
        pdf.set_text_color(*MUTED)
        pdf.set_xy(12, y + .5)
        pdf.cell(186, 5, f"기준점 {report.point.latitude:.5f}, {report.point.longitude:.5f}  ·  전체 명부 {report.total_count}개소 기준")
        y = pdf.get_y() + 5
        if metadata.get("synthetic"):
            y = self._block_text(pdf, "검수용 합성 시설 자료 · 실제 시설 또는 실제 사건 현황이 아닙니다.",
                                 12, y, 186, size=7.5, bold=True, color=TEAL) + 2
        pdf.set_fill_color(239, 246, 255)
        pdf.rect(12, y, 186, 8, "F")
        nearest = stat["nearest_meters"]
        message = f"반경 {report.radius_km:g}km 안 등록시설 {stat['count']}개소"
        message += f"  ·  최근접 {format_distance(nearest)}" if nearest is not None else "  ·  반경 내 등록시설 없음"
        self._block_text(pdf, message, 15, y + 2, 180, size=8.3, bold=True, color=(3, 105, 161))
        y += 10
        cards = [("반경 내 시설", f"{stat['count']}개소", "선택한 반경 안의 등록시설", BLUE),
                 ("최근접 거리", format_distance(nearest) if nearest is not None else "—", "기준점부터 직선거리", TEAL),
                 ("시설 유형", f"{len(stat['types'])}종", "반경 내 시설 유형 구성", NAVY),
                 ("담당부서", f"{sum(r['label'] != '-' for r in stat['departments'])}개", "명부에 등록된 담당부서", NAVY)]
        for index, (title, value, subtitle, color) in enumerate(cards):
            x = 12 + index * 47.5
            pdf.set_fill_color(*CARD_BG)
            pdf.set_draw_color(*LINE)
            pdf.rect(x, y, 43.5, 18, "DF")
            pdf.set_fill_color(*color)
            pdf.rect(x, y, 43.5, 1, "F")
            self._block_text(pdf, title, x + 3, y + 2, 38, size=6.7, bold=True, color=MUTED)
            self._block_text(pdf, value, x + 3, y + 6.5, 38, size=12.5, bold=True, color=color)
            self._block_text(pdf, subtitle, x + 3, y + 14, 38, size=5.7, color=MUTED)
        pdf.set_xy(12, y + 22)
        self._section(pdf, "1", "주변 시설 위치도", "파랑: 기준점·반경 / 청록: 시설 번호")
        y = pdf.get_y()
        pdf.image(io.BytesIO(map_png), x=12, y=y, w=186, h=96.1)
        pdf.set_draw_color(*LINE)
        pdf.rect(12, y, 186, 96.1)
        self._block_text(pdf, "같은 번호는 밀집 시설 묶음입니다. 점은 실제 좌표, 연결선은 번호 위치를 안내합니다.",
                         12, y + 97.5, 148, size=6.5, color=MUTED)
        pdf.set_font("Ko", "", 6.5)
        pdf.set_text_color(*TEAL)
        pdf.set_xy(161, y + 97.5)
        pdf.cell(37, 4, "지도: Kakao · 지도 열기", align="R",
                 link=f"https://map.kakao.com/link/map/{report.point.latitude},{report.point.longitude}")
        pdf.set_xy(12, y + 103)
        count = len(report.facilities)
        self._section(pdf, "2", "가까운 시설" if count <= 5 else "가까운 시설 TOP 5",
                      "거리순 전체 목록" if count <= 5 else f"전체 {count}개소 중 거리순")
        if not count:
            self._block_text(pdf, "반경 내 등록시설 0개소", 15, pdf.get_y() + 1, 180, size=10, bold=True, color=TEAL)
            self._block_text(pdf, "시설 명부와 선택 반경을 기준으로 조회한 결과입니다. 실제 피해 여부와는 별개입니다.",
                             15, pdf.get_y() + 2, 180, size=7.5, color=MUTED)
            pdf.set_xy(12, pdf.get_y() + 7)
        elif count <= 5:
            self._full_list(pdf, report, group_ids)
        else:
            self.WIDTHS = (12, 58, 29, 19, 68)
            self.HEADERS = ("지도", "시설명", "유형", "직선거리", "담당부서")
            self._table_header(pdf)
            for row in report.facilities[:5]:
                f = row.facility
                self._row(pdf, [str(group_ids[f.id]), report_text(f.name), report_text(f.facility_type),
                                format_distance(row.meters), report_text(f.department)])
        pdf.ln(4)
        analysis_height = self._analysis_height(pdf, stat)
        if pdf.get_y() + 8 + analysis_height > 277:
            pdf.add_page()
        self._section(pdf, "3", "거리·유형·담당부서 현황", "각 분류의 합계 = 반경 내 시설 수")
        self._analysis(pdf, stat)
        if count > 5:
            pdf.ln(6)
            if pdf.get_y() + 33 > 277:
                pdf.add_page()
            self._section(pdf, "4", "거리순 전체 시설 목록", f"총 {count}개소 · 지도 번호 연결")
            self._full_list(pdf, report, group_ids)
        return bytes(pdf.output())

    def _full_list(self, pdf, report, group_ids):
        self.WIDTHS, self.HEADERS = type(self).WIDTHS, type(self).HEADERS
        self._table_header(pdf)
        for row in report.facilities:
            f = row.facility
            self._row(pdf, [str(group_ids[f.id]), report_text(f.name), report_text(f.facility_type),
                            format_distance(row.meters), report_text(f.address), report_text(f.department)])

    def _row(self, pdf, values):
        # 원본 렌더러의 긴 행 분할을 유지하면서 시안의 표 간격을 맞춘다.
        pdf.set_font("Ko", "", 7.2)
        lines = [pdf.multi_cell(width - 2, 3.7, value, dry_run=True,
                               output=MethodReturnValue.LINES, wrapmode=WrapMode.CHAR)
                 for width, value in zip(self.WIDTHS, values)]
        height = max(map(len, lines)) * 3.7 + 2.5
        if pdf.get_y() + height > 277 and pdf.get_y() > 36:
            pdf.add_page()
            self._table_header(pdf)
        continuation = False
        while any(lines):
            available = int((277 - pdf.get_y() - 2.5) / 3.7)
            if available < 1:
                pdf.add_page()
                self._table_header(pdf)
                available = int((277 - pdf.get_y() - 2.5) / 3.7)
            pdf.set_font("Ko", "", 7.2)
            pdf.set_text_color(*INK)
            count, top, x = min(available, max(map(len, lines))), pdf.get_y(), 12
            for index, (width, column_lines) in enumerate(zip(self.WIDTHS, lines)):
                chunk = column_lines[:count]
                del column_lines[:count]
                if continuation and index == 0 and not chunk:
                    chunk = [values[0]]
                for line_index, line in enumerate(chunk):
                    pdf.set_xy(x + 1, top + 1.25 + line_index * 3.7)
                    pdf.cell(width - 2, 3.7, line)
                x += width
            height = count * 3.7 + 2.5
            pdf.set_draw_color(*LINE)
            pdf.line(12, top + height, 198, top + height)
            pdf.set_xy(12, top + height)
            continuation = True

    def _panel_rows(self, pdf, rows, width=54):
        pdf.set_font("Ko", "", 7.1)
        return [(row, pdf.multi_cell(width - 8, 3.7, row["label"], dry_run=True,
                                     output=MethodReturnValue.LINES, wrapmode=WrapMode.CHAR)) for row in rows]

    def _analysis_height(self, pdf, stat):
        return max(12 + sum(len(lines) * 3.7 + 1.5 for _, lines in self._panel_rows(pdf, stat[key]))
                   for key in ("bands", "types", "departments"))

    def _analysis(self, pdf, stat):
        y, height = pdf.get_y(), self._analysis_height(pdf, stat)
        sections = [("거리대별 분포", "bands", BLUE), ("시설 유형", "types", TEAL), ("담당부서", "departments", NAVY)]
        if height > 225:
            # 명부의 유형/부서 종류가 많은 경우도 분류 항목을 생략하지 않는다.
            for title, key, color in sections:
                self._section(pdf, "·", title)
                for row, lines in self._panel_rows(pdf, stat[key], 180):
                    h = len(lines) * 3.7 + 5
                    if pdf.get_y() + h > 277:
                        pdf.add_page()
                        self._section(pdf, "·", title + " (계속)")
                    self._block_text(pdf, f"{row['label']}  {row['count']}개소", 15, pdf.get_y(), 180, size=7.1)
                    pdf.ln(3)
            return
        for index, (title, key, color) in enumerate(sections):
            x = 12 + index * 63.5
            pdf.set_fill_color(*CARD_BG)
            pdf.set_draw_color(*LINE)
            pdf.rect(x, y, 59, height, "DF")
            self._block_text(pdf, title, x + 3, y + 3, 53, size=8, bold=True, color=color)
            current = y + 10
            if not stat[key]:
                self._block_text(pdf, "해당 시설 없음", x + 3, current, 53, size=7, color=MUTED)
            for row, lines in self._panel_rows(pdf, stat[key]):
                self._block_text(pdf, "\n".join(lines), x + 3, current, 46, size=7.1)
                pdf.set_font("Ko", "B", 7.1)
                pdf.set_text_color(*color)
                pdf.set_xy(x + 49, current)
                pdf.cell(7, 4, str(row["count"]), align="R")
                current += len(lines) * 3.7 + .2
                pdf.set_fill_color(*LINE)
                pdf.rect(x + 3, current, 53, 1, "F")
                if row["count"]:
                    pdf.set_fill_color(*color)
                    pdf.rect(x + 3, current, 53 * row["count"] / stat["count"], 1, "F")
                current += 1.3
        pdf.set_xy(12, y + height)
