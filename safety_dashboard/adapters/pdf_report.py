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
from safety_dashboard.domain.models import DashboardSnapshot, RiskAssessment
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
    RiskGrade.NONE: (248, 250, 252),
}
LEVEL_COLOR = {
    WarningLevel.CRITICAL: (185, 28, 28),
    WarningLevel.WARNING: (217, 45, 32),
    WarningLevel.ADVISORY: (217, 119, 6),
    WarningLevel.UNKNOWN: (100, 116, 139),
}


def _get_sorted_assessments(snapshot: DashboardSnapshot) -> list[RiskAssessment]:
    """Single Source of Truth: 위험도 등급 > 특보 개수 > 시설명 순으로 정렬된 평가 목록을 반환합니다."""
    ranking = {
        RiskGrade.HIGH: 0,
        RiskGrade.MEDIUM: 1,
        RiskGrade.LOW: 2,
        RiskGrade.UNASSESSED: 3,
        RiskGrade.NONE: 4,
    }
    return sorted(
        [item for item in snapshot.assessments if item.grade is not RiskGrade.NONE],
        key=lambda item: (ranking.get(item.grade, 9), -len(item.reasons), item.facility.name),
    )


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
        if snapshot.warning_feed.health not in {
            DataHealth.LIVE,
            DataHealth.SIMULATION,
        }:
            raise ValueError(
                "KMA 실시간 또는 모의훈련 자료가 정상인 경우에만 "
                "PDF 보고서를 생성할 수 있습니다."
            )
        if not self.font_path.exists():
            raise ValueError(f"PDF 한글 폰트가 없습니다: {self.font_path}")

        simulation = snapshot.warning_feed.health is DataHealth.SIMULATION
        created_at = dt.datetime.now().astimezone()
        # 데이터 기준시각: KMA Feed 및 위험도 평가가 반영된 Snapshot 생성 시각 (Single Source of Truth)
        data_ref_time = snapshot.generated_at or snapshot.warning_feed.fetched_at or created_at
        data_ref_label = data_ref_time.strftime("%Y-%m-%d %H:%M")

        pdf = _ReportPdf(
            simulation=simulation,
            temporary_policy=temporary_policy,
            generated_label=created_at.strftime("%Y-%m-%d %H:%M"),
            data_ref_label=data_ref_label,
            policy_version=snapshot.policy_version,
            scope_label=scope_label,
            orientation="P",
            unit="mm",
            format="A4",
        )
        pdf.set_margins(12, 14, 12)
        pdf.set_auto_page_break(False, margin=14)

        # 폰트 등록
        pdf.add_font("Ko", "", str(self.regular_font_path))
        pdf.add_font("Ko", "B", str(self.bold_font_path))
        title = "기상재난 시설 영향 보고서"
        pdf.set_title(("[모의훈련] " if simulation else "") + title)
        pdf.add_page()
        pdf.alias_nb_pages()

        # 정렬된 영향시설 단일 진실 공급원 (Single Source of Truth)
        sorted_assessments = _get_sorted_assessments(snapshot)

        # =========================================================================
        # 1페이지: 지휘부용 종합 상황판 (Fixed Layout)
        # =========================================================================
        # 1. 관제 요약 (상황 요약 바 + KPI 카드 + 권역 지도/TOP4/안전요령)
        self._section(pdf, "1", "관제 요약")
        self._status_summary_bar(pdf, snapshot)
        pdf.ln(2.0)
        self._summary_cards(pdf, snapshot)
        pdf.ln(2.5)
        self._map_and_highlights(pdf, snapshot, sorted_assessments)
        pdf.ln(2.5)

        # 2. 1페이지 하단: 영향시설 점검 우선순위 TOP 10 (Flow Area 시작)
        self._section(pdf, "2", "영향시설 우선순위")
        self._assessment_table_top10(pdf, sorted_assessments)

        # =========================================================================
        # 모드 결정: Compact 1-Page Mode vs Standard Multi-Page Mode
        # =========================================================================
        has_more_facilities = len(sorted_assessments) > 10
        has_warnings = len(snapshot.warning_feed.warnings) > 0
        warning_count = len(snapshot.warning_feed.warnings)

        # Compact Mode 가드 상수 및 실제 가용 높이 계산
        COMPACT_MAX_AFFECTED = 10
        COMPACT_MAX_WARNINGS = 8
        SAFETY_MARGIN_MM = 3.0

        # 활성특보 섹션 예상 높이: 타이틀(6.0) + 요약바(6.5) + 테이블헤더(5.2) + 행당(4.8) + 여백(4.0)
        warning_section_height = 21.7 + (warning_count * 4.8)
        remaining_height = pdf.page_break_trigger - pdf.get_y() - SAFETY_MARGIN_MM

        # Compact 1-Page Mode 판정: 소량 데이터이고 1페이지 잔여 영역에 안전하게 수용 가능한 경우
        is_compact_mode = (
            not has_more_facilities
            and has_warnings
            and len(sorted_assessments) <= COMPACT_MAX_AFFECTED
            and warning_count <= COMPACT_MAX_WARNINGS
            and warning_section_height <= remaining_height
        )

        if is_compact_mode:
            # [COMPACT MODE] 1페이지 하단 Flow Area에 활성특보 섹션을 렌더링하고 총 1페이지로 완결
            pdf.ln(2.5)
            self._section(pdf, "3", "활성 특보")
            self._warning_summary_bar(pdf, snapshot)
            pdf.ln(1.5)
            self._warning_table(pdf, snapshot)
        else:
            # [STANDARD MODE] 대량 데이터 (1페이지 상황판 + 2페이지 이후 상세현황)
            if has_more_facilities:
                pdf.add_page()
                self._section(pdf, "2", "영향시설 우선순위", continued=True)
                self._assessment_table_remaining(pdf, sorted_assessments)
                pdf.ln(3.0)

            if has_warnings:
                if has_more_facilities:
                    self._ensure_space(pdf, 25)
                else:
                    pdf.add_page()
                self._section(pdf, "3", "활성 특보")
                self._warning_summary_bar(pdf, snapshot)
                pdf.ln(1.5)
                self._warning_table(pdf, snapshot)

        return bytes(pdf.output())

    @staticmethod
    def _section(pdf: FPDF, number: str, title: str, continued: bool = False) -> None:
        pdf.set_draw_color(*LINE)
        pdf.set_line_width(0.35)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(1.2)
        pdf.set_font("Ko", "B", 8.8)
        pdf.set_text_color(*NAVY)
        suffix = " (계속)" if continued else ""
        pdf.cell(0, 4.8, f"{number} {title}{suffix}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(0.8)

    @staticmethod
    def _status_summary_bar(pdf: FPDF, snapshot: DashboardSnapshot) -> None:
        """규칙 기반 현재 상황 1줄 요약 바를 렌더링합니다."""
        summary = snapshot.summary
        high_count = summary.high_risk_count
        medium_count = sum(1 for a in snapshot.assessments if a.grade is RiskGrade.MEDIUM)
        low_count = sum(1 for a in snapshot.assessments if a.grade is RiskGrade.LOW)
        affected_count = summary.affected_facility_count

        # 규칙 기반 조건부 문구 및 테마 색상 결정
        if high_count > 0:
            msg = f"즉시 현장조치 {high_count}개소 · 사전예찰 {medium_count}개소 · 상황모니터링 {low_count}개소"
            fill_col = (254, 242, 242)   # 연적색
            border_col = (252, 165, 165) # 적색 보더
            text_col = (185, 28, 28)     # 진한 적색
            badge_bg = (220, 38, 38)
        elif medium_count > 0:
            msg = f"긴급조치 대상 없음 · 사전예찰 {medium_count}개소 · 상황모니터링 {low_count}개소"
            fill_col = (255, 247, 237)   # 연주황
            border_col = (253, 186, 116) # 주황 보더
            text_col = (194, 65, 12)     # 진한 주황
            badge_bg = (234, 88, 12)
        elif affected_count > 0:
            msg = f"긴급조치·사전예찰 대상 없음 · 특보 영향 {affected_count}개소 상황모니터링"
            fill_col = (240, 249, 255)   # 연청색
            border_col = (186, 230, 253) # 청색 보더
            text_col = (3, 105, 161)     # 진한 청색
            badge_bg = (2, 132, 199)
        else:
            msg = "현재 기상특보 영향시설 없음 (전 소관시설 정상 운영 중)"
            fill_col = (248, 250, 252)   # 뉴트럴 그레이
            border_col = (226, 232, 240)
            text_col = (71, 85, 105)
            badge_bg = (100, 116, 139)

        x = pdf.l_margin
        y = pdf.get_y()
        w = pdf.w - 2 * pdf.l_margin
        h = 6.2

        pdf.set_fill_color(*fill_col)
        pdf.set_draw_color(*border_col)
        pdf.set_line_width(0.3)
        pdf.rect(x, y, w, h, style="DF")

        # 상태 뱃지 ([현재상황] 고정으로 문구 중복 방지)
        pdf.set_xy(x + 2.0, y + 1.1)
        pdf.set_fill_color(*badge_bg)
        pdf.set_text_color(*WHITE)
        pdf.set_font("Ko", "B", 6.2)
        pdf.cell(14.0, 4.0, "현재상황", fill=True, align="C")

        # 상황 요약 텍스트
        pdf.set_xy(x + 18.0, y + 1.1)
        pdf.set_text_color(*text_col)
        pdf.set_font("Ko", "B", 7.2)
        pdf.cell(w - 20.0, 4.0, msg)

        pdf.set_y(y + h)

    @staticmethod
    def _summary_cards(pdf: FPDF, snapshot: DashboardSnapshot) -> None:
        """1단: KPI 4개 카드를 조건부 강조(0개소 시 Neutral)하여 렌더링합니다."""
        summary = snapshot.summary
        high_count = summary.high_risk_count
        medium_count = sum(1 for a in snapshot.assessments if a.grade is RiskGrade.MEDIUM)
        affected_count = summary.affected_facility_count
        total_count = len(snapshot.facilities) if snapshot.facilities else 103
        is_partial = total_count < 103

        first_label = "보고 대상 시설" if is_partial else "소관시설 전체"
        first_sub = f"전체 103개소 중 선택" if is_partial else "영남권 소관 사업장"

        # 위험 [상], [중]이 0개일 때는 Neutral 톤으로 과도한 경계감 방지
        high_accent = GRADE_COLOR[RiskGrade.HIGH] if high_count > 0 else (148, 163, 184)
        high_tint = GRADE_TINT[RiskGrade.HIGH] if high_count > 0 else CARD_BG
        high_num_col = GRADE_COLOR[RiskGrade.HIGH] if high_count > 0 else (100, 116, 139)

        med_accent = GRADE_COLOR[RiskGrade.MEDIUM] if medium_count > 0 else (148, 163, 184)
        med_tint = GRADE_TINT[RiskGrade.MEDIUM] if medium_count > 0 else CARD_BG
        med_num_col = GRADE_COLOR[RiskGrade.MEDIUM] if medium_count > 0 else (100, 116, 139)

        cards = (
            (first_label, f"{total_count}개소", first_sub, CARD_BG, NAVY, NAVY),
            ("특보 영향시설", f"{affected_count}개소", "기상특보 발효 권역 내", (238, 246, 255), BLUE, BLUE),
            ("위험 [상] 집중", f"{high_count}개소", "경보 발효 등 긴급 점검", high_tint, high_accent, high_num_col),
            ("위험 [중] 주의", f"{medium_count}개소", "주의보 발효 등 사전 예찰", med_tint, med_accent, med_num_col),
        )
        card_width = 44.0
        gap = 3.3
        start_y = pdf.get_y()
        for index, (label, value, sub_text, fill, accent, num_color) in enumerate(cards):
            x = pdf.l_margin + index * (card_width + gap)
            pdf.set_xy(x, start_y)
            pdf.set_fill_color(*fill)
            pdf.set_draw_color(*LINE)
            pdf.set_line_width(0.3)
            pdf.rect(x, start_y, card_width, 15.5, style="DF")

            # 상단 컬러 바
            pdf.set_fill_color(*accent)
            pdf.rect(x, start_y, card_width, 2.2, style="F")

            pdf.set_xy(x + 3.0, start_y + 2.8)
            pdf.set_font("Ko", "B", 6.8)
            pdf.set_text_color(*MUTED)
            pdf.cell(card_width - 6, 3.5, label)

            pdf.set_xy(x + 3.0, start_y + 6.6)
            pdf.set_font("Ko", "B", 10.8)
            pdf.set_text_color(*num_color)
            pdf.cell(card_width - 6, 5.0, value)

            pdf.set_xy(x + 3.0, start_y + 11.6)
            pdf.set_font("Ko", "", 5.8)
            pdf.set_text_color(*MUTED)
            pdf.cell(card_width - 6, 3.0, sub_text)

        pdf.set_y(start_y + 16.0)

    def _map_and_highlights(
        self,
        pdf: FPDF,
        snapshot: DashboardSnapshot,
        sorted_assessments: list[RiskAssessment],
    ) -> None:
        """좌측: 대형 와이드 지도 + 일체형 통합 범례 푸터 / 우측: 일체형 인포 패널."""
        start_y = pdf.get_y()
        left_w = 116.0
        right_w = 66.7
        gap = 3.3
        right_x = pdf.l_margin + left_w + gap

        map_h = 76.0
        legend_h = 9.0
        total_left_h = map_h + legend_h

        # TOP 4 시설 순위 매핑 (Single Source of Truth)
        top4_rows = sorted_assessments[:4]
        top_ranks = {item.facility.id: rank for rank, item in enumerate(top4_rows, 1)}

        # 1. 좌측: 대형 와이드 지도 렌더링
        map_y = start_y
        try:
            map_png = self.map_renderer.render_png(
                snapshot,
                width=760,
                height=550,
                top_facility_ranks=top_ranks,
            )
            map_stream = io.BytesIO(map_png)
            pdf.image(map_stream, x=pdf.l_margin, y=map_y, w=left_w, h=map_h)
        except Exception:
            pdf.set_xy(pdf.l_margin, map_y)
            pdf.set_fill_color(*CARD_BG)
            pdf.set_draw_color(*LINE)
            pdf.rect(pdf.l_margin, map_y, left_w, map_h, style="DF")
            pdf.set_xy(pdf.l_margin, map_y + 32)
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
        # 🔴 상: 즉시점검
        pdf.set_fill_color(*GRADE_COLOR[RiskGrade.HIGH])
        pdf.ellipse(pdf.l_margin + 2.5, row1_y + 0.4, 2.4, 2.4, style="F")
        pdf.set_xy(pdf.l_margin + 5.5, row1_y)
        pdf.set_font("Ko", "B", 6.0)
        pdf.set_text_color(*GRADE_COLOR[RiskGrade.HIGH])
        pdf.cell(7.5, 3.0, "상:")
        pdf.set_font("Ko", "", 6.0)
        pdf.set_text_color(*INK)
        pdf.cell(17.5, 3.0, "즉시현장조치 |")

        # 🟠 중: 사전예찰
        pdf.set_fill_color(*GRADE_COLOR[RiskGrade.MEDIUM])
        pdf.ellipse(pdf.l_margin + 32.5, row1_y + 0.4, 2.4, 2.4, style="F")
        pdf.set_xy(pdf.l_margin + 35.5, row1_y)
        pdf.set_font("Ko", "B", 6.0)
        pdf.set_text_color(*GRADE_COLOR[RiskGrade.MEDIUM])
        pdf.cell(7.5, 3.0, "중:")
        pdf.set_font("Ko", "", 6.0)
        pdf.set_text_color(*INK)
        pdf.cell(17.5, 3.0, "사전예찰대기 |")

        # 🟡 하: 모니터링
        pdf.set_fill_color(*GRADE_COLOR[RiskGrade.LOW])
        pdf.ellipse(pdf.l_margin + 62.5, row1_y + 0.4, 2.4, 2.4, style="F")
        pdf.set_xy(pdf.l_margin + 65.5, row1_y)
        pdf.set_font("Ko", "B", 6.0)
        pdf.set_text_color(*GRADE_COLOR[RiskGrade.LOW])
        pdf.cell(7.5, 3.0, "하:")
        pdf.set_font("Ko", "", 6.0)
        pdf.set_text_color(*INK)
        pdf.cell(17.5, 3.0, "상황모니터링")

        # 범례 2행: 특보구역 범례
        row2_y = legend_y + 4.5
        pdf.set_xy(pdf.l_margin + 2.5, row2_y)
        pdf.set_font("Ko", "B", 5.8)
        pdf.set_text_color(*NAVY)
        pdf.cell(13.0, 3.0, "■ 특보구역:")

        # 경보 박스 + 텍스트
        pdf.set_fill_color(*LEVEL_COLOR[WarningLevel.WARNING])
        pdf.rect(pdf.l_margin + 16.5, row2_y + 0.5, 2.4, 2.4, style="F")
        pdf.set_xy(pdf.l_margin + 19.5, row2_y)
        pdf.set_font("Ko", "", 5.8)
        pdf.set_text_color(*INK)
        pdf.cell(8.0, 3.0, "경보")

        # 주의보 박스 + 텍스트
        pdf.set_fill_color(*LEVEL_COLOR[WarningLevel.ADVISORY])
        pdf.rect(pdf.l_margin + 28.5, row2_y + 0.5, 2.4, 2.4, style="F")
        pdf.set_xy(pdf.l_margin + 31.5, row2_y)
        pdf.set_font("Ko", "", 5.8)
        pdf.set_text_color(*INK)
        pdf.cell(9.0, 3.0, "주의보")

        # 범례 3행: 공식 고정 안내문 (특보 단계와 시설 위험등급 혼동 방지)
        row3_y = legend_y + 7.6
        pdf.set_xy(pdf.l_margin + 2.0, row3_y)
        pdf.set_font("Ko", "", 5.4)
        pdf.set_text_color(*MUTED)
        pdf.cell(
            left_w - 4.0,
            3.0,
            "※ 시설 위험등급은 기상특보 단계가 아닌 시설별 재난영향도 평가 결과임.",
        )

        # 3. 우측: 일체형 인포 패널 (중점 관리 대상 시설 + 핵심 안전관리 요령)
        top_h = 41.0
        pdf.set_xy(right_x, start_y)
        pdf.set_fill_color(*CARD_BG)
        pdf.set_draw_color(*LINE)
        pdf.rect(right_x, start_y, right_w, top_h, style="DF")

        # 3-1. 헤더 라벨 및 개소수 뱃지 (TOP4 내부 표현 제거)
        affected_count = len(sorted_assessments)
        if affected_count == 0:
            count_label = "0개소"
        elif affected_count <= 4:
            count_label = f"{affected_count}개소"
        else:
            count_label = "상위 4개소"

        pdf.set_xy(right_x + 3.0, start_y + 2.0)
        pdf.set_font("Ko", "B", 7.8)
        pdf.set_text_color(*NAVY)
        pdf.cell(42.0, 3.8, "중점 관리 대상 시설")

        pdf.set_xy(right_x + right_w - 24.0, start_y + 2.2)
        pdf.set_font("Ko", "B", 6.2)
        pdf.set_text_color(*MUTED)
        pdf.cell(21.0, 3.4, count_label, align="R")

        if not top4_rows:
            pdf.set_xy(right_x, start_y + 17.0)
            pdf.set_font("Ko", "", 7.0)
            pdf.set_text_color(*MUTED)
            pdf.cell(right_w, 4.5, "현재 중점 관리 대상 시설 없음", align="C")
        else:
            row_y = start_y + 6.5
            for rank_idx, item in enumerate(top4_rows, 1):
                # 순위 번호 뱃지 (지도 마커 번호와 완벽 1:1 연계)
                pdf.set_xy(right_x + 3.0, row_y)
                pdf.set_fill_color(*GRADE_COLOR[item.grade])
                pdf.set_text_color(*WHITE)
                pdf.set_font("Ko", "B", 6.2)
                grade_name = _grade_label(item.grade)
                pdf.cell(7.0, 4.0, f"{rank_idx}", fill=True, align="C")

                # 시설 위험등급 뱃지 (Risk Badge 계열)
                pdf.set_xy(right_x + 10.5, row_y)
                pdf.set_fill_color(*GRADE_TINT[item.grade])
                pdf.set_text_color(*GRADE_COLOR[item.grade])
                pdf.set_font("Ko", "B", 6.0)
                pdf.cell(6.5, 4.0, grade_name, fill=True, align="C")

                # 시설명 (최대 12자 안전 표출)
                pdf.set_xy(right_x + 17.5, row_y)
                pdf.set_font("Ko", "B", 6.8)
                pdf.set_text_color(*INK)
                pdf.cell(28.0, 4.0, _short(item.facility.name, 12))

                # 특보 단계 문구 (ex: 호우 · 경보, 폭염 · 주의보)
                def _format_warning_step(r: RiskReason) -> str:
                    lvl = r.raw_level
                    if "경보" in lvl:
                        lvl_clean = "경보"
                    elif "주의" in lvl:
                        lvl_clean = "주의보"
                    else:
                        lvl_clean = lvl
                    return f"{r.warning_type} · {lvl_clean}" if lvl_clean else r.warning_type

                warn_text = ", ".join(dict.fromkeys(_format_warning_step(r) for r in item.reasons))
                pdf.set_xy(right_x + 46.0, row_y)
                pdf.set_font("Ko", "", 5.8)
                pdf.set_text_color(*MUTED)
                pdf.cell(right_w - 49.0, 4.0, _short(warn_text, 8), align="R")
                row_y += 4.8

        # 3-2. 하단 카드: 발효 특보별 핵심 안전관리 요령 (Action Items 불릿 목록)
        bot_y = start_y + top_h + 2.5
        bot_h = total_left_h - (top_h + 2.5)
        pdf.set_xy(right_x, bot_y)
        pdf.set_fill_color(240, 249, 255) # 연한 아이스 블루
        pdf.set_draw_color(186, 230, 253) # 하늘색 보더
        pdf.rect(right_x, bot_y, right_w, bot_h, style="DF")

        # 헤더 라벨
        pdf.set_xy(right_x + 3.0, bot_y + 2.0)
        pdf.set_font("Ko", "B", 7.8)
        pdf.set_text_color(*NAVY)
        pdf.cell(right_w - 6.0, 3.8, "발효 특보별 핵심 안전관리 요령")

        guidelines = extract_safety_guidelines(snapshot, max_items=2)
        g_y = bot_y + 5.8
        for w_type, action_items in guidelines:
            pdf.set_xy(right_x + 3.0, g_y)
            pdf.set_fill_color(*BLUE)
            pdf.set_text_color(*WHITE)
            pdf.set_font("Ko", "B", 5.8)
            pdf.cell(11.0, 3.4, f"[{w_type}]", fill=True, align="C")

            item_y = g_y
            for action_text in action_items:
                pdf.set_xy(right_x + 15.0, item_y)
                pdf.set_font("Ko", "", 5.8)
                pdf.set_text_color(*INK)
                pdf.cell(right_w - 18.0, 3.2, f"• {action_text}")
                item_y += 3.3
            g_y = max(g_y + 4.0, item_y + 1.0)

        pdf.set_y(start_y + total_left_h)

    @staticmethod
    def _table_header(
        pdf: FPDF,
        widths: tuple[int, ...],
        labels: tuple[str, ...],
    ) -> None:
        pdf.set_font("Ko", "B", 7.2)
        pdf.set_fill_color(*NAVY)
        pdf.set_draw_color(*WHITE)
        pdf.set_text_color(*WHITE)
        for width, label in zip(widths, labels):
            pdf.cell(width, 5.2, label, border=1, fill=True, align="C")
        pdf.ln()

    def _assessment_table_top10(
        self,
        pdf: FPDF,
        sorted_assessments: list[RiskAssessment],
    ) -> None:
        """1페이지 하단: 영향시설 우선순위 상위 10개(TOP 10)를 고정 크기로 렌더링합니다."""
        widths = (8, 14, 40, 24, 42, 58)
        labels = ("순위", "등급", "시설명", "시설구분", "해당 기상특보", "담당부서 · 담당자")
        self._table_header(pdf, widths, labels)

        top10_rows = sorted_assessments[:10]
        if not top10_rows:
            self._empty_row(pdf, sum(widths), "현재 기상특보 영향시설 없음 (소관시설 정상)")
            return

        for index, item in enumerate(top10_rows, 1):
            self._render_assessment_row(pdf, index, item, widths, is_page1=True)

    def _assessment_table_remaining(
        self,
        pdf: FPDF,
        sorted_assessments: list[RiskAssessment],
    ) -> None:
        """2페이지 이후: 11위부터 N위까지의 잔여 영향시설 목록을 누락 없이 렌더링합니다."""
        widths = (8, 14, 40, 24, 42, 58)
        labels = ("순위", "등급", "시설명", "시설구분", "해당 기상특보", "담당부서 · 담당자")
        self._table_header(pdf, widths, labels)

        remaining_rows = sorted_assessments[10:]
        for index, item in enumerate(remaining_rows, 11):
            contact = public_contact(item.facility).replace(" · ", "\n", 1)
            pdf.set_font("Ko", "", 6.2)
            contact_lines = pdf.multi_cell(
                widths[-1] - 2,
                3.2,
                contact,
                dry_run=True,
                output=MethodReturnValue.LINES,
                wrapmode=WrapMode.CHAR,
            )
            row_height = max(5.2, len(contact_lines) * 3.2 + 1.0)
            if pdf.get_y() + row_height > pdf.page_break_trigger:
                pdf.add_page()
                self._section(pdf, "2", "영향시설 우선순위", continued=True)
                self._table_header(pdf, widths, labels)
            self._render_assessment_row(pdf, index, item, widths, is_page1=False)

    def _render_assessment_row(
        self,
        pdf: FPDF,
        index: int,
        item: RiskAssessment,
        widths: tuple[int, ...],
        is_page1: bool = False,
    ) -> None:
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

        # 1페이지에서는 Display Name(핵심 부서명)과 전화번호가 정제된 담당자를 사용하여 공간 최적화
        if is_page1:
            contact = _format_facility_contact_page1(item.facility)
        else:
            contact = public_contact(item.facility).replace(" · ", "\n", 1)

        pdf.set_font("Ko", "", 6.2)
        contact_lines = pdf.multi_cell(
            widths[-1] - 2,
            3.2,
            contact,
            dry_run=True,
            output=MethodReturnValue.LINES,
            wrapmode=WrapMode.CHAR,
        )
        row_height = max(5.2, len(contact_lines) * 3.2 + 1.0)
        fill = GRADE_TINT[item.grade] if index % 2 == 1 else WHITE

        for column, (width, value, limit) in enumerate(
            zip(widths[:-1], values, limits)
        ):
            if column == 1:
                pdf.set_fill_color(*GRADE_COLOR[item.grade])
                pdf.set_text_color(*WHITE)
                pdf.set_font("Ko", "B", 6.8)
            else:
                pdf.set_fill_color(*fill)
                pdf.set_text_color(*INK)
                pdf.set_font("Ko", "", 6.8)
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
        pdf.set_font("Ko", "", 6.2)
        pdf.set_text_color(*INK)
        text_y = contact_y + (row_height - len(contact_lines) * 3.2) / 2
        for line in contact_lines:
            pdf.set_xy(contact_x + 1, text_y)
            pdf.cell(contact_width - 2, 3.2, line, align="C")
            text_y += 3.2
        pdf.set_xy(pdf.l_margin, contact_y + row_height)

    @staticmethod
    def _warning_summary_bar(pdf: FPDF, snapshot: DashboardSnapshot) -> None:
        """활성특보 전체 집계 Summary Bar를 렌더링합니다."""
        warnings = snapshot.warning_feed.warnings
        total_w = len(warnings)
        if total_w == 0:
            return

        warn_count = sum(1 for w in warnings if w.level in (WarningLevel.WARNING, WarningLevel.CRITICAL))
        adv_count = sum(1 for w in warnings if w.level is WarningLevel.ADVISORY)

        # 특보 종류별 집계
        type_counts: dict[str, int] = {}
        for w in warnings:
            type_counts[w.warning_type] = type_counts.get(w.warning_type, 0) + 1

        # 상위 4개 종류 + 외 N종
        sorted_types = sorted(type_counts.items(), key=lambda x: -x[1])
        top_types = sorted_types[:4]
        type_parts = [f"{t} {c}건" for t, c in top_types]
        if len(sorted_types) > 4:
            rem_count = len(sorted_types) - 4
            type_parts.append(f"외 {rem_count}종")
        types_str = " · ".join(type_parts)

        summary_text = f"활성특보 총 {total_w}건 (경보 {warn_count}건 · 주의보 {adv_count}건)  |  특보별: {types_str}"

        x = pdf.l_margin
        y = pdf.get_y()
        w = pdf.w - 2 * pdf.l_margin
        h = 5.6

        pdf.set_fill_color(241, 245, 249) # 연한 그레이
        pdf.set_draw_color(*LINE)
        pdf.set_line_width(0.3)
        pdf.rect(x, y, w, h, style="DF")

        pdf.set_xy(x + 3.0, y + 1.0)
        pdf.set_font("Ko", "B", 6.8)
        pdf.set_text_color(*NAVY)
        pdf.cell(w - 6.0, 3.6, summary_text)

        pdf.set_y(y + h)

    def _warning_table(self, pdf: FPDF, snapshot: DashboardSnapshot) -> None:
        widths = (31, 31, 31, 27, 33, 33)
        labels = ("광역", "특보구역", "특보종류", "단계", "발표시각", "발효시각")
        self._table_header(pdf, widths, labels)
        if not snapshot.warning_feed.warnings:
            self._empty_row(pdf, sum(widths), "현재 발효 중인 기상특보가 없습니다.")
            return

        for index, warning in enumerate(snapshot.warning_feed.warnings):
            row_height = 5.0
            if pdf.get_y() + row_height > pdf.page_break_trigger:
                pdf.add_page()
                self._section(pdf, "2", "활성 특보 현황", continued=True)
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
                    pdf.set_font("Ko", "B", 6.6)
                else:
                    pdf.set_fill_color(*fill)
                    pdf.set_text_color(*INK)
                    pdf.set_font("Ko", "", 6.8)
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
        pdf.set_font("Ko", "", 7.2)
        pdf.set_fill_color(*CARD_BG)
        pdf.set_draw_color(*LINE)
        pdf.set_text_color(*MUTED)
        pdf.cell(width, 6.8, message, border=1, fill=True, align="C")
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
        data_ref_label: str,
        policy_version: str,
        scope_label: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.simulation = simulation
        self.temporary_policy = temporary_policy
        self.generated_label = generated_label
        self.data_ref_label = data_ref_label
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
        self.set_font("Ko", "B", 13.5)
        self.set_text_color(*NAVY)
        title = "K-ECO 기상재난 시설 영향 보고서"
        self.cell(100, 6, title, new_x=XPos.RIGHT, new_y=YPos.TOP)

        # 3. 모의훈련 / 임시정책 뱃지
        badge_x = self.get_x() + 2
        if self.simulation:
            self.set_xy(badge_x, 9.8)
            self.set_fill_color(217, 45, 32)
            self.set_text_color(*WHITE)
            self.set_font("Ko", "B", 6.8)
            self.cell(14, 4.2, "모의훈련", fill=True, align="C")
            badge_x += 16
        if self.temporary_policy:
            self.set_xy(badge_x, 9.8)
            self.set_fill_color(217, 119, 6)
            self.set_text_color(*WHITE)
            self.set_font("Ko", "B", 6.8)
            self.cell(14, 4.2, "임시정책", fill=True, align="C")

        # 4. 우측 메타 라인 (발행일시 및 데이터 기준시각 명확히 분리 표출)
        self.set_xy(self.w - self.r_margin - 90, 9.5)
        self.set_font("Ko", "", 6.5)
        self.set_text_color(*MUTED)
        self.cell(90, 5, f"발행: {self.generated_label}  |  데이터 기준: {self.data_ref_label}", align="R")

        # 5. 서브 메타 정보
        self.set_xy(self.l_margin, 15.2)
        self.set_font("Ko", "", 6.8)
        self.set_text_color(*MUTED)
        self.cell(
            self.w - 2 * self.l_margin,
            4,
            f"관제 범위: {self.scope_label}  |  위험도 정책 기준: {self.policy_version}",
        )
        self.ln(4.5)

    def footer(self) -> None:
        self.set_y(-9)
        self.set_draw_color(*LINE)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(1.2)
        self.set_font("Ko", "", 6.5)
        self.set_text_color(*MUTED)
        self.cell(
            self.w - 2 * self.l_margin,
            4,
            f"K-ECO 스마트 안전관제 시스템  |  페이지 {self.page_no()} / {{nb}}",
            align="C",
        )


def _format_facility_contact_page1(facility: Facility) -> str:
    """1페이지 영향시설 테이블용 담당부서 및 담당자 요약 문자열을 생성합니다."""
    from safety_dashboard.application.contacts import _clean_part, _MOBILE_PHONE

    raw_dept = _clean_part(facility.department)
    raw_mgr = _clean_part(_MOBILE_PHONE.sub("", str(facility.manager or "")))

    # 이미 Snapshot 직렬화 등으로 '부서명 · 담당자' 형태로 합쳐져 있는 경우 분리 처리
    if " · " in raw_dept:
        dept_part, _, mgr_part = raw_dept.partition(" · ")
        short_dept = _format_department_display(dept_part)
        mgr = raw_mgr if raw_mgr and raw_mgr != "-" else mgr_part
        parts = [p for p in (short_dept, mgr) if p and p != "-"]
        return " · ".join(parts) if parts else "-"

    short_dept = _format_department_display(raw_dept)
    parts = [p for p in (short_dept, raw_mgr) if p and p != "-"]
    return " · ".join(parts) if parts else "-"


def _format_department_display(department: str) -> str:
    """1페이지 테이블을 위해 조직 경로에서 핵심 부서 단위(Display Name)를 추출합니다."""
    if not department or department == "-":
        return "-"
    tokens = department.strip().split()
    if not tokens:
        return "-"
    # 마지막 어절이 '부', '팀', '과', '소', '실', '센터' 등으로 끝나면 해당 어절 반환
    last = tokens[-1]
    if any(last.endswith(suffix) for suffix in ("부", "팀", "과", "소", "실", "센터", "처", "본부")):
        return last
    return last


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
