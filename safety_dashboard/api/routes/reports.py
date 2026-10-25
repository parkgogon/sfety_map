from __future__ import annotations
import datetime as dt
import logging
import hashlib
import json
import asyncio
from typing import Literal
from fastapi import Cookie, Header, HTTPException, Query, Response, Request
from starlette.concurrency import run_in_threadpool
from safety_dashboard.api.nearby_reports import NearbyReportBusy
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
    async def nearby_report_pdf(request: NearbyReportRequest, connection: Request) -> Response:
        """기상 조회나 전파 없이 시설 CSV로만 기준점 주변 보고서를 만듭니다."""
        try:
            facilities = await run_in_threadpool(CsvFacilityRepository(services.settings.facility_path).list_monitored)
            report = NearbyReport.build(GeoPoint(request.latitude, request.longitude),
                                        request.label, request.address, request.radius_km, facilities)
        except (FacilityDataError, ValueError):
            LOGGER.warning("nearby_report_facilities_unavailable")
            raise HTTPException(status_code=503, detail="시설 자료를 읽지 못해 보고서를 생성하지 못했습니다.") from None
        stop_watching = asyncio.Event()
        async def disconnected():
            while not stop_watching.is_set():
                if await connection.is_disconnected():
                    return
                await asyncio.sleep(.1)
        generation = asyncio.create_task(services.nearby_reports.generate(report))
        watcher = asyncio.create_task(disconnected())
        try:
            async with asyncio.timeout(40):
                completed, _ = await asyncio.wait({generation, watcher}, return_when=asyncio.FIRST_COMPLETED)
                if generation not in completed:
                    generation.cancel()
                    return Response(status_code=499)
                content, map_status = await generation
        except NearbyReportBusy:
            raise HTTPException(status_code=429, detail="보고서 생성이 몰리고 있습니다. 잠시 후 다시 시도해 주세요.",
                                headers={"Retry-After": "3"}) from None
        except TimeoutError:
            raise HTTPException(status_code=504, detail="보고서 생성 시간이 초과되었습니다. 다시 시도해 주세요.") from None
        except Exception as exc:
            LOGGER.error("nearby_report_generation_failed type=%s", type(exc).__name__)
            raise HTTPException(status_code=500, detail="주변 시설 보고서를 생성하지 못했습니다.") from None
        finally:
            # is_disconnected의 AnyIO CancelScope가 취소를 소비해도 다음 반복에서 끝낸다.
            stop_watching.set()
            watcher.cancel()
            if not generation.done():
                generation.cancel()
            await asyncio.gather(watcher, generation, return_exceptions=True)
        return Response(content=content, media_type="application/pdf", headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="nearby_facilities_{report.generated_at:%Y%m%d_%H%M%S}.pdf"',
            "X-Nearby-Facility-Count": str(len(report.facilities)),
            "X-Nearby-Map-Status": map_status,
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
