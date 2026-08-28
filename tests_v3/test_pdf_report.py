"""A4 세로형 PDF 보고서 및 정적 지도 렌더러 단위 테스트."""

import datetime as dt
import io
from pathlib import Path
import unittest
from PIL import Image

from safety_dashboard.adapters.pdf_report import PdfReportRenderer
from safety_dashboard.adapters.static_map import StaticSafetyMapRenderer
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
)

ROOT = Path(__file__).parents[1]
FONT_PATH = ROOT / "fonts/NotoSansKR.ttf"


def sample_snapshot() -> DashboardSnapshot:
    now = dt.datetime(2026, 8, 28, 14, 0)
    warnings = (
        Warning(
            "w-1", "KMA", "L107", "L10701", "경상북도", "포항시",
            "호우", "경보", WarningLevel.WARNING, issued_at=now, effective_at=now,
        ),
        Warning(
            "w-2", "KMA", "L107", "L10705", "경상북도", "구미시",
            "강풍", "주의보", WarningLevel.ADVISORY, issued_at=now, effective_at=now,
        ),
    )
    f1 = Facility("f-1", "포항 대기측정소", "대기측정소", GeoPoint(36.01, 129.35), "경북 포항시 남구", "대구경북환경본부", "담당1")
    f2 = Facility("f-2", "구미 수질측정소", "수질측정소", GeoPoint(36.12, 128.34), "경북 구미시 공단동", "대구경북환경본부", "담당2")
    f3 = Facility("f-3", "부산 영농사업소", "영농폐기물 수거사업소", GeoPoint(35.18, 129.07), "부산광역시 연제구", "부산울산경남환경본부", "담당3")

    a1 = RiskAssessment(
        f1, RiskGrade.HIGH,
        (RiskReason("w-1", "호우", "경보", RiskGrade.HIGH, "L10701", "호우:경보"),),
        "2026.08-v1", now,
    )
    a2 = RiskAssessment(
        f2, RiskGrade.MEDIUM,
        (RiskReason("w-2", "강풍", "주의보", RiskGrade.MEDIUM, "L10705", "강풍:주의보"),),
        "2026.08-v1", now,
    )
    a3 = RiskAssessment(f3, RiskGrade.NONE, (), "2026.08-v1", now)

    return DashboardSnapshot(
        generated_at=now,
        warning_feed=WarningFeed(warnings, DataHealth.LIVE, now),
        facilities=(f1, f2, f3),
        assessments=(a1, a2, a3),
        summary=DashboardSummary(2, 2, 1, 0, WarningLevel.WARNING),
        policy_version="2026.08-v1",
    )


class PdfReportTests(unittest.TestCase):
    def test_extract_safety_guidelines_returns_relevant_actions(self):
        snapshot = sample_snapshot()
        guidelines = extract_safety_guidelines(snapshot)
        self.assertGreaterEqual(len(guidelines), 1)
        w_types = [g[0] for g in guidelines]
        self.assertIn("호우", w_types)
        self.assertEqual(guidelines[0][1], WARNING_ACTION_GUIDELINES["호우"])

    def test_static_map_renderer_creates_valid_png(self):
        renderer = StaticSafetyMapRenderer()
        snapshot = sample_snapshot()
        png_bytes = renderer.render_png(snapshot, width=400, height=350)
        self.assertTrue(png_bytes.startswith(b"\x89PNG"))

        # Pillow로 파싱 가능한 유효한 이미지인지 검증
        img = Image.open(io.BytesIO(png_bytes))
        self.assertEqual(img.size, (400, 350))
        self.assertEqual(img.format, "PNG")

    def test_portrait_pdf_report_renders_successfully(self):
        renderer = PdfReportRenderer(FONT_PATH)
        snapshot = sample_snapshot()
        pdf_bytes = renderer.render(snapshot, scope_label="전체 소관시설")
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 5000)


if __name__ == "__main__":
    unittest.main()
