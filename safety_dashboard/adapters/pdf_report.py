"""동일한 관제 snapshot을 사용하는 A4 세로형 모던 PDF 보고서."""

from __future__ import annotations

import datetime as dt
import io
from pathlib import Path
from typing import Sequence

from fpdf import FPDF
from fpdf.enums import MethodReturnValue, WrapMode, XPos, YPos

from safety_dashboard.adapters.static_map import StaticSafetyMapRenderer
from safety_dashboard.application.contacts import public_contact
from safety_dashboard.domain.enums import DataHealth, RiskGrade, WarningLevel
from safety_dashboard.domain.models import DashboardSnapshot
from safety_dashboard.domain.safety_guidelines import extract_safety_guidelines

# 모던 공공·기업 디자인 색상 팔레트
NAVY = (15, 23, 42)        # #0F172A (대제목, 중요 수치)
BLUE = (2, 132, 199)       # #0284C7 (포인트 블루)
TEAL = (15, 118, 110)      # #0F766E (포인트 틸)
INK = (30, 41, 59)         # #1E293B (본문 텍스트)
MUTED = (100, 116, 139)    # #64748B (보조 텍스트)
LINE = (226, 232, 240)     # #E2E8F0 (테두리 선)
CARD_BG = (248, 250, 252)  # #F8FAFC (은은한 카드 배경)
WHITE = (255, 255, 255)

GRADE_COLOR = {
    RiskGrade.HIGH: (217, 45, 32),       # #D92D20
    RiskGrade.MEDIUM: (194, 65, 12),     # #C2410C
    RiskGrade.LOW: (138, 109, 0),        # #8A6D00
    RiskGrade.UNASSESSED: (124, 58, 237),# #7C3AED
    RiskGrade.NONE: (23, 107, 135),      # #176B87
}
GRADE_TINT = {
    RiskGrade.HIGH: (253, 239, 237),
    RiskGrade.MEDIUM: (255, 244, 235),
    RiskGrade.LOW: (251, 247, 225),
    RiskGrade.UNASSESSED: (245, 243, 255),
    RiskGrade.NONE: (238, 248, 251),
}
LEVEL_COLOR = {
    WarningLevel.CRITICAL: (185, 28, 28),
    WarningLevel.WARNING: (217, 45, 32),
    WarningLevel.ADVISORY: (217, 119, 6),
    WarningLevel.UNKNOWN: (100, 116, 139),
}


