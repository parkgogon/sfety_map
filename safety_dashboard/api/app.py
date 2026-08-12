"""FastAPI/Cloud Run 진입점."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.gzip import GZipMiddleware

from safety_dashboard.api.context_service import (
    FacilityContextService,
    FacilityNotFoundError,
)
from safety_dashboard.api.service import MonitoringApiService
from safety_dashboard.api.settings import ApiSettings
from safety_dashboard.api.weather_layer_service import WeatherLayerService
from safety_dashboard.adapters.firestore_alerts import FirestoreAlertStore
from safety_dashboard.alerts.admin import (
    AlertAdminAuthorizationError,
    AlertAdminConfigurationError,
    AlertAdminService,
)
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.domain.enums import WeatherLayerKind


LOGGER = logging.getLogger("safety_dashboard.api")


def create_app(
    service: MonitoringApiService | None = None,
    context_service: FacilityContextService | None = None,
    weather_layer_service: WeatherLayerService | None = None,
    alert_admin_service: AlertAdminService | None = None,
) -> FastAPI:
    settings = ApiSettings.from_environment()
    monitoring_service = service or MonitoringApiService(settings)
    facility_context = context_service or FacilityContextService(settings)
    weather_layers = weather_layer_service or WeatherLayerService(settings)
    alert_settings = AlertSettings.from_environment()
    alert_admin = alert_admin_service

    def notification_admin() -> AlertAdminService:
        nonlocal alert_admin
        if alert_admin is None:
            alert_admin = AlertAdminService(
                FirestoreAlertStore(alert_settings.project_id),
                alert_settings,
            )
        return alert_admin
    application = FastAPI(
        title="K-ECO Safety Monitoring API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
    )
    application.add_middleware(GZipMiddleware, minimum_size=1000)

    @application.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "api_version": "v1"}

    @application.get("/api/v1/monitoring")
    def monitoring(
        response: Response,
        refresh: bool = Query(False),
        mode: Literal["live", "simulation"] = Query("live"),
    ) -> dict:
        response.headers["Cache-Control"] = "private, no-store"
        return monitoring_service.monitoring(
            force_refresh=refresh,
            simulation=mode == "simulation",
        )

    @application.get("/api/v1/facilities/{facility_id}/weather")
    def facility_weather(facility_id: str, response: Response) -> dict:
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return facility_context.weather(facility_id)
        except FacilityNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="시설을 찾을 수 없습니다.",
            ) from exc

    @application.get("/api/v1/facilities/{facility_id}/cctv")
    def facility_cctv(facility_id: str, response: Response) -> dict:
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return facility_context.cctv(facility_id)
        except FacilityNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="시설을 찾을 수 없습니다.",
            ) from exc

    @application.get("/api/v1/weather/layers/{layer}")
    def weather_layer(
        layer: WeatherLayerKind,
        response: Response,
    ) -> dict:
        response.headers["Cache-Control"] = "private, no-store"
        return weather_layers.layer(layer)

    @application.post("/api/v1/webhooks/solapi")
    def solapi_webhook(
        events: list[dict],
        x_solapi_secret: str = Header("", alias="X-Solapi-Secret"),
    ) -> dict[str, object]:
        try:
            changed = notification_admin().apply_webhook(x_solapi_secret, events)
        except AlertAdminAuthorizationError as exc:
            raise HTTPException(status_code=403, detail="웹훅 인증 실패") from exc
        except AlertAdminConfigurationError as exc:
            raise HTTPException(status_code=503, detail="웹훅 연동 미설정") from exc
        return {"status": "ok", "updated": changed}

    @application.get("/internal/v1/notifications/status")
    def notification_status(
        response: Response,
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        service = _authorized_admin(notification_admin(), x_alert_admin_token)
        return service.status()

    @application.get("/internal/v1/notifications/metrics")
    def notification_metrics(
        response: Response,
        start: dt.date = Query(alias="from"),
        end: dt.date = Query(alias="to"),
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        service = _authorized_admin(notification_admin(), x_alert_admin_token)
        try:
            return service.metrics(start, end)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.get("/internal/v1/notifications/export.csv")
    def notification_export(
        start: dt.date = Query(alias="from"),
        end: dt.date = Query(alias="to"),
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
    ) -> Response:
        service = _authorized_admin(notification_admin(), x_alert_admin_token)
        try:
            content = service.export_csv(start, end)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": (
                    f'attachment; filename="automatic_alerts_{start}_{end}.csv"'
                ),
            },
        )

    @application.exception_handler(Exception)
    async def unhandled_error(_, error: Exception) -> JSONResponse:
        # 외부 응답에 내부 경로, API 키 또는 원본 예외 메시지를 노출하지 않는다.
        LOGGER.error(
            "api_request_failed",
            exc_info=(type(error), error, error.__traceback__),
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": "MONITORING_UNAVAILABLE",
                "detail": "관제 자료를 구성하지 못했습니다. 잠시 후 다시 확인해 주세요.",
            },
            headers={"Cache-Control": "private, no-store"},
        )

    return application


def _authorized_admin(
    service: AlertAdminService,
    token: str,
) -> AlertAdminService:
    try:
        service.authorize_admin(token)
    except AlertAdminAuthorizationError as exc:
        raise HTTPException(status_code=403, detail="관리자 인증 실패") from exc
    except AlertAdminConfigurationError as exc:
        raise HTTPException(status_code=503, detail="관리자 통계 연동 미설정") from exc
    return service


app = create_app()
