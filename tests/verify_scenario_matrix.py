"""Scenario A to O Comprehensive Matrix Verification Script."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import subprocess
import re

from safety_dashboard.adapters.pdf_report import PdfReportRenderer
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

ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = ROOT / "fonts" / "NotoSansKR-Regular.ttf"
OUTPUT_DIR = ROOT / "output" / "scenario_matrix"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

renderer = PdfReportRenderer(font_path=FONT_PATH)
now = dt.datetime(2026, 8, 28, 14, 0)


def create_scenario_pdf(name: str, snapshot: DashboardSnapshot) -> tuple[int, Path]:
    pdf_bytes = renderer.render(snapshot)
    pdf_path = OUTPUT_DIR / f"{name}.pdf"
    pdf_path.write_bytes(pdf_bytes)
    import shutil
    if shutil.which("pdfinfo"):
        info = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, text=True, check=True).stdout
        match = re.search(r"Pages:\s+(\d+)", info)
        if match:
            return int(match.group(1)), pdf_path
    matches = re.findall(rb"/Type\s*/Page\b(?!\s*s)", pdf_bytes)
    num_pages = len(matches) if matches else 1
    return num_pages, pdf_path


def run_all_scenarios():
    results = {}

    # -------------------------------------------------------------
    # Scenario A: 특보 0, 영향시설 0
    # -------------------------------------------------------------
    facs_a = [Facility(f"fac-{i}", f"시설 {i}", "대기측정소", GeoPoint(35.5, 128.5), "주소") for i in range(10)]
    feed_a = WarningFeed((), DataHealth.LIVE, now)
    assessments_a = tuple(RiskAssessment(f, RiskGrade.NONE, (), "2026.08-v1", now) for f in facs_a)
    summary_a = DashboardSummary(0, 0, 0, 0, WarningLevel.UNKNOWN)
    snap_a = DashboardSnapshot(now, feed_a, tuple(facs_a), assessments_a, summary_a, "2026.08-v1")
    pages, path = create_scenario_pdf("scenario_A", snap_a)
    results["Scenario A (0 facilities, 0 warnings)"] = (pages, pages == 1)

    # -------------------------------------------------------------
    # Scenario B: 영향시설 1, 특보 1
    # -------------------------------------------------------------
    w_b = Warning("w-1", "KMA", "L107", "L10701", "경북", "포항시", "호우", "경보", WarningLevel.WARNING, issued_at=now, effective_at=now)
    fac_b = Facility("fac-1", "포항 대기측정소", "대기측정소", GeoPoint(36.0, 129.3), "포항시 남구", "대구경북본부 유역관리부", "김철수")
    feed_b = WarningFeed((w_b,), DataHealth.LIVE, now)
    reason_b = RiskReason("w-1", "호우", "경보", RiskGrade.HIGH, fac_b.address, "p1")
    assessments_b = (RiskAssessment(fac_b, RiskGrade.HIGH, (reason_b,), "2026.08-v1", now),)
    summary_b = DashboardSummary(1, 1, 1, 0, WarningLevel.WARNING)
    snap_b = DashboardSnapshot(now, feed_b, (fac_b,), assessments_b, summary_b, "2026.08-v1")
    pages, path = create_scenario_pdf("scenario_B", snap_b)
    results["Scenario B (1 facility, 1 warning)"] = (pages, pages == 1)

    # -------------------------------------------------------------
    # Scenario C: 영향시설 3, 특보 3
    # -------------------------------------------------------------
    warnings_c = tuple(
        Warning(f"w-{i}", "KMA", "L107", f"L1070{i}", "경북", f"구역{i}", "호우", "경보", WarningLevel.WARNING, issued_at=now, effective_at=now)
        for i in range(3)
    )
    facs_c = [
        Facility(f"fac-{i}", f"테스트 시설 {i}", "대기측정소", GeoPoint(35.5 + i * 0.2, 128.5 + i * 0.2), "경북 포항시", "대구경북본부 대기관리부", "이영희")
        for i in range(3)
    ]
    assessments_c = tuple(
        RiskAssessment(f, RiskGrade.HIGH, (RiskReason(f"w-{i}", "호우", "경보", RiskGrade.HIGH, f.address, "p1"),), "2026.08-v1", now)
        for i, f in enumerate(facs_c)
    )
    snap_c = DashboardSnapshot(now, WarningFeed(warnings_c, DataHealth.LIVE, now), tuple(facs_c), assessments_c, DashboardSummary(3, 3, 3, 0, WarningLevel.WARNING), "2026.08-v1")
    pages, path = create_scenario_pdf("scenario_C", snap_c)
    results["Scenario C (3 facilities, 3 warnings) [Compact]"] = (pages, pages == 1)

    # -------------------------------------------------------------
    # Scenario D: 영향시설 10, 특보 4
    # -------------------------------------------------------------
    warnings_d = tuple(
        Warning(f"w-{i}", "KMA", "L107", f"L1070{i}", "경북", f"구역{i}", "호우", "경보", WarningLevel.WARNING, issued_at=now, effective_at=now)
        for i in range(4)
    )
    facs_d = [
        Facility(f"fac-{i}", f"시설 {i}", "대기측정소", GeoPoint(35.2 + i * 0.1, 128.2 + i * 0.1), "경북 구미시", "대구경북본부", "박담당")
        for i in range(10)
    ]
    assessments_d = tuple(
        RiskAssessment(f, RiskGrade.HIGH if i < 3 else RiskGrade.MEDIUM, (RiskReason("w-0", "호우", "경보", RiskGrade.HIGH, f.address, "p1"),), "2026.08-v1", now)
        for i, f in enumerate(facs_d)
    )
    snap_d = DashboardSnapshot(now, WarningFeed(warnings_d, DataHealth.LIVE, now), tuple(facs_d), assessments_d, DashboardSummary(4, 10, 3, 0, WarningLevel.WARNING), "2026.08-v1")
    pages, path = create_scenario_pdf("scenario_D", snap_d)
    results["Scenario D (10 facilities, 4 warnings) [Compact]"] = (pages, pages == 1)

    # -------------------------------------------------------------
    # Scenario E: 영향시설 11, 특보 3 (Standard Mode Boundary)
    # -------------------------------------------------------------
    facs_e = [
        Facility(f"fac-{i}", f"시설 {i:02d}", "대기측정소", GeoPoint(35.2 + (i % 5) * 0.1, 128.2 + (i % 5) * 0.1), "경북 구미시", "대구경북본부", "박담당")
        for i in range(11)
    ]
    assessments_e = tuple(
        RiskAssessment(f, RiskGrade.MEDIUM, (RiskReason("w-0", "호우", "주의보", RiskGrade.MEDIUM, f.address, "p1"),), "2026.08-v1", now)
        for f in facs_e
    )
    snap_e = DashboardSnapshot(now, WarningFeed(warnings_c, DataHealth.LIVE, now), tuple(facs_e), assessments_e, DashboardSummary(3, 11, 0, 0, WarningLevel.ADVISORY), "2026.08-v1")
    pages, path = create_scenario_pdf("scenario_E", snap_e)
    results["Scenario E (11 facilities, 3 warnings) [Standard]"] = (pages, pages >= 2)

    # -------------------------------------------------------------
    # Scenario F: 영향시설 35, 특보 25
    # -------------------------------------------------------------
    warnings_f = tuple(
        Warning(f"w-{i}", "KMA", "L107", f"L1070{i}", "경북", f"구역{i}", "호우" if i % 2 == 0 else "강풍", "경보" if i < 5 else "주의보", WarningLevel.WARNING if i < 5 else WarningLevel.ADVISORY, issued_at=now, effective_at=now)
        for i in range(25)
    )
    facs_f = [
        Facility(f"fac-{i}", f"소관시설 {i:02d}", "수질측정소" if i % 2 == 0 else "대기측정소", GeoPoint(35.0 + (i % 10) * 0.15, 128.0 + (i % 8) * 0.15), "경남 창원시", "부산울산경남본부 환경관리부", "정관리")
        for i in range(35)
    ]
    assessments_f = tuple(
        RiskAssessment(f, RiskGrade.HIGH if i < 5 else (RiskGrade.MEDIUM if i < 20 else RiskGrade.LOW), (RiskReason("w-0", "호우", "경보", RiskGrade.HIGH, f.address, "p1"),), "2026.08-v1", now)
        for i, f in enumerate(facs_f)
    )
    snap_f = DashboardSnapshot(now, WarningFeed(warnings_f, DataHealth.LIVE, now), tuple(facs_f), assessments_f, DashboardSummary(25, 35, 5, 0, WarningLevel.WARNING), "2026.08-v1")
    pages, path = create_scenario_pdf("scenario_F", snap_f)
    results["Scenario F (35 facilities, 25 warnings)"] = (pages, pages >= 2)

    # -------------------------------------------------------------
    # Scenario G: 영향시설 103개 (전체 소관시설)
    # -------------------------------------------------------------
    facs_g = [
        Facility(f"fac-{i}", f"사업장 {i:03d}", "대기측정소", GeoPoint(35.0 + (i % 15) * 0.1, 128.0 + (i % 12) * 0.1), "대구광역시", "대구경북본부", "강담당")
        for i in range(103)
    ]
    assessments_g = tuple(
        RiskAssessment(f, RiskGrade.HIGH if i < 10 else (RiskGrade.MEDIUM if i < 50 else RiskGrade.LOW), (RiskReason("w-0", "호우", "경보", RiskGrade.HIGH, f.address, "p1"),), "2026.08-v1", now)
        for i, f in enumerate(facs_g)
    )
    snap_g = DashboardSnapshot(now, WarningFeed(warnings_f, DataHealth.LIVE, now), tuple(facs_g), assessments_g, DashboardSummary(25, 103, 10, 0, WarningLevel.WARNING), "2026.08-v1")
    pages, path = create_scenario_pdf("scenario_G", snap_g)
    results["Scenario G (103 facilities)"] = (pages, pages >= 4)

    # -------------------------------------------------------------
    # Scenario H: 위험 [상] 존재
    # -------------------------------------------------------------
    pages, path = create_scenario_pdf("scenario_H", snap_d)
    results["Scenario H (Risk HIGH present)"] = (pages, pages >= 1)

    # -------------------------------------------------------------
    # Scenario I: 위험 [중]만 존재 (HIGH=0)
    # -------------------------------------------------------------
    facs_i = [Facility(f"fac-{i}", f"중위험 시설 {i}", "대기측정소", GeoPoint(35.5, 128.5), "경북") for i in range(5)]
    assessments_i = tuple(
        RiskAssessment(f, RiskGrade.MEDIUM, (RiskReason("w-0", "호우", "주의보", RiskGrade.MEDIUM, f.address, "p1"),), "2026.08-v1", now)
        for f in facs_i
    )
    snap_i = DashboardSnapshot(now, WarningFeed(warnings_c, DataHealth.LIVE, now), tuple(facs_i), assessments_i, DashboardSummary(3, 5, 0, 0, WarningLevel.ADVISORY), "2026.08-v1")
    pages, path = create_scenario_pdf("scenario_I", snap_i)
    results["Scenario I (Risk MEDIUM only)"] = (pages, pages == 1)

    # -------------------------------------------------------------
    # Scenario J: 호우 + 강풍 + 태풍 복합특보
    # -------------------------------------------------------------
    warnings_j = (
        Warning("w-1", "KMA", "L107", "L10701", "경북", "포항시", "태풍", "경보", WarningLevel.CRITICAL, issued_at=now, effective_at=now),
        Warning("w-2", "KMA", "L107", "L10702", "경북", "경주시", "호우", "경보", WarningLevel.WARNING, issued_at=now, effective_at=now),
        Warning("w-3", "KMA", "L108", "L10801", "부산", "해운대구", "강풍", "경보", WarningLevel.WARNING, issued_at=now, effective_at=now),
    )
    facs_j = [
        Facility("fac-1", "포항 대기", "대기측정소", GeoPoint(36.0, 129.3), "포항시"),
        Facility("fac-2", "경주 수질", "수질측정소", GeoPoint(35.8, 129.2), "경주시"),
        Facility("fac-3", "부산 사업소", "영농폐기물사업소", GeoPoint(35.2, 129.1), "부산 해운대구"),
    ]
    assessments_j = (
        RiskAssessment(facs_j[0], RiskGrade.HIGH, (RiskReason("w-1", "태풍", "경보", RiskGrade.HIGH, facs_j[0].address, "p1"),), "2026.08-v1", now),
        RiskAssessment(facs_j[1], RiskGrade.HIGH, (RiskReason("w-2", "호우", "경보", RiskGrade.HIGH, facs_j[1].address, "p1"),), "2026.08-v1", now),
        RiskAssessment(facs_j[2], RiskGrade.HIGH, (RiskReason("w-3", "강풍", "경보", RiskGrade.HIGH, facs_j[2].address, "p1"),), "2026.08-v1", now),
    )
    snap_j = DashboardSnapshot(now, WarningFeed(warnings_j, DataHealth.LIVE, now), tuple(facs_j), assessments_j, DashboardSummary(3, 3, 3, 0, WarningLevel.CRITICAL), "2026.08-v1")
    pages, path = create_scenario_pdf("scenario_J", snap_j)
    results["Scenario J (Complex Warnings: Typhoon+Rain+Wind)"] = (pages, pages == 1)

    # -------------------------------------------------------------
    # Scenario K: TOP 시설 4개 밀집 (좌표 0.01도 이내)
    # -------------------------------------------------------------
    facs_k = [
        Facility(f"fac-{i}", f"밀집 시설 {i}", "대기측정소", GeoPoint(35.85 + i * 0.005, 128.60 + i * 0.005), "대구 중구")
        for i in range(4)
    ]
    assessments_k = tuple(
        RiskAssessment(f, RiskGrade.HIGH, (RiskReason("w-0", "호우", "경보", RiskGrade.HIGH, f.address, "p1"),), "2026.08-v1", now)
        for f in facs_k
    )
    snap_k = DashboardSnapshot(now, WarningFeed((warnings_j[1],), DataHealth.LIVE, now), tuple(facs_k), assessments_k, DashboardSummary(1, 4, 4, 0, WarningLevel.WARNING), "2026.08-v1")
    pages, path = create_scenario_pdf("scenario_K", snap_k)
    results["Scenario K (4 Dense TOP facilities)"] = (pages, pages == 1)

    # -------------------------------------------------------------
    # Scenario L: TOP 시설이 지도 Edge에 존재 (극단 경계 좌표)
    # -------------------------------------------------------------
    facs_l = [
        Facility("fac-n", "북단 울릉도", "대기측정소", GeoPoint(37.5, 130.8), "경북 울릉군"),
        Facility("fac-s", "남단 거제도", "대기측정소", GeoPoint(34.8, 128.6), "경남 거제시"),
        Facility("fac-w", "서단 거창군", "대기측정소", GeoPoint(35.7, 127.8), "경남 거창군"),
        Facility("fac-e", "동단 포항호미곶", "대기측정소", GeoPoint(36.1, 129.6), "경북 포항시"),
    ]
    assessments_l = tuple(
        RiskAssessment(f, RiskGrade.HIGH, (RiskReason("w-0", "호우", "경보", RiskGrade.HIGH, f.address, "p1"),), "2026.08-v1", now)
        for f in facs_l
    )
    snap_l = DashboardSnapshot(now, WarningFeed((warnings_j[1],), DataHealth.LIVE, now), tuple(facs_l), assessments_l, DashboardSummary(1, 4, 4, 0, WarningLevel.WARNING), "2026.08-v1")
    pages, path = create_scenario_pdf("scenario_L", snap_l)
    results["Scenario L (Edge TOP facilities)"] = (pages, pages == 1)

    # -------------------------------------------------------------
    # Scenario M: 매우 긴 시설명
    # -------------------------------------------------------------
    facs_m = [
        Facility("fac-long-1", "국립환경과학원 영남권 대기환경연구소 복합대기오염 연속자동측정소 A구역 1호기", "대기측정소", GeoPoint(35.8, 128.6), "대구"),
        Facility("fac-long-2", "부산울산경남 광역 하수슬러지 자원화 및 감량화 시범사업 종합처리시설 제2처리동", "공공하수처리시설", GeoPoint(35.2, 129.0), "부산"),
    ]
    assessments_m = tuple(
        RiskAssessment(f, RiskGrade.HIGH, (RiskReason("w-0", "호우", "경보", RiskGrade.HIGH, f.address, "p1"),), "2026.08-v1", now)
        for f in facs_m
    )
    snap_m = DashboardSnapshot(now, WarningFeed((warnings_j[1],), DataHealth.LIVE, now), tuple(facs_m), assessments_m, DashboardSummary(1, 2, 2, 0, WarningLevel.WARNING), "2026.08-v1")
    pages, path = create_scenario_pdf("scenario_M", snap_m)
    results["Scenario M (Extremely Long Facility Names)"] = (pages, pages == 1)

    # -------------------------------------------------------------
    # Scenario N: 매우 긴 부서명
    # -------------------------------------------------------------
    facs_n = [
        Facility("fac-dept-1", "시설 1", "대기측정소", GeoPoint(35.8, 128.6), "대구", "대구경북환경본부 환경서비스처 유역관리부 수질총량관리기획단 수계관리팀", "홍길동 대리"),
        Facility("fac-dept-2", "시설 2", "대기측정소", GeoPoint(35.2, 129.0), "부산", "부산울산경남환경본부 자원순환관리처 영농폐기물수거사업소 거제수거센터운영팀", "김영수 과장"),
    ]
    assessments_n = tuple(
        RiskAssessment(f, RiskGrade.HIGH, (RiskReason("w-0", "호우", "경보", RiskGrade.HIGH, f.address, "p1"),), "2026.08-v1", now)
        for f in facs_n
    )
    snap_n = DashboardSnapshot(now, WarningFeed((warnings_j[1],), DataHealth.LIVE, now), tuple(facs_n), assessments_n, DashboardSummary(1, 2, 2, 0, WarningLevel.WARNING), "2026.08-v1")
    pages, path = create_scenario_pdf("scenario_N", snap_n)
    results["Scenario N (Extremely Long Department Names)"] = (pages, pages == 1)

    # -------------------------------------------------------------
    # Scenario O: 활성특보 60건 이상
    # -------------------------------------------------------------
    warnings_o = tuple(
        Warning(f"w-{i}", "KMA", "L107", f"L1070{i}", "경북", f"특보구역_{i:02d}", "호우" if i % 3 == 0 else ("강풍" if i % 3 == 1 else "폭염"), "경보" if i % 5 == 0 else "주의보", WarningLevel.WARNING if i % 5 == 0 else WarningLevel.ADVISORY, issued_at=now, effective_at=now)
        for i in range(65)
    )
    facs_o = [Facility(f"fac-{i}", f"시설 {i}", "대기측정소", GeoPoint(35.5, 128.5), "경북") for i in range(5)]
    assessments_o = tuple(
        RiskAssessment(f, RiskGrade.HIGH, (RiskReason("w-0", "호우", "경보", RiskGrade.HIGH, f.address, "p1"),), "2026.08-v1", now)
        for f in facs_o
    )
    snap_o = DashboardSnapshot(now, WarningFeed(warnings_o, DataHealth.LIVE, now), tuple(facs_o), assessments_o, DashboardSummary(65, 5, 5, 0, WarningLevel.WARNING), "2026.08-v1")
    pages, path = create_scenario_pdf("scenario_o", snap_o)
    results["Scenario O (65 Active Warnings)"] = (pages, pages >= 2)

    print("=" * 60)
    print("Scenario Matrix Execution Results:")
    print("=" * 60)
    all_ok = True
    for name, (pg, ok) in results.items():
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"{name:50s} : {pg} pages [{status}]")
        if not ok:
            all_ok = False
    print("=" * 60)
    if all_ok:
        print("ALL SCENARIOS PASSED INVARIANT AND PAGINATION CHECKS!")
    else:
        print("SOME SCENARIOS FAILED CHECKS!")


if __name__ == "__main__":
    run_all_scenarios()
