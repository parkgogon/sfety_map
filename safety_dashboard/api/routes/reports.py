from __future__ import annotations
import datetime as dt
import logging
import hashlib
import json
from typing import Literal
from fastapi import Cookie, Header, HTTPException, Query, Response
from safety_dashboard.admin.session import AdminSessionManager
from safety_dashboard.adapters.firestore_alerts import KST
from safety_dashboard.domain.enums import DataHealth

from fastapi import APIRouter
from safety_dashboard.api.dependencies import ApiServices
from safety_dashboard.api.settings import ROOT
from safety_dashboard.api.schemas import NearbyReportRequest
from safety_dashboard.adapters.facility_csv import CsvFacilityRepository, FacilityDataError
from safety_dashboard.application.nearby_report import NearbyReport
from safety_dashboard.domain.models import GeoPoint

LOGGER = logging.getLogger("safety_dashboard.api")


def build_router(services: ApiServices) -> APIRouter:
    router = APIRouter()
    monitoring_service = services.monitoring_service

    @router.post("/api/v1/reports/nearby.pdf")
    def nearby_report_pdf(request: NearbyReportRequest) -> Response:
        """기상 조회나 전파 없이 시설 CSV로만 기준점 주변 보고서를 만듭니다."""
        try:
            facilities = CsvFacilityRepository(services.settings.facility_path).list_monitored()
            report = NearbyReport.build(GeoPoint(request.latitude, request.longitude),
                                        request.label, request.address, request.radius_km, facilities)
        except (FacilityDataError, ValueError):
            LOGGER.warning("nearby_report_facilities_unavailable")
            raise HTTPException(status_code=503, detail="시설 자료를 읽지 못해 보고서를 생성하지 못했습니다.") from None
        from safety_dashboard.adapters.nearby_pdf_report import NearbyPdfReportRenderer
        try:
            content = NearbyPdfReportRenderer(ROOT / "fonts" / "NotoSansKR.ttf").render(report)
        except Exception as exc:
            LOGGER.error("nearby_report_generation_failed type=%s", type(exc).__name__)
            raise HTTPException(status_code=500, detail="주변 시설 보고서를 생성하지 못했습니다.") from None
        return Response(content=content, media_type="application/pdf", headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="nearby_facilities_{report.generated_at:%Y%m%d_%H%M%S}.pdf"',
            "X-Nearby-Facility-Count": str(len(report.facilities)),
            "X-Nearby-Facility-Digest": hashlib.sha256(json.dumps(
                sorted(r.facility.id for r in report.facilities),
                ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8")).hexdigest(),
        })

    @router.get("/api/v1/monitoring/report.pdf")
    @router.get("/internal/v1/monitoring/report.pdf")
    def internal_monitoring_report_pdf(
        mode: Literal["live", "simulation"] = Query("live"),
        facility_ids: str = Query("", description="콤마로 구분된 시설 ID 목록"),
        scope_label: str = Query("전체 소관시설", max_length=100),
        token: str = Query("", description="관리자 세션 토큰 (선택)"),
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> Response:
        """관제 snapshot 기반 A4 세로형 PDF 현황보고서를 생성하여 다운로드합니다 (공개 접근 허용)."""
        snapshot = monitoring_service.snapshot(simulation=mode == "simulation")
        if snapshot.warning_feed.health not in {
            DataHealth.LIVE,
            DataHealth.SIMULATION,
        }:
            raise HTTPException(
                status_code=409,
                detail=(
                    "KMA 실시간 자료가 정상이 아닌 상태에서는 "
                    "새 PDF 보고서를 생성할 수 없습니다."
                ),
            )

        target_snapshot = snapshot
        if facility_ids.strip():
            selected_ids = [
                fid.strip() for fid in facility_ids.split(",") if fid.strip()
            ]
            if selected_ids:
                selected_set = frozenset(selected_ids)
                assessments = tuple(
                    item
                    for item in snapshot.assessments
                    if item.facility.id in selected_set
                )
                from safety_dashboard.application.selection import _subset_snapshot

                target_snapshot = _subset_snapshot(snapshot, assessments)

        from safety_dashboard.adapters.pdf_report import PdfReportRenderer

        font_path = ROOT / "fonts" / "NotoSansKR.ttf"
        try:
            renderer = PdfReportRenderer(font_path)
            pdf_bytes = renderer.render(target_snapshot, scope_label=scope_label)
        except Exception as exc:
            LOGGER.error("pdf_report_generation_failed", exc_info=True)
            raise HTTPException(
                status_code=500, detail="PDF 보고서를 생성하지 못했습니다."
            ) from exc

        now_str = dt.datetime.now(KST).strftime("%Y%m%d_%H%M%S")
        filename = f"safety_monitoring_report_{now_str}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    return router
