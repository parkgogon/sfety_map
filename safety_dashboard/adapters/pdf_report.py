"""동일한 관제 snapshot을 사용하는 A4 가로형 PDF 보고서."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import MethodReturnValue, WrapMode, XPos, YPos

from safety_dashboard.application.contacts import public_contact
from safety_dashboard.domain.enums import DataHealth, RiskGrade, WarningLevel
from safety_dashboard.domain.models import DashboardSnapshot


NAVY = (19, 42, 68)
TEAL = (17, 137, 137)
INK = (28, 43, 61)
MUTED = (91, 106, 123)
LINE = (208, 219, 229)
WHITE = (255, 255, 255)

GRADE_COLOR = {
    RiskGrade.HIGH: (211, 54, 48),
    RiskGrade.MEDIUM: (232, 137, 28),
    RiskGrade.LOW: (48, 135, 92),
    RiskGrade.UNASSESSED: (104, 117, 133),
    RiskGrade.NONE: (128, 142, 155),
}
GRADE_TINT = {
    RiskGrade.HIGH: (253, 239, 237),
    RiskGrade.MEDIUM: (254, 246, 232),
    RiskGrade.LOW: (237, 248, 242),
    RiskGrade.UNASSESSED: (242, 245, 248),
    RiskGrade.NONE: (246, 248, 250),
}
LEVEL_COLOR = {
    WarningLevel.CRITICAL: (177, 42, 38),
    WarningLevel.WARNING: (219, 91, 37),
    WarningLevel.ADVISORY: (224, 151, 26),
    WarningLevel.UNKNOWN: (104, 117, 133),
}


class PdfReportRenderer:
    def __init__(self, font_path: str | Path) -> None:
        self.font_path = Path(font_path)

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
            orientation="L",
            unit="mm",
            format="A4",
        )
        pdf.set_margins(12, 34, 12)
        # 자동 분할은 끄되 수동 분할 기준에 푸터 영역을 예약합니다.
        pdf.set_auto_page_break(False, margin=16)
        pdf.add_font("Ko", "", str(self.font_path))
        pdf.add_font("Ko", "B", str(self.font_path))
        pdf.alias_nb_pages()
        title = "기상재난 시설 영향 보고서"
        pdf.set_title(("[모의훈련] " if simulation else "") + title)
        pdf.add_page()

        self._section(pdf, "1", "관제 요약")
        self._summary_cards(pdf, snapshot)
        pdf.ln(4)

        self._section(pdf, "2", "영향시설 우선순위")
        self._assessment_table(pdf, snapshot)
        pdf.ln(4)

        self._ensure_space(pdf, 20)
        self._section(pdf, "3", "활성 특보")
        self._warning_table(pdf, snapshot)

        return bytes(pdf.output())

    @staticmethod
    def _section(pdf: FPDF, number: str, title: str, continued: bool = False) -> None:
        pdf.set_draw_color(*TEAL)
        pdf.set_line_width(0.8)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(2.2)
        pdf.set_font("Ko", "B", 11.5)
        pdf.set_text_color(*TEAL)
        pdf.cell(9, 7, number, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_text_color(*NAVY)
        suffix = " (계속)" if continued else ""
        pdf.cell(0, 7, title + suffix, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.5)

    @staticmethod
    def _table_header(
        pdf: FPDF,
        widths: tuple[int, ...],
        labels: tuple[str, ...],
    ) -> None:
        pdf.set_font("Ko", "B", 8)
        pdf.set_fill_color(*NAVY)
        pdf.set_draw_color(*WHITE)
        pdf.set_text_color(*WHITE)
        for width, label in zip(widths, labels):
            pdf.cell(width, 7, label, border=1, fill=True, align="C")
        pdf.ln()

    @staticmethod
    def _summary_cards(pdf: FPDF, snapshot: DashboardSnapshot) -> None:
        summary = snapshot.summary
        cards = (
            ("활성 특보", summary.active_warning_count, (236, 247, 248), TEAL),
            ("영향 시설", summary.affected_facility_count, (237, 243, 250), NAVY),
            ("상 위험", summary.high_risk_count, (253, 239, 237), GRADE_COLOR[RiskGrade.HIGH]),
            ("미판정", summary.unassessed_count, (242, 245, 248), GRADE_COLOR[RiskGrade.UNASSESSED]),
        )
        card_width = 64
        gap = 5
        start_y = pdf.get_y()
        for index, (label, value, fill, accent) in enumerate(cards):
            x = pdf.l_margin + index * (card_width + gap)
            pdf.set_xy(x, start_y)
            pdf.set_fill_color(*fill)
            pdf.set_draw_color(*LINE)
            pdf.rect(x, start_y, card_width, 19, style="DF")
            pdf.set_fill_color(*accent)
            pdf.rect(x, start_y, 2, 19, style="F")
            pdf.set_xy(x + 6, start_y + 3)
            pdf.set_font("Ko", "", 8)
            pdf.set_text_color(*MUTED)
            pdf.cell(card_width - 10, 5, label)
            pdf.set_xy(x + 6, start_y + 8.5)
            pdf.set_font("Ko", "B", 15)
            pdf.set_text_color(*NAVY)
            pdf.cell(card_width - 10, 7, str(value))
        pdf.set_y(start_y + 19)

    def _assessment_table(self, pdf: FPDF, snapshot: DashboardSnapshot) -> None:
        widths = (17, 49, 35, 68, 43, 58)
        labels = ("등급", "시설명", "구분", "주소", "해당 특보", "담당부서 · 담당자")
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

        for index, item in enumerate(rows):
            warnings = ", ".join(
                dict.fromkeys(f"{reason.warning_type} {reason.raw_level}" for reason in item.reasons)
            )
            values = (
                _grade_label(item.grade),
                item.facility.name,
                item.facility.facility_type,
                item.facility.address,
                warnings,
            )
            limits = (8, 23, 16, 34, 20)
            contact = public_contact(item.facility).replace(" · ", "\n", 1)
            pdf.set_font("Ko", "", 6.8)
            contact_lines = pdf.multi_cell(
                widths[-1] - 2,
                3.5,
                contact,
                dry_run=True,
                output=MethodReturnValue.LINES,
                wrapmode=WrapMode.CHAR,
            )
            row_height = max(7, len(contact_lines) * 3.5 + 1.6)
            if pdf.get_y() + row_height > pdf.page_break_trigger:
                pdf.add_page()
                self._section(pdf, "2", "영향시설 우선순위", continued=True)
                self._table_header(pdf, widths, labels)
            fill = GRADE_TINT[item.grade] if index % 2 == 0 else WHITE
            for column, (width, value, limit) in enumerate(
                zip(widths[:-1], values, limits)
            ):
                if column == 0:
                    pdf.set_fill_color(*GRADE_COLOR[item.grade])
                    pdf.set_text_color(*WHITE)
                    pdf.set_font("Ko", "B", 7.5)
                else:
                    pdf.set_fill_color(*fill)
                    pdf.set_text_color(*INK)
                    pdf.set_font("Ko", "", 7.3)
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
            pdf.set_font("Ko", "", 6.8)
            pdf.set_text_color(*INK)
            text_y = contact_y + (row_height - len(contact_lines) * 3.5) / 2
            for line in contact_lines:
                pdf.set_xy(contact_x + 1, text_y)
                pdf.cell(contact_width - 2, 3.5, line, align="C")
                text_y += 3.5
            pdf.set_xy(pdf.l_margin, contact_y + row_height)

    def _warning_table(self, pdf: FPDF, snapshot: DashboardSnapshot) -> None:
        widths = (48, 48, 42, 38, 47, 47)
        labels = ("광역", "구역", "특보", "단계", "발표", "발효")
        self._table_header(pdf, widths, labels)
        if not snapshot.warning_feed.warnings:
            self._empty_row(pdf, sum(widths), "현재 선택 시설에 연결된 활성 특보가 없습니다.")
            return

        for index, warning in enumerate(snapshot.warning_feed.warnings):
            if pdf.get_y() + 7 > pdf.page_break_trigger:
                pdf.add_page()
                self._section(pdf, "3", "활성 특보", continued=True)
                self._table_header(pdf, widths, labels)
            values = (
                warning.region_up,
                warning.region,
                warning.warning_type,
                warning.raw_level,
                _format_time(warning.issued_at),
                _format_time(warning.effective_at),
            )
            fill = (246, 249, 251) if index % 2 == 0 else WHITE
            for column, (width, value) in enumerate(zip(widths, values)):
                if column == 3:
                    pdf.set_fill_color(*LEVEL_COLOR[warning.level])
                    pdf.set_text_color(*WHITE)
                    pdf.set_font("Ko", "B", 7.5)
                else:
                    pdf.set_fill_color(*fill)
                    pdf.set_text_color(*INK)
                    pdf.set_font("Ko", "", 7.5)
                pdf.set_draw_color(*LINE)
                pdf.cell(width, 7, _short(value, 24), border=1, fill=True, align="C")
            pdf.ln()

    @staticmethod
    def _empty_row(pdf: FPDF, width: int, message: str) -> None:
        pdf.set_fill_color(246, 249, 251)
        pdf.set_draw_color(*LINE)
        pdf.set_text_color(*MUTED)
        pdf.set_font("Ko", "", 8)
        pdf.cell(width, 8, message, border=1, fill=True, align="C")
        pdf.ln()

    @staticmethod
    def _ensure_space(pdf: FPDF, height: float) -> None:
        if pdf.get_y() + height > pdf.page_break_trigger:
            pdf.add_page()


def _grade_label(grade: RiskGrade) -> str:
    return {
        RiskGrade.HIGH: "상",
        RiskGrade.MEDIUM: "중",
        RiskGrade.LOW: "하",
        RiskGrade.UNASSESSED: "미판정",
        RiskGrade.NONE: "없음",
    }[grade]


def _format_time(value: object) -> str:
    return value.strftime("%m-%d %H:%M") if hasattr(value, "strftime") else "-"


def _short(value: object, limit: int) -> str:
    text = str(value or "-")
    return text if len(text) <= limit else text[: limit - 1] + "…"


class _ReportPdf(FPDF):
    def __init__(
        self,
        *args,
        simulation: bool = False,
        temporary_policy: bool = False,
        generated_label: str,
        policy_version: str,
        scope_label: str,
        **kwargs,
    ) -> None:
        self.simulation = simulation
        self.temporary_policy = temporary_policy
        self.generated_label = generated_label
        self.policy_version = policy_version
        self.scope_label = scope_label
        super().__init__(*args, **kwargs)

    def header(self) -> None:
        self.set_fill_color(*NAVY)
        self.rect(0, 0, self.w, 29, style="F")
        self.set_fill_color(*TEAL)
        self.rect(0, 28, self.w, 1, style="F")
        self.set_xy(12, 6)
        self.set_font("Ko", "B", 15)
        self.set_text_color(*WHITE)
        self.cell(150, 7, "기상재난 시설 영향 보고서")
        self.set_xy(12, 15)
        self.set_font("Ko", "", 7.5)
        self.set_text_color(202, 216, 229)
        self.cell(
            205,
            5,
            f"관제 권역  대구·경북·부산·울산·경남  |  선택 범위  {_short(self.scope_label, 72)}",
        )
        badges: list[tuple[str, tuple[int, int, int]]] = [
            ("모의훈련" if self.simulation else "실시간", (197, 116, 25) if self.simulation else TEAL)
        ]
        if self.temporary_policy:
            badges.append(("임시정책", (190, 67, 61)))
        badge_width = 25
        total_width = len(badges) * badge_width + max(0, len(badges) - 1) * 3
        x = self.w - self.r_margin - total_width
        for label, color in badges:
            self.set_xy(x, 8)
            self.set_fill_color(*color)
            self.set_text_color(*WHITE)
            self.set_font("Ko", "B", 7.5)
            self.cell(badge_width, 7, label, fill=True, align="C")
            x += badge_width + 3
        self.set_y(34)

    def footer(self) -> None:
        self.set_y(-11)
        self.set_draw_color(*LINE)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(1)
        self.set_font("Ko", "", 6.8)
        self.set_text_color(*MUTED)
        temporary = " | 임시 위험도 기준" if self.temporary_policy else ""
        self.cell(
            215,
            5,
            f"생성 {self.generated_label} | 정책 {self.policy_version}{temporary} | 현장 판단을 대체하지 않습니다.",
        )
        self.cell(0, 5, f"{self.page_no()} / {{nb}}", align="R")
