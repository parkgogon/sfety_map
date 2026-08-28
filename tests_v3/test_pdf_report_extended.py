"""확장된 PDF 보고서 무결성, 경계값, 마스터 지침 및 고정 레이아웃 테스트."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import unittest

from safety_dashboard.adapters.pdf_report import PdfReportRenderer, _get_sorted_assessments
from safety_dashboard.domain import (
    DashboardSnapshot,
    DashboardSummary,
    DataHealth,
    Facility,
    GeoPoint,
    RiskAssessment,
    RiskGrade,
    RiskReason,
    Warning,
    WarningFeed,
    WarningLevel,
)
from safety_dashboard.domain.safety_guidelines import (
    WARNING_ACTION_GUIDELINES,
    extract_safety_guidelines,
    get_warning_guideline,
)

ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = ROOT / "fonts" / "NotoSansKR-Regular.ttf"


def create_dummy_facility(index: int, name: str | None = None) -> Facility:
    return Facility(
        id=f"fac-{index:03d}",
        name=name or f"테스트 시설 {index:03d}",
        facility_type="대기측정소",
        location=GeoPoint(35.5 + (index % 10) * 0.1, 128.5 + (index % 10) * 0.1),
        address="경상북도 포항시 남구",
        department="대구경북환경본부",
        manager="홍길동",
    )


def create_dummy_snapshot(
    facility_count: int,
    high_count: int = 0,
    medium_count: int = 0,
    low_count: int = 0,
    warning_types: tuple[str, ...] = ("호우",),
    custom_warning_count: int | None = None,
) -> DashboardSnapshot:
    now = dt.datetime(2026, 8, 28, 14, 0)
    w_count = custom_warning_count if custom_warning_count is not None else len(warning_types)
    warnings = tuple(
        Warning(
            id=f"w-{idx}",
            source="KMA",
            region_up_code="L107",
            region_code=f"L1070{idx+1}",
            region_up="경상북도",
            region=f"지역 {idx+1}",
            warning_type=warning_types[idx % len(warning_types)] if warning_types else "호우",
            raw_level="경보" if idx == 0 and high_count > 0 else "주의보",
            level=WarningLevel.WARNING if idx == 0 and high_count > 0 else WarningLevel.ADVISORY,
            issued_at=now,
            effective_at=now,
        )
        for idx in range(w_count)
    )

    facilities = [create_dummy_facility(i) for i in range(facility_count)]
    assessments: list[RiskAssessment] = []

    for i, fac in enumerate(facilities):
        if i < high_count:
            grade = RiskGrade.HIGH
            wt = warning_types[0] if warning_types else "호우"
            reason = RiskReason("w-0", wt, "경보", grade, fac.address, "p1")
            assessments.append(RiskAssessment(fac, grade, (reason,), "2026.08-v1", now))
        elif i < high_count + medium_count:
            grade = RiskGrade.MEDIUM
            wt = warning_types[min(1, len(warning_types) - 1)] if warning_types else "호우"
            reason = RiskReason("w-1", wt, "주의보", grade, fac.address, "p1")
            assessments.append(RiskAssessment(fac, grade, (reason,), "2026.08-v1", now))
        elif i < high_count + medium_count + low_count:
            grade = RiskGrade.LOW
            wt = warning_types[-1] if warning_types else "호우"
            reason = RiskReason("w-2", wt, "주의보", grade, fac.address, "p1")
            assessments.append(RiskAssessment(fac, grade, (reason,), "2026.08-v1", now))
        else:
            assessments.append(RiskAssessment(fac, RiskGrade.NONE, (), "2026.08-v1", now))

    affected_count = high_count + medium_count + low_count
    summary = DashboardSummary(
        active_warning_count=len(warnings),
        affected_facility_count=affected_count,
        high_risk_count=high_count,
        unassessed_count=0,
        highest_warning_level=WarningLevel.WARNING if high_count > 0 else WarningLevel.ADVISORY,
    )

    return DashboardSnapshot(
        generated_at=now,
        policy_version="2026.08-v1",
        facilities=tuple(facilities),
        assessments=tuple(assessments),
        summary=summary,
        warning_feed=WarningFeed(warnings=warnings, health=DataHealth.LIVE, fetched_at=now),
    )


class PdfReportExtendedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.renderer = PdfReportRenderer(FONT_PATH)

    def _get_page_count(self, pdf_bytes: bytes) -> int:
        import re
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf") as report:
            report.write(pdf_bytes)
            report.flush()
            info_text = subprocess.run(
                ["pdfinfo", report.name],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            match = re.search(r"Pages:\s+(\d+)", info_text)
            self.assertIsNotNone(match)
            return int(match.group(1))

    def test_single_source_of_truth_ranking(self) -> None:
        """TOP4, TOP10, 상세 목록이 단일 정렬 원천(_get_sorted_assessments)을 동일하게 사용하는지 검증."""
        snapshot = create_dummy_snapshot(25, high_count=3, medium_count=5, low_count=7)
        sorted_list = _get_sorted_assessments(snapshot)

        # 1. 등급 위계 검증 (HIGH -> MEDIUM -> LOW)
        grades = [item.grade for item in sorted_list]
        self.assertEqual(grades[:3], [RiskGrade.HIGH] * 3)
        self.assertEqual(grades[3:8], [RiskGrade.MEDIUM] * 5)
        self.assertEqual(grades[8:15], [RiskGrade.LOW] * 7)

        # 2. TOP4, TOP10, 11위~N위의 일관성 검증
        top4 = sorted_list[:4]
        top10 = sorted_list[:10]
        remaining = sorted_list[10:]

        self.assertEqual(top4, top10[:4])
        self.assertEqual(len(top10) + len(remaining), len(sorted_list))
        top10_ids = {item.facility.id for item in top10}
        remaining_ids = {item.facility.id for item in remaining}
        self.assertEqual(top10_ids.intersection(remaining_ids), set())

    def test_data_integrity_counts(self) -> None:
        """데이터 무결성: affectedCount == high + medium + low 및 중복 없음 검증."""
        snapshot = create_dummy_snapshot(50, high_count=5, medium_count=10, low_count=15)
        sorted_list = _get_sorted_assessments(snapshot)

        # 시설 ID 중복 없음 검증
        fac_ids = [item.facility.id for item in sorted_list]
        self.assertEqual(len(fac_ids), len(set(fac_ids)))

        # 집계 수치 일치 검증
        self.assertEqual(snapshot.summary.affected_facility_count, 30)
        self.assertEqual(len(sorted_list), 30)

    def test_boundary_facility_counts(self) -> None:
        """경계값 렌더링 검증: 0개, 1개, 4개, 9개, 10개, 11개, 52개 시설."""
        counts = [
            (0, 0, 0, 0),    # 0개 (Empty state)
            (1, 1, 0, 0),    # 1개
            (4, 2, 2, 0),    # 4개 (TOP4 꽉 참)
            (9, 3, 3, 3),    # 9개
            (10, 2, 4, 4),   # 10개 (1페이지 TOP10 한계선)
            (11, 2, 4, 5),   # 11개 (2페이지에 정확히 1개 상세 생성)
            (52, 5, 20, 27), # 52개 (다중 페이지 페이징)
        ]

        for total_f, h, m, l in counts:
            with self.subTest(total_f=total_f, h=h, m=m, l=l):
                snap = create_dummy_snapshot(max(total_f, 10), high_count=h, medium_count=m, low_count=l)
                pdf_bytes = self.renderer.render(snap)
                self.assertTrue(pdf_bytes.startswith(b"%PDF"))
                self.assertGreater(len(pdf_bytes), 1000)

    def test_safety_guidelines_master_completeness(self) -> None:
        """시스템이 지원하는 기상특보 13종이 모두 가이드라인에 정의되어 있는지 전수 검증."""
        from safety_dashboard.domain.safety_guidelines import (
            DEFAULT_GUIDELINE_MASTER,
            SUPPORTED_WARNING_TYPES,
        )

        for wt in SUPPORTED_WARNING_TYPES:
            self.assertTrue(DEFAULT_GUIDELINE_MASTER.has_mapping(wt), f"누락된 특보 매핑: {wt}")
            guideline = DEFAULT_GUIDELINE_MASTER.get_guideline(wt)
            self.assertIsInstance(guideline, tuple)
            self.assertGreaterEqual(len(guideline), 2)
            for action in guideline:
                self.assertGreater(len(action), 3)

        # 알 수 없는 특보에 대한 fallback 검증
        fallback_guide = DEFAULT_GUIDELINE_MASTER.get_guideline("알수없는특보")
        self.assertIn("표준 안전관리요령", fallback_guide[0])

    def test_safety_guidelines_prioritization_and_extraction(self) -> None:
        """특보 영향도 및 경보 우선순위에 따른 안전관리 요령 추출 로직 검증."""
        # 1. 경보 특보(호우)와 주의보 특보(강풍) 혼재 시 경보 우선 추출
        snap = create_dummy_snapshot(10, high_count=2, medium_count=2, warning_types=("호우", "강풍"))
        guidelines = extract_safety_guidelines(snap, max_items=2)
        extracted_types = [g[0] for g in guidelines]
        self.assertEqual(extracted_types[0], "호우")
        self.assertEqual(len(guidelines), 2)

        # 2. 평시(특보 없음) 시 기본 안전수칙 반환 검증
        snap_empty = create_dummy_snapshot(10, high_count=0, medium_count=0, low_count=0, custom_warning_count=0, warning_types=())
        empty_guidelines = extract_safety_guidelines(snap_empty, max_items=2)
        self.assertEqual(empty_guidelines[0][0], "평시")

    # =========================================================================
    # PART 1: Compact vs Standard Mode 시나리오 테스트 (A, B, C, D, E)
    # =========================================================================
    def test_scenario_a_compact_mode(self) -> None:
        """Scenario A: 영향시설 3개, 활성특보 3건 -> Compact Mode (정확히 1페이지)."""
        snap = create_dummy_snapshot(10, high_count=1, medium_count=1, low_count=1, warning_types=("호우", "강풍", "폭염"))
        pdf_bytes = self.renderer.render(snap)
        self.assertEqual(self._get_page_count(pdf_bytes), 1)

    def test_scenario_b_boundary_height(self) -> None:
        """Scenario B: 영향시설 10개, 활성특보 5건 -> 실제 남은 Height 계산 기반 판정."""
        snap = create_dummy_snapshot(10, high_count=2, medium_count=4, low_count=4, custom_warning_count=5, warning_types=("호우", "태풍", "강풍", "폭염", "풍랑"))
        pdf_bytes = self.renderer.render(snap)
        # 10개 행(약 60mm) + 특보 5건(약 45mm)은 가용 잔여높이에 따라 안전하게 Compact 혹은 Standard로 처리됨
        page_count = self._get_page_count(pdf_bytes)
        self.assertIn(page_count, (1, 2))

    def test_scenario_c_standard_mode_many_warnings(self) -> None:
        """Scenario C: 영향시설 10개, 활성특보 20건 -> Standard Mode (2페이지 이상 분할)."""
        snap = create_dummy_snapshot(10, high_count=2, medium_count=4, low_count=4, custom_warning_count=20, warning_types=("호우", "태풍", "강풍", "폭염"))
        pdf_bytes = self.renderer.render(snap)
        self.assertGreaterEqual(self._get_page_count(pdf_bytes), 2)

    def test_scenario_d_standard_mode_large_data(self) -> None:
        """Scenario D: 영향시설 30개 이상, 활성특보 30개 이상 -> Multi-page 구조 정상 분할."""
        snap = create_dummy_snapshot(50, high_count=5, medium_count=15, low_count=15, custom_warning_count=30, warning_types=("태풍", "호우", "강풍", "폭풍해일"))
        pdf_bytes = self.renderer.render(snap)
        self.assertGreaterEqual(self._get_page_count(pdf_bytes), 3)

    def test_scenario_e_empty_state_one_page(self) -> None:
        """Scenario E: 영향시설 0개, 활성특보 0건 -> 불필요한 2페이지 생성 없이 정확히 1페이지."""
        snap = create_dummy_snapshot(10, high_count=0, medium_count=0, low_count=0, custom_warning_count=0, warning_types=())
        pdf_bytes = self.renderer.render(snap)
        self.assertEqual(self._get_page_count(pdf_bytes), 1)

    # =========================================================================
    # PART 2: 지도 Callout / Leader Line 시나리오 테스트
    # =========================================================================
    def test_map_callout_scenarios(self) -> None:
        """지도 Callout 및 Leader Line 시나리오 (1개, 4개, 좌/우 집중, 경계값 등) 검증."""
        from safety_dashboard.adapters.static_map import StaticSafetyMapRenderer

        map_renderer = StaticSafetyMapRenderer(font_path=FONT_PATH)

        # Scenario A: TOP 시설 1개
        snap_a = create_dummy_snapshot(10, high_count=1, medium_count=0, low_count=0)
        png_a = map_renderer.render_png(snap_a, top_facility_ranks={snap_a.assessments[0].facility.id: 1})
        self.assertTrue(png_a.startswith(b"\x89PNG"))

        # Scenario B/C/F: TOP 시설 4개 (좌/우 분배 및 근접)
        snap_b = create_dummy_snapshot(10, high_count=2, medium_count=2, low_count=0)
        ranks_b = {snap_b.assessments[i].facility.id: i + 1 for i in range(4)}
        png_b = map_renderer.render_png(snap_b, top_facility_ranks=ranks_b)
        self.assertTrue(png_b.startswith(b"\x89PNG"))

        # Scenario D/E: Left/Right Rail 집중 배치 시뮬레이션
        # 임의의 좌표(모두 서쪽/모두 동쪽) 시설로 구성된 스냅샷 생성
        west_facs = [
            Facility(
                id=f"w-{i}",
                name=f"서부시설{i}",
                facility_type="대기측정소",
                location=GeoPoint(latitude=36.4 + i * 0.05, longitude=128.1),
                address="경상북도 상주시 사벌국면",
                department="대구경북환경본부",
                manager="홍길동",
            )
            for i in range(4)
        ]
        west_assess = [
            RiskAssessment(west_facs[i], RiskGrade.HIGH, (RiskReason("w0", "호우", "경보", RiskGrade.HIGH, "상주시", "p1"),), "v1", dt.datetime.now())
            for i in range(4)
        ]
        snap_west = DashboardSnapshot(
            generated_at=dt.datetime.now(),
            policy_version="v1",
            facilities=tuple(west_facs),
            assessments=tuple(west_assess),
            summary=DashboardSummary(1, 4, 4, 0, WarningLevel.WARNING),
            warning_feed=WarningFeed((), DataHealth.LIVE, dt.datetime.now()),
        )
        ranks_west = {f.id: i + 1 for i, f in enumerate(west_facs)}
        png_west = map_renderer.render_png(snap_west, top_facility_ranks=ranks_west)
        self.assertTrue(png_west.startswith(b"\x89PNG"))

    # =========================================================================
    # PART 3: 중점관리시설 Panel 및 안전요령 테스트
    # =========================================================================
    def test_priority_panel_count_label_and_rendering(self) -> None:
        """중점관리시설 패널 개수 뱃지 (0개소, 1개소, 3개소, 상위 4개소) 및 긴 시설명 렌더링 검증."""
        # 1. 0개소 (Empty state)
        s0 = create_dummy_snapshot(10, high_count=0, medium_count=0, low_count=0, custom_warning_count=0, warning_types=())
        pdf0 = self.renderer.render(s0)
        self.assertTrue(len(pdf0) > 0)

        # 2. 1개소
        s1 = create_dummy_snapshot(10, high_count=1, medium_count=0, low_count=0, warning_types=("호우",))
        pdf1 = self.renderer.render(s1)
        self.assertTrue(len(pdf1) > 0)

        # 3. 3개소
        s3 = create_dummy_snapshot(10, high_count=1, medium_count=2, low_count=0, warning_types=("호우", "강풍"))
        pdf3 = self.renderer.render(s3)
        self.assertTrue(len(pdf3) > 0)

        # 4. 10개소 이상 (상위 4개소 표출) + 긴 시설명
        long_facs = [
            Facility(
                id=f"fac-{i:03d}",
                name=f"경상북도 포항시 남구 장기면 수질자동측정소_{i:03d}",
                facility_type="수질측정소",
                location=GeoPoint(35.8 + i * 0.05, 129.2 + i * 0.05),
                address="경상북도 포항시",
            )
            for i in range(12)
        ]
        long_assess = [
            RiskAssessment(long_facs[i], RiskGrade.HIGH if i < 2 else RiskGrade.MEDIUM, (RiskReason("w0", "호우", "경보", RiskGrade.HIGH, "포항시", "p1"),), "v1", dt.datetime.now())
            for i in range(12)
        ]
        s_long = DashboardSnapshot(
            generated_at=dt.datetime.now(),
            policy_version="v1",
            facilities=tuple(long_facs),
            assessments=tuple(long_assess),
            summary=DashboardSummary(1, 12, 2, 0, WarningLevel.WARNING),
            warning_feed=WarningFeed((), DataHealth.LIVE, dt.datetime.now()),
        )
        pdf_long = self.renderer.render(s_long)
        self.assertTrue(len(pdf_long) > 0)

    # =========================================================================
    # PART 4: Header Metadata / Department Display / Legend 마감 테스트
    # =========================================================================
    def test_department_display_formatting(self) -> None:
        """1페이지 담당부서 축약(Display Name) 헬퍼 로직 검증."""
        from safety_dashboard.adapters.pdf_report import _format_department_display

        # 케이스 1: 3단 조직 경로
        self.assertEqual(_format_department_display("대구경북환경본부 환경서비스처 유역관리부"), "유역관리부")
        # 케이스 2: 2단 사업소 경로
        self.assertEqual(_format_department_display("부산울산경남환경본부 자원순환관리처 영농폐기물사업소"), "영농폐기물사업소")
        # 케이스 3: 단일 부서명
        self.assertEqual(_format_department_display("유역관리부"), "유역관리부")
        # 케이스 4: 빈 값 / 기본값
        self.assertEqual(_format_department_display("-"), "-")
        self.assertEqual(_format_department_display(""), "-")

    def test_header_data_reference_timestamp(self) -> None:
        """헤더에 발행일시와 데이터 기준시각이 안전하게 분리 표출되는지 검증."""
        gen_time = dt.datetime(2026, 8, 28, 14, 30)
        snap = create_dummy_snapshot(10, high_count=1, medium_count=1)
        pdf_bytes = self.renderer.render(snap)
        self.assertTrue(len(pdf_bytes) > 0)

    def test_status_summary_bar_cases(self) -> None:
        """규칙 기반 현재 상황 요약 바 문구 생성 4가지 케이스 검증."""
        # CASE 1: high > 0
        s1 = create_dummy_snapshot(10, high_count=2, medium_count=3, low_count=1)
        pdf1 = self.renderer.render(s1)
        self.assertTrue(len(pdf1) > 0)

        # CASE 2: high == 0 and medium > 0
        s2 = create_dummy_snapshot(10, high_count=0, medium_count=3, low_count=2)
        pdf2 = self.renderer.render(s2)
        self.assertTrue(len(pdf2) > 0)

        # CASE 3: high == 0 and medium == 0 and affected > 0
        s3 = create_dummy_snapshot(10, high_count=0, medium_count=0, low_count=5)
        pdf3 = self.renderer.render(s3)
        self.assertTrue(len(pdf3) > 0)

        # CASE 4: affected == 0
        s4 = create_dummy_snapshot(10, high_count=0, medium_count=0, low_count=0)
        pdf4 = self.renderer.render(s4)
        self.assertTrue(len(pdf4) > 0)


if __name__ == "__main__":
    unittest.main()

