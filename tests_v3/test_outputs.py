import datetime as dt
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from safety_dashboard.adapters.pdf_report import PdfReportRenderer
from safety_dashboard.application.notifications import build_telegram_messages
from safety_dashboard.application.selection import action_snapshot
from safety_dashboard.domain import (
    DashboardSnapshot,
    DashboardSummary,
    DataHealth,
    Facility,
    GeoPoint,
    Warning,
    WarningFeed,
    WarningLevel,
)
from safety_dashboard.domain.risk_policy import RiskPolicy
from safety_dashboard.monitoring.snapshot import (
    dashboard_snapshot_from_document,
    dashboard_snapshot_to_document,
)


ROOT = Path(__file__).parents[1]
POLICY = RiskPolicy.load(ROOT / "safety_dashboard/config/risk_policy.toml")
FONT_PATH = ROOT / "fonts/NotoSansKR.ttf"


def selected_snapshot() -> DashboardSnapshot:
    now = dt.datetime(2026, 8, 4, 6, 0)
    warning = Warning(
        "warning-1",
        "기상청",
        "L107",
        "L10701",
        "경상북도",
        "포항시",
        "호우",
        "경보",
        WarningLevel.WARNING,
        issued_at=now,
        effective_at=now,
    )
    facility = Facility(
        "air",
        "선택한 대기 시설",
        "대기측정소",
        GeoPoint(36, 129),
        "경북 포항시",
        department="대구경북환경본부 환경서비스처 대기관리1부",
        manager="김담당 010-0000-0000",
    )
    assessment = POLICY.assess(facility, (warning,), now)
    return DashboardSnapshot(
        generated_at=now,
        warning_feed=WarningFeed((warning,), DataHealth.LIVE, now),
        facilities=(facility,),
        assessments=(assessment,),
        summary=DashboardSummary(1, 1, 1, 0, WarningLevel.WARNING),
        policy_version=POLICY.version,
    )


class OutputTests(unittest.TestCase):
    def test_temporary_policy_is_explicit_in_telegram(self):
        message = build_telegram_messages(
            selected_snapshot().assessments,
            temporary_policy=True,
        )[0]
        self.assertIn("임시 위험도 기준", message)

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext is required")
    def test_pdf_has_required_section_order_and_temporary_badge(self):
        source = selected_snapshot()
        excluded_facility = replace(
            source.facilities[0],
            id="excluded",
            name="제외되어야 할 시설",
        )
        excluded_assessment = POLICY.assess(
            excluded_facility,
            source.warning_feed.warnings,
            source.generated_at,
        )
        full_snapshot = replace(
            source,
            facilities=source.facilities + (excluded_facility,),
            assessments=source.assessments + (excluded_assessment,),
            summary=replace(source.summary, affected_facility_count=2, high_risk_count=2),
        )
        common_snapshot = dashboard_snapshot_from_document(
            dashboard_snapshot_to_document(full_snapshot)
        )
        selected = action_snapshot(common_snapshot, ("air",))
        data = PdfReportRenderer(FONT_PATH).render(
            selected,
            scope_label="대기측정소 / 상",
            temporary_policy=True,
        )
        self.assertTrue(data.startswith(b"%PDF"))
        with tempfile.NamedTemporaryFile(suffix=".pdf") as report:
            report.write(data)
            report.flush()
            text = subprocess.run(
                ["pdftotext", "-layout", report.name, "-"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        normalized = " ".join(text.split())
        self.assertLess(normalized.index("1 관제 요약"), normalized.index("2 영향시설 우선순위"))
        self.assertLess(normalized.index("2 영향시설 우선순위"), normalized.index("3 활성 특보"))
        self.assertIn("선택한 대기 시설", normalized)
        self.assertNotIn("제외되어야 할 시설", normalized)
        self.assertIn("임시정책", normalized)
        self.assertIn("대구경북환경본부 환경서비스처 대기관리1부", normalized)
        self.assertIn("김담당", normalized)
        self.assertNotIn("010-0000-0000", normalized)

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext is required")
    def test_pdf_repeats_priority_context_across_pages(self):
        source = selected_snapshot()
        assessments = tuple(
            POLICY.assess(
                replace(
                    source.facilities[0],
                    id=f"facility-{index}",
                    name=f"영향 시설 {index:02}",
                ),
                source.warning_feed.warnings,
                source.generated_at,
            )
            for index in range(52)
        )
        many = replace(
            source,
            facilities=tuple(item.facility for item in assessments),
            assessments=assessments,
            summary=replace(
                source.summary,
                affected_facility_count=len(assessments),
                high_risk_count=len(assessments),
            ),
        )
        data = PdfReportRenderer(FONT_PATH).render(many)
        with tempfile.NamedTemporaryFile(suffix=".pdf") as report:
            report.write(data)
            report.flush()
            text = subprocess.run(
                ["pdftotext", "-layout", report.name, "-"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        normalized = " ".join(text.split())
        self.assertIn("2 영향시설 우선순위 (계속)", normalized)
        self.assertGreaterEqual(normalized.count("기상재난 시설 영향 보고서"), 2)
        self.assertGreater(normalized.index("3 활성 특보"), normalized.index("영향 시설 51"))


if __name__ == "__main__":
    unittest.main()
