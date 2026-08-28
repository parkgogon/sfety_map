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

        # 1. 관제 요약 지표 카드 및 권역 지도
        self._section(pdf, "1", "관제 요약")
        self._summary_cards(pdf, snapshot)
        pdf.ln(3.5)

        # 권역 지도(와이드+통합범례) + 중점관리 TOP 4 & 안전관리 요령
        self._map_and_highlights(pdf, snapshot)
        pdf.ln(3.5)

        # 2. 영향시설 점검 우선순위 목록
        self._section(pdf, "2", "영향시설 우선순위")
        self._assessment_table(pdf, snapshot)
        pdf.ln(3)

        # 3. 활성 특보 현황
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

    def _map_and_highlights(self, pdf: FPDF, snapshot: DashboardSnapshot) -> None:
        """좌측: 대형 와이드 지도 + 일체형 통합 범례 푸터 / 우측: 일체형 인포 패널."""
        start_y = pdf.get_y()
        left_w = 116.0
        right_w = 66.7
        gap = 3.3
        right_x = pdf.l_margin + left_w + gap

        map_h = 83.5
        legend_h = 8.5
        total_left_h = map_h + legend_h

        # 1. 좌측: 대형 와이드 지도 렌더링
        map_y = start_y
        try:
            map_png = self.map_renderer.render_png(snapshot, width=760, height=550)
            map_stream = io.BytesIO(map_png)
            pdf.image(map_stream, x=pdf.l_margin, y=map_y, w=left_w, h=map_h)
        except Exception:
            pdf.set_xy(pdf.l_margin, map_y)
            pdf.set_fill_color(*CARD_BG)
            pdf.set_draw_color(*LINE)
            pdf.rect(pdf.l_margin, map_y, left_w, map_h, style="DF")
            pdf.set_xy(pdf.l_margin, map_y + 35)
            pdf.set_font("Ko", "", 8)
            pdf.set_text_color(*MUTED)
            pdf.cell(left_w, 5, "지도 렌더링 준비 중", align="C")

        # 2. 좌측 하단: 지도 일체형 통합 범례 푸터
        legend_y = map_y + map_h
        pdf.set_xy(pdf.l_margin, legend_y)
        pdf.set_fill_color(241, 245, 249) # #F1F5F9 (지도와 일체화된 연한 그레이 배경)
        pdf.set_draw_color(*LINE)
        pdf.rect(pdf.l_margin, legend_y, left_w, legend_h, style="DF")

        # 범례 1행: 마커 등급별 행동 요령 안내
        row1_y = legend_y + 1.2
        pdf.set_xy(pdf.l_margin + 2.5, row1_y)
        
        # 🔴 상: 즉시점검
        pdf.set_fill_color(*GRADE_COLOR[RiskGrade.HIGH])
        pdf.ellipse(pdf.l_margin + 2.5, row1_y + 0.6, 2.6, 2.6, style="F")
        pdf.set_xy(pdf.l_margin + 5.8, row1_y)
        pdf.set_font("Ko", "B", 6.2)
        pdf.set_text_color(*GRADE_COLOR[RiskGrade.HIGH])
        pdf.cell(10, 3.2, "상(집중):")
        pdf.set_font("Ko", "", 6.0)
        pdf.set_text_color(*INK)
        pdf.cell(17, 3.2, "즉시현장조치 |")

        # 🟠 중: 사전예찰
        pdf.set_fill_color(*GRADE_COLOR[RiskGrade.MEDIUM])
        pdf.ellipse(pdf.l_margin + 34.0, row1_y + 0.6, 2.6, 2.6, style="F")
        pdf.set_xy(pdf.l_margin + 37.3, row1_y)
        pdf.set_font("Ko", "B", 6.2)
        pdf.set_text_color(*GRADE_COLOR[RiskGrade.MEDIUM])
        pdf.cell(10, 3.2, "중(주의):")
        pdf.set_font("Ko", "", 6.0)
        pdf.set_text_color(*INK)
        pdf.cell(17, 3.2, "사전예찰대기 |")

        # 🟡 하: 모니터링
        pdf.set_fill_color(*GRADE_COLOR[RiskGrade.LOW])
        pdf.ellipse(pdf.l_margin + 65.5, row1_y + 0.6, 2.6, 2.6, style="F")
        pdf.set_xy(pdf.l_margin + 68.8, row1_y)
        pdf.set_font("Ko", "B", 6.2)
        pdf.set_text_color(*GRADE_COLOR[RiskGrade.LOW])
        pdf.cell(10, 3.2, "하(관심):")
        pdf.set_font("Ko", "", 6.0)
        pdf.set_text_color(*INK)
        pdf.cell(15, 3.2, "상황모니터링")

        # 범례 2행: 기상특보 발효 구역 안내
        row2_y = legend_y + 4.8
        pdf.set_xy(pdf.l_margin + 2.5, row2_y)
        pdf.set_font("Ko", "B", 6.0)
        pdf.set_text_color(*NAVY)
        pdf.cell(14, 3.0, "■ 특보구역:")

        # 🟥 경보
        pdf.set_fill_color(*LEVEL_COLOR[WarningLevel.WARNING])
        pdf.rect(pdf.l_margin + 17.5, row2_y + 0.4, 2.4, 2.4, style="F")
        pdf.set_xy(pdf.l_margin + 20.8, row2_y)
        pdf.set_font("Ko", "", 5.8)
        pdf.set_text_color(*INK)
        pdf.cell(20, 3.0, "경보 (중대위험) |")

        # 🟧 주의보
        pdf.set_fill_color(*LEVEL_COLOR[WarningLevel.ADVISORY])
        pdf.rect(pdf.l_margin + 42.0, row2_y + 0.4, 2.4, 2.4, style="F")
        pdf.set_xy(pdf.l_margin + 45.3, row2_y)
        pdf.set_font("Ko", "", 5.8)
        pdf.set_text_color(*INK)
        pdf.cell(20, 3.0, "주의보 (주의위험)")

        # 3. 우측: 일체형 인포 패널 (TOP 4 + 핵심 안전관리 요령)
        # 3-1. 상단 카드: 중점 관리 대상 시설 (TOP 4)
        top_h = 44.0
        pdf.set_xy(right_x, start_y)
        pdf.set_fill_color(*CARD_BG)
        pdf.set_draw_color(*LINE)
        pdf.rect(right_x, start_y, right_w, top_h, style="DF")

        # 헤더 라벨
        pdf.set_xy(right_x + 3, start_y + 2.0)
        pdf.set_font("Ko", "B", 8.0)
        pdf.set_text_color(*NAVY)
        pdf.cell(right_w - 6, 4.0, "중점 관리 대상 시설 (TOP 4)")

        ranking = {RiskGrade.HIGH: 0, RiskGrade.MEDIUM: 1, RiskGrade.LOW: 2, RiskGrade.UNASSESSED: 3}
        priority_rows = sorted(
            (item for item in snapshot.assessments if item.grade in (RiskGrade.HIGH, RiskGrade.MEDIUM, RiskGrade.LOW)),
            key=lambda item: (ranking.get(item.grade, 9), item.facility.name),
        )[:4]

        if not priority_rows:
            pdf.set_xy(right_x, start_y + 18)
            pdf.set_font("Ko", "", 7.2)
            pdf.set_text_color(*MUTED)
            pdf.cell(right_w, 5, "현재 특보 영향 시설이 없습니다 (안전)", align="C")
        else:
            row_y = start_y + 6.8
            for idx, item in enumerate(priority_rows, 1):
                pdf.set_xy(right_x + 3, row_y)
                pdf.set_fill_color(*GRADE_COLOR[item.grade])
                pdf.set_text_color(*WHITE)
                pdf.set_font("Ko", "B", 6.5)
                grade_name = _grade_label(item.grade)
                pdf.cell(10, 4.2, f"{idx}.{grade_name}", fill=True, align="C")

                pdf.set_xy(right_x + 14, row_y)
                pdf.set_font("Ko", "B", 7.2)
                pdf.set_text_color(*INK)
                pdf.cell(32, 4.2, _short(item.facility.name, 11))

                warn_text = ", ".join(dict.fromkeys(f"{r.warning_type}" for r in item.reasons))
                pdf.set_xy(right_x + 46, row_y)
                pdf.set_font("Ko", "", 6.6)
                pdf.set_text_color(*MUTED)
                pdf.cell(right_w - 49, 4.2, _short(warn_text, 8), align="R")
                row_y += 5.2

        # 3-2. 하단 카드: 발효 특보별 핵심 안전관리 요령
        bot_y = start_y + top_h + 3.0
        bot_h = total_left_h - (top_h + 3.0)
        pdf.set_xy(right_x, bot_y)
        pdf.set_fill_color(*(240, 249, 255)) # 연한 아이스 블루
        pdf.set_draw_color(186, 230, 253)    # 하늘색 보더
        pdf.rect(right_x, bot_y, right_w, bot_h, style="DF")

        # 헤더 라벨
        pdf.set_xy(right_x + 3, bot_y + 2.0)
        pdf.set_font("Ko", "B", 8.0)
        pdf.set_text_color(*NAVY)
        pdf.cell(right_w - 6, 4.0, "발효 특보별 핵심 안전관리 요령")

        guidelines = extract_safety_guidelines(snapshot, max_items=3)
        g_y = bot_y + 6.8
        for w_type, g_text in guidelines:
            pdf.set_xy(right_x + 3, g_y)
            pdf.set_fill_color(*BLUE)
            pdf.set_text_color(*WHITE)
            pdf.set_font("Ko", "B", 6.4)
            pdf.cell(11.5, 3.8, f"[{w_type}]", fill=True, align="C")

            pdf.set_xy(right_x + 15.5, g_y)
            pdf.set_font("Ko", "", 6.8)
            pdf.set_text_color(*INK)
            pdf.multi_cell(right_w - 18, 3.6, g_text, wrapmode=WrapMode.CHAR)
            g_y = pdf.get_y() + 1.2

        pdf.set_y(start_y + total_left_h)

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
