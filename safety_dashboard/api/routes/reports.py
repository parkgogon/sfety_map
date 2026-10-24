from __future__ import annotations
import datetime as dt
import logging
from typing import Literal
from fastapi import Cookie, Header, HTTPException, Query, Response
from safety_dashboard.admin.session import AdminSessionManager
from safety_dashboard.adapters.firestore_alerts import KST
from safety_dashboard.domain.enums import DataHealth

from fastapi import APIRouter
from safety_dashboard.api.dependencies import ApiServices
from safety_dashboard.api.settings import ROOT

LOGGER = logging.getLogger("safety_dashboard.api")


def build_router(services: ApiServices) -> APIRouter:
    router = APIRouter()
    monitoring_service = services.monitoring_service

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
