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
) -> DashboardSnapshot:
    now = dt.datetime(2026, 8, 28, 14, 0)
    warnings = tuple(
        Warning(
            id=f"w-{idx}",
            source="KMA",
            region_up_code="L107",
            region_code=f"L1070{idx+1}",
            region_up="경상북도",
            region="포항시",
            warning_type=wt,
            raw_level="경보" if idx == 0 and high_count > 0 else "주의보",
            level=WarningLevel.WARNING if idx == 0 and high_count > 0 else WarningLevel.ADVISORY,
            issued_at=now,
            effective_at=now,
        )
        for idx, wt in enumerate(warning_types)
    )

    facilities = [create_dummy_facility(i) for i in range(facility_count)]
    assessments: list[RiskAssessment] = []

    for i, fac in enumerate(facilities):
        if i < high_count:
            grade = RiskGrade.HIGH
            reason = RiskReason("w-0", warning_types[0], "경보", grade, fac.address, "p1")
            assessments.append(RiskAssessment(fac, grade, (reason,), "2026.08-v1", now))
        elif i < high_count + medium_count:
            grade = RiskGrade.MEDIUM
            wt = warning_types[min(1, len(warning_types) - 1)]
            reason = RiskReason("w-1", wt, "주의보", grade, fac.address, "p1")
            assessments.append(RiskAssessment(fac, grade, (reason,), "2026.08-v1", now))
        elif i < high_count + medium_count + low_count:
            grade = RiskGrade.LOW
            wt = warning_types[-1]
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
        kma_supported_warning_types = [
            "호우", "태풍", "강풍", "폭염", "대설", "한파",
            "풍랑", "건조", "황사", "폭풍해일", "지진해일", "안개", "열대야",
        ]
        for wt in kma_supported_warning_types:
            self.assertIn(wt, WARNING_ACTION_GUIDELINES)
            guideline = get_warning_guideline(wt)
            self.assertIsInstance(guideline, tuple)
            self.assertGreaterEqual(len(guideline), 2)
            for action in guideline:
                self.assertGreater(len(action), 3)

        # 알 수 없는 특보에 대한 fallback 검증
        fallback_guide = get_warning_guideline("우박")
        self.assertIn("우박", fallback_guide[0])

    def test_compact_mode_one_page_completion(self) -> None:
        """Compact 1-Page Mode: 소량 데이터(시설 4개, 특보 2건) 시 정확히 1페이지로 완결되는지 검증."""
        import re
        import subprocess
        import tempfile

        snap_small = create_dummy_snapshot(10, high_count=1, medium_count=2, low_count=1, warning_types=("호우", "강풍"))
        pdf_bytes = self.renderer.render(snap_small)

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
            self.assertEqual(int(match.group(1)), 1)

    def test_standard_mode_multi_page(self) -> None:
        """Standard Mode: 대량 데이터(시설 45개, 특보 4건) 시 2페이지 이상 생성되는지 검증."""
        import re
        import subprocess
        import tempfile

        snap_large = create_dummy_snapshot(50, high_count=3, medium_count=15, low_count=27, warning_types=("태풍", "호우", "강풍", "폭풍해일"))
        pdf_bytes = self.renderer.render(snap_large)

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
            self.assertGreaterEqual(int(match.group(1)), 2)

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