class PdfReportRenderer:
    """A4 세로형(Portrait) 모던 기상재난 시설 안전관리 현황보고서 렌더러."""

    def __init__(self, font_path: str | Path, zone_geojson_path: Path | str | None = None) -> None:
        self.font_path = Path(font_path)
        font_dir = self.font_path.parent if self.font_path.is_file() else self.font_path
        
        # Bold 및 Regular 폰트 분리 지원
        self.bold_font_path = font_dir / "NotoSansKR-Bold.ttf"
        self.regular_font_path = font_dir / "NotoSansKR-Regular.ttf"
        if not self.bold_font_path.exists():
            self.bold_font_path = self.font_path
        if not self.regular_font_path.exists():
            self.regular_font_path = self.font_path

        self.map_renderer = StaticSafetyMapRenderer(zone_geojson_path, font_path=self.regular_font_path)

    def render(
        self,
        snapshot: DashboardSnapshot,
        scope_label: str = "전체 소관시설",
        temporary_policy: bool = False,
    ) -> bytes:
        if not self.font_path.exists():
            raise ValueError(f"PDF 한글 폰트가 없습니다: {self.font_path}")

        simulation = snapshot.warning_feed.health is DataHealth.SIMULATION
        created_at = dt.datetime.now().astimezone()
        pdf = _ReportPdf(
            simulation=simulation,
            temporary_policy=temporary_policy,
            generated_label=created_at.strftime("%Y-%m-%d %H:%M"),
            policy_version=snapshot.policy_version,
            scope_label=scope_label,
            orientation="P",
            unit="mm",
            format="A4",
        )
        pdf.set_margins(12, 14, 12)
        pdf.set_auto_page_break(False, margin=14)
        
        # 폰트 등록 (Bold & Regular 분리)
        pdf.add_font("Ko", "", str(self.regular_font_path))
        pdf.add_font("Ko", "B", str(self.bold_font_path))
        pdf.alias_nb_pages()

        title = "기상재난 시설 영향 보고서"
        pdf.set_title(("[모의훈련] " if simulation else "") + title)
        pdf.add_page()

        # 1. 관제 요약 지표 카드 & 위험등급/특보 정의 가이드
        self._section(pdf, "1", "관제 요약 및 위험등급 기준")
        self._summary_cards(pdf, snapshot)
        self._risk_grade_definition_bar(pdf)
        pdf.ln(3)

        # 2. 권역 지도 + 중점관리 TOP 3 & 안전관리 요령
        self._map_and_highlights(pdf, snapshot)
        pdf.ln(3.5)

        # 3. 영향시설 점검 우선순위 목록
        self._section(pdf, "2", "영향시설 우선순위")
        self._assessment_table(pdf, snapshot)
        pdf.ln(3)

        # 4. 활성 특보 현황
        self._ensure_space(pdf, 22)
        self._section(pdf, "3", "활성 특보")
        self._warning_table(pdf, snapshot)

        return bytes(pdf.output())

    @staticmethod
    def _section(pdf: FPDF, number: str, title: str, continued: bool = False) -> None:
        pdf.set_draw_color(*LINE)
        pdf.set_line_width(0.4)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(1.5)
        pdf.set_font("Ko", "B", 9.5)
        pdf.set_text_color(*NAVY)
        suffix = " (계속)" if continued else ""
        pdf.cell(0, 5.2, f"{number} {title}{suffix}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.0)

    @staticmethod
    def _summary_cards(pdf: FPDF, snapshot: DashboardSnapshot) -> None:
        summary = snapshot.summary
        high_count = summary.high_risk_count
        medium_count = sum(1 for a in snapshot.assessments if a.grade is RiskGrade.MEDIUM)
        affected_count = summary.affected_facility_count
        total_count = len(snapshot.facilities) if snapshot.facilities else 103

        cards = (
            ("소관시설 전체", f"{total_count}개소", "영남권 소관 사업장", CARD_BG, NAVY),
            ("특보 영향시설", f"{affected_count}개소", "기상특보 발효 권역 내", (238, 246, 255), BLUE),
            ("위험 [상] 집중", f"{high_count}개소", "경보 발효 등 긴급 점검", GRADE_TINT[RiskGrade.HIGH], GRADE_COLOR[RiskGrade.HIGH]),
            ("위험 [중] 주의", f"{medium_count}개소", "주의보 발효 등 사전 예찰", GRADE_TINT[RiskGrade.MEDIUM], GRADE_COLOR[RiskGrade.MEDIUM]),
        )
        card_width = 44
        gap = 3.3
        start_y = pdf.get_y()
        for index, (label, value, sub_text, fill, accent) in enumerate(cards):
            x = pdf.l_margin + index * (card_width + gap)
            pdf.set_xy(x, start_y)
            pdf.set_fill_color(*fill)
            pdf.set_draw_color(*LINE)
            pdf.set_line_width(0.3)
            pdf.rect(x, start_y, card_width, 16.5, style="DF")

            # 상단 컬러 바
            pdf.set_fill_color(*accent)
            pdf.rect(x, start_y, card_width, 2.5, style="F")

            pdf.set_xy(x + 3.5, start_y + 3.2)
            pdf.set_font("Ko", "B", 7.2)
            pdf.set_text_color(*MUTED)
            pdf.cell(card_width - 7, 3.8, label)

            pdf.set_xy(x + 3.5, start_y + 7.2)
            pdf.set_font("Ko", "B", 11.5)
            pdf.set_text_color(*accent)
            pdf.cell(card_width - 7, 5.5, value)

            pdf.set_xy(x + 3.5, start_y + 12.5)
            pdf.set_font("Ko", "", 6.2)
            pdf.set_text_color(*MUTED)
            pdf.cell(card_width - 7, 3.2, sub_text)

        pdf.set_y(start_y + 17.5)

    @staticmethod
    def _risk_grade_definition_bar(pdf: FPDF) -> None:
        """위험등급 및 특보 구역 정의 설명 바."""
        y = pdf.get_y()
        total_w = pdf.w - 2 * pdf.l_margin
        pdf.set_xy(pdf.l_margin, y)
        pdf.set_fill_color(241, 245, 249) # #F1F5F9
        pdf.set_draw_color(*LINE)
        pdf.rect(pdf.l_margin, y, total_w, 6.2, style="DF")

        # 등급 정의 텍스트
        pdf.set_xy(pdf.l_margin + 2.5, y + 1.2)
        pdf.set_font("Ko", "B", 6.8)
        pdf.set_text_color(*NAVY)
        pdf.cell(16, 3.8, "등급·구역 안내:")

        # 상
        pdf.set_font("Ko", "B", 6.6)
        pdf.set_text_color(*GRADE_COLOR[RiskGrade.HIGH])
        pdf.cell(15, 3.8, "● 위험 [상]:")
        pdf.set_font("Ko", "", 6.4)
        pdf.set_text_color(*INK)
        pdf.cell(27, 3.8, "즉시 현장 점검·조치 |")

        # 중
        pdf.set_font("Ko", "B", 6.6)
        pdf.set_text_color(*GRADE_COLOR[RiskGrade.MEDIUM])
        pdf.cell(15, 3.8, "● 위험 [중]:")
        pdf.set_font("Ko", "", 6.4)
        pdf.set_text_color(*INK)
        pdf.cell(25, 3.8, "사전 예찰·비상대기 |")

        # 하
        pdf.set_font("Ko", "B", 6.6)
        pdf.set_text_color(*GRADE_COLOR[RiskGrade.LOW])
        pdf.cell(15, 3.8, "● 위험 [하]:")
        pdf.set_font("Ko", "", 6.4)
        pdf.set_text_color(*INK)
        pdf.cell(22, 3.8, "기상 모니터링 |")

        # 특보 구역
        pdf.set_font("Ko", "B", 6.6)
        pdf.set_text_color(*BLUE)
        pdf.cell(16, 3.8, "■ 특보구역:")
        pdf.set_font("Ko", "", 6.4)
        pdf.set_text_color(*INK)
        pdf.cell(32, 3.8, "기상청 경보(적)·주의보(주)")

        pdf.set_y(y + 7.5)

    def _map_and_highlights(self, pdf: FPDF, snapshot: DashboardSnapshot) -> None:
        """좌측: 영남권 정적 지도 (지명/특보 라벨 포함) / 우측: 중점관리 TOP 3 & 안전관리 요령."""
        start_y = pdf.get_y()
        left_w = 90
        right_w = 92.7
        gap = 3.3
        right_x = pdf.l_margin + left_w + gap

        # 1. 좌측: 지도 타이틀 & 지도 렌더링
        pdf.set_xy(pdf.l_margin, start_y)
        pdf.set_font("Ko", "B", 8.6)
        pdf.set_text_color(*NAVY)
        pdf.cell(left_w, 4.2, "소관 권역 기상특보 & 시설 분포", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        map_y = pdf.get_y() + 0.5
        try:
            map_png = self.map_renderer.render_png(snapshot, width=640, height=540)
            map_stream = io.BytesIO(map_png)
            pdf.image(map_stream, x=pdf.l_margin, y=map_y, w=left_w, h=71)
        except Exception:
            pdf.set_xy(pdf.l_margin, map_y)
            pdf.set_fill_color(*CARD_BG)
            pdf.set_draw_color(*LINE)
            pdf.rect(pdf.l_margin, map_y, left_w, 71, style="DF")
            pdf.set_xy(pdf.l_margin, map_y + 30)
            pdf.set_font("Ko", "", 8)
            pdf.set_text_color(*MUTED)
            pdf.cell(left_w, 5, "지도 렌더링 준비 중", align="C")

        # 지도 하단 선명한 컬러 범례 칩 렌더링 (괄호 안 색상명 제거)
        legend_y = map_y + 72.2
        pdf.set_xy(pdf.l_margin, legend_y)
        
        # 🔴 상
        pdf.set_fill_color(*GRADE_COLOR[RiskGrade.HIGH])
        pdf.ellipse(pdf.l_margin + 2, legend_y + 0.5, 3.2, 3.2, style="F")
        pdf.set_xy(pdf.l_margin + 6, legend_y)
        pdf.set_font("Ko", "B", 7.0)
        pdf.set_text_color(*INK)
        pdf.cell(7, 4, "상")

        # 🟠 중
        pdf.set_fill_color(*GRADE_COLOR[RiskGrade.MEDIUM])
        pdf.ellipse(pdf.l_margin + 15, legend_y + 0.5, 3.2, 3.2, style="F")
        pdf.set_xy(pdf.l_margin + 19, legend_y)
        pdf.cell(7, 4, "중")

        # 🟡 하
        pdf.set_fill_color(*GRADE_COLOR[RiskGrade.LOW])
        pdf.ellipse(pdf.l_margin + 28, legend_y + 0.5, 3.2, 3.2, style="F")
        pdf.set_xy(pdf.l_margin + 32, legend_y)
        pdf.cell(7, 4, "하")

        # 구분선
        pdf.set_xy(pdf.l_margin + 41, legend_y)
        pdf.set_text_color(*MUTED)
        pdf.cell(4, 4, "|")

        # 🟥 경보구역
        pdf.set_fill_color(*LEVEL_COLOR[WarningLevel.WARNING])
        pdf.rect(pdf.l_margin + 46, legend_y + 0.5, 3.4, 3.4, style="F")
        pdf.set_xy(pdf.l_margin + 50.5, legend_y)
        pdf.set_text_color(*INK)
        pdf.cell(16, 4, "경보구역")

        # 🟧 주의보구역
        pdf.set_fill_color(*LEVEL_COLOR[WarningLevel.ADVISORY])
        pdf.rect(pdf.l_margin + 68, legend_y + 0.5, 3.4, 3.4, style="F")
        pdf.set_xy(pdf.l_margin + 72.5, legend_y)
        pdf.cell(17, 4, "주의보구역")

        # 2. 우측 상단: 중점 관리 대상 시설 (TOP 3) 카드
        pdf.set_xy(right_x, start_y)
        pdf.set_font("Ko", "B", 8.6)
        pdf.set_text_color(*NAVY)
        pdf.cell(right_w, 4.2, "중점 관리 대상 시설 (TOP 3)", new_x=XPos.RIGHT, new_y=YPos.TOP)

        top_box_y = start_y + 4.7
        pdf.set_xy(right_x, top_box_y)
        pdf.set_fill_color(*CARD_BG)
        pdf.set_draw_color(*LINE)
        pdf.rect(right_x, top_box_y, right_w, 33.5, style="DF")

        ranking = {RiskGrade.HIGH: 0, RiskGrade.MEDIUM: 1, RiskGrade.LOW: 2, RiskGrade.UNASSESSED: 3}
        priority_rows = sorted(
            (item for item in snapshot.assessments if item.grade in (RiskGrade.HIGH, RiskGrade.MEDIUM, RiskGrade.LOW)),
            key=lambda item: (ranking.get(item.grade, 9), item.facility.name),
        )[:3]

        if not priority_rows:
            pdf.set_xy(right_x, top_box_y + 13.5)
            pdf.set_font("Ko", "", 7.5)
            pdf.set_text_color(*MUTED)
            pdf.cell(right_w, 5, "현재 특보 영향권 시설이 없습니다 (안전)", align="C")
        else:
            row_y = top_box_y + 2.5
            for idx, item in enumerate(priority_rows, 1):
                pdf.set_xy(right_x + 3, row_y)
                pdf.set_fill_color(*GRADE_COLOR[item.grade])
                pdf.set_text_color(*WHITE)
                pdf.set_font("Ko", "B", 6.8)
                grade_name = _grade_label(item.grade)
                pdf.cell(11, 4.4, f"{idx}. {grade_name}", fill=True, align="C")

                pdf.set_xy(right_x + 16, row_y)
                pdf.set_font("Ko", "B", 7.6)
                pdf.set_text_color(*INK)
                pdf.cell(44, 4.4, _short(item.facility.name, 15))

                warn_text = ", ".join(dict.fromkeys(f"{r.warning_type} {r.raw_level}" for r in item.reasons))
                pdf.set_xy(right_x + 60, row_y)
                pdf.set_font("Ko", "", 7.0)
                pdf.set_text_color(*MUTED)
                pdf.cell(right_w - 63, 4.4, _short(warn_text, 14), align="R")
                row_y += 5.8

        # 3. 우측 하단: 발효 특보별 핵심 안전관리 요령 카드
        bot_title_y = top_box_y + 36.0
        pdf.set_xy(right_x, bot_title_y)
        pdf.set_font("Ko", "B", 8.6)
        pdf.set_text_color(*NAVY)
        pdf.cell(right_w, 4.2, "발효 특보별 핵심 안전관리 요령", new_x=XPos.RIGHT, new_y=YPos.TOP)

        bot_box_y = bot_title_y + 4.7
        pdf.set_xy(right_x, bot_box_y)
        pdf.set_fill_color(*(240, 249, 255)) # 연한 아이스 블루
        pdf.set_draw_color(186, 230, 253)    # 하늘색 보더
        pdf.rect(right_x, bot_box_y, right_w, 32.5, style="DF")

        guidelines = extract_safety_guidelines(snapshot, max_items=2)
        g_y = bot_box_y + 2.5
        for w_type, g_text in guidelines:
            pdf.set_xy(right_x + 3, g_y)
            pdf.set_fill_color(*BLUE)
            pdf.set_text_color(*WHITE)
            pdf.set_font("Ko", "B", 6.8)
            pdf.cell(13, 4.2, f"[{w_type}]", fill=True, align="C")

            pdf.set_xy(right_x + 18, g_y)
            pdf.set_font("Ko", "", 7.2)
            pdf.set_text_color(*INK)
            pdf.multi_cell(right_w - 20, 4.0, g_text, wrapmode=WrapMode.CHAR)
            g_y = pdf.get_y() + 1.5

        pdf.set_y(start_y + 79)

    @staticmethod
    def _table_header(
        pdf: FPDF,
        widths: tuple[int, ...],
        labels: tuple[str, ...],
    ) -> None:
        pdf.set_font("Ko", "B", 7.6)
        pdf.set_fill_color(*NAVY)
        pdf.set_draw_color(*WHITE)
        pdf.set_text_color(*WHITE)
        for width, label in zip(widths, labels):
            pdf.cell(width, 6.0, label, border=1, fill=True, align="C")
        pdf.ln()

    def _assessment_table(self, pdf: FPDF, snapshot: DashboardSnapshot) -> None:
        widths = (8, 14, 40, 24, 42, 58)
        labels = ("순위", "등급", "시설명", "시설구분", "해당 기상특보", "담당부서 · 담당자")
        ranking = {
            RiskGrade.HIGH: 0,
            RiskGrade.MEDIUM: 1,
            RiskGrade.LOW: 2,
            RiskGrade.UNASSESSED: 3,
        }
        rows = sorted(
            (item for item in snapshot.assessments if item.grade is not RiskGrade.NONE),
            key=lambda item: (ranking.get(item.grade, 9), item.facility.name),
        )
        self._table_header(pdf, widths, labels)
        if not rows:
            self._empty_row(pdf, sum(widths), "현재 특보 영향 시설이 없습니다.")
            return

        for index, item in enumerate(rows, 1):
            warnings = ", ".join(
                dict.fromkeys(f"{reason.warning_type} {reason.raw_level}" for reason in item.reasons)
            )
            values = (
                str(index),
                _grade_label(item.grade),
                item.facility.name,
                item.facility.facility_type,
                warnings,
            )
            limits = (4, 8, 20, 13, 20)
            contact = public_contact(item.facility).replace(" · ", "\n", 1)
            pdf.set_font("Ko", "", 6.6)
            contact_lines = pdf.multi_cell(
                widths[-1] - 2,
                3.4,
                contact,
                dry_run=True,
                output=MethodReturnValue.LINES,
                wrapmode=WrapMode.CHAR,
            )
            row_height = max(6.0, len(contact_lines) * 3.4 + 1.2)
            if pdf.get_y() + row_height > pdf.page_break_trigger:
                pdf.add_page()
                self._section(pdf, "2", "영향시설 우선순위", continued=True)
                self._table_header(pdf, widths, labels)
            fill = GRADE_TINT[item.grade] if index % 2 == 1 else WHITE
            for column, (width, value, limit) in enumerate(
                zip(widths[:-1], values, limits)
            ):
                if column == 1:
                    pdf.set_fill_color(*GRADE_COLOR[item.grade])
                    pdf.set_text_color(*WHITE)
                    pdf.set_font("Ko", "B", 7.2)
                else:
                    pdf.set_fill_color(*fill)
                    pdf.set_text_color(*INK)
                    pdf.set_font("Ko", "", 7.2)
                pdf.set_draw_color(*LINE)
                pdf.cell(
                    width,
                    row_height,
                    _short(value, limit),
                    border=1,
                    fill=True,
                    align="C",
                )

            contact_x = pdf.get_x()
            contact_y = pdf.get_y()
            contact_width = widths[-1]
            pdf.set_fill_color(*fill)
            pdf.set_draw_color(*LINE)
            pdf.rect(contact_x, contact_y, contact_width, row_height, style="DF")
            pdf.set_font("Ko", "", 6.6)
            pdf.set_text_color(*INK)
            text_y = contact_y + (row_height - len(contact_lines) * 3.4) / 2
            for line in contact_lines:
                pdf.set_xy(contact_x + 1, text_y)
                pdf.cell(contact_width - 2, 3.4, line, align="C")
                text_y += 3.4
            pdf.set_xy(pdf.l_margin, contact_y + row_height)

    def _warning_table(self, pdf: FPDF, snapshot: DashboardSnapshot) -> None:
        widths = (31, 31, 31, 27, 33, 33)
        labels = ("광역", "특보구역", "특보종류", "단계", "발표시각", "발효시각")
        self._table_header(pdf, widths, labels)
        if not snapshot.warning_feed.warnings:
            self._empty_row(pdf, sum(widths), "현재 선택 시설에 연결된 활성 특보가 없습니다.")
            return

        for index, warning in enumerate(snapshot.warning_feed.warnings):
            row_height = 5.4
            if pdf.get_y() + row_height > pdf.page_break_trigger:
                pdf.add_page()
                self._section(pdf, "3", "활성 특보", continued=True)
                self._table_header(pdf, widths, labels)
            fill = (248, 250, 252) if index % 2 == 0 else WHITE
            pdf.set_draw_color(*LINE)
            pdf.set_fill_color(*fill)
            values = (
                warning.region_up,
                warning.region,
                warning.warning_type,
                warning.raw_level,
                warning.issued_at.strftime("%m-%d %H:%M") if warning.issued_at else "-",
                warning.effective_at.strftime("%m-%d %H:%M") if warning.effective_at else "-",
            )
            for col_idx, (width, value) in enumerate(zip(widths, values)):
                if col_idx == 3:
                    pdf.set_fill_color(*LEVEL_COLOR.get(warning.level, (100, 116, 139)))
                    pdf.set_text_color(*WHITE)
                    pdf.set_font("Ko", "B", 6.8)
                else:
                    pdf.set_fill_color(*fill)
                    pdf.set_text_color(*INK)
                    pdf.set_font("Ko", "", 7.2)
                pdf.cell(
                    width,
                    row_height,
                    _short(value, 16),
                    border=1,
                    fill=True,
                    align="C",
                )
            pdf.ln()

    @staticmethod
    def _empty_row(pdf: FPDF, width: int, message: str) -> None:
        pdf.set_font("Ko", "", 7.8)
        pdf.set_fill_color(*CARD_BG)
        pdf.set_draw_color(*LINE)
        pdf.set_text_color(*MUTED)
        pdf.cell(width, 7.5, message, border=1, fill=True, align="C")
        pdf.ln()

    @staticmethod
    def _ensure_space(pdf: FPDF, height: float) -> None:
        if pdf.get_y() + height > pdf.page_break_trigger:
            pdf.add_page()


class _ReportPdf(FPDF):
    """세로형 모던 헤더 및 푸터가 포함된 커스텀 FPDF 클래스."""

    def __init__(
        self,
        simulation: bool,
        temporary_policy: bool,
        generated_label: str,
        policy_version: str,
        scope_label: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.simulation = simulation
        self.temporary_policy = temporary_policy
        self.generated_label = generated_label
        self.policy_version = policy_version
        self.scope_label = scope_label

    def header(self) -> None:
        # 1. 최상단 모던 투톤 스트라이프 바 (Blue + Teal)
        self.set_xy(self.l_margin, 6)
        self.set_fill_color(*BLUE)
        self.rect(self.l_margin, 6, (self.w - 2 * self.l_margin) * 0.7, 2, style="F")
        self.set_fill_color(*TEAL)
        self.rect(self.l_margin + (self.w - 2 * self.l_margin) * 0.7, 6, (self.w - 2 * self.l_margin) * 0.3, 2, style="F")

        # 2. 메인 타이틀
        self.set_xy(self.l_margin, 9)
        self.set_font("Ko", "B", 14)
        self.set_text_color(*NAVY)
        title = "K-ECO 기상재난 시설 영향 보고서"
        self.cell(105, 6, title, new_x=XPos.RIGHT, new_y=YPos.TOP)

        # 3. 모의훈련 / 임시정책 뱃지
        badge_x = self.get_x() + 2
        if self.simulation:
            self.set_xy(badge_x, 9.8)
            self.set_fill_color(217, 45, 32)
            self.set_text_color(*WHITE)
            self.set_font("Ko", "B", 7)
            self.cell(15, 4.5, "모의훈련", fill=True, align="C")
            badge_x += 17
        if self.temporary_policy:
            self.set_xy(badge_x, 9.8)
            self.set_fill_color(217, 119, 6)
            self.set_text_color(*WHITE)
            self.set_font("Ko", "B", 7)
            self.cell(15, 4.5, "임시정책", fill=True, align="C")

        # 4. 우측 메타 라인 (발행일시)
        self.set_xy(self.w - self.r_margin - 50, 9.5)
        self.set_font("Ko", "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(50, 5, f"발행일시: {self.generated_label}", align="R")

        # 5. 서브 메타 정보
        self.set_xy(self.l_margin, 15.2)
        self.set_font("Ko", "", 7.2)
        self.set_text_color(*MUTED)
        self.cell(
            self.w - 2 * self.l_margin,
            4,
            f"관제 범위: {self.scope_label}  |  위험도 정책 기준: {self.policy_version}",
        )
        self.ln(5)

    def footer(self) -> None:
        self.set_y(-10)
        self.set_draw_color(*LINE)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(1.5)
        self.set_font("Ko", "", 6.8)
        self.set_text_color(*MUTED)
        self.cell(
            self.w - 2 * self.l_margin,
            4,
            f"K-ECO 스마트 안전관제 시스템  |  페이지 {self.page_no()} / {{nb}}",
            align="C",
        )


def _short(text: str, limit: int) -> str:
    cleaned = " ".join(str(text).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _grade_label(grade: RiskGrade) -> str:
    labels = {
        RiskGrade.HIGH: "상",
        RiskGrade.MEDIUM: "중",
        RiskGrade.LOW: "하",
        RiskGrade.UNASSESSED: "미판정",
        RiskGrade.NONE: "영향없음",
    }
    return labels.get(grade, "-")
