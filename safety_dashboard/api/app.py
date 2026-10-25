"""Cloud Run 진입점과 API 조립. HTTP 처리는 업무별 라우터에 둔다."""

from __future__ import annotations
import logging
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from safety_dashboard.admin.access import AdminAccessVerifier
from safety_dashboard.api.context_service import FacilityContextService
from safety_dashboard.api.service import MonitoringApiService
from safety_dashboard.api.weather_layer_service import WeatherLayerService
from safety_dashboard.alerts.admin import AlertAdminService
from safety_dashboard.operations.readiness import OperationalReadinessService
from safety_dashboard.api.nearby_reports import NearbyReportGenerator

from safety_dashboard.api.dependencies import build_services
from safety_dashboard.api.schemas import (
    AdminAccessRequest,
    ManualTelegramDispatchRequest,
    ManualTelegramMessageRequest,
)
from safety_dashboard.api.routes import health as health_routes
from safety_dashboard.api.routes import admin as admin_routes
from safety_dashboard.api.routes import monitoring as monitoring_routes
from safety_dashboard.api.routes import context as context_routes
from safety_dashboard.api.routes import notifications as notifications_routes
from safety_dashboard.api.routes import reports as reports_routes
from safety_dashboard.api.routes import policy as policy_routes

LOGGER = logging.getLogger("safety_dashboard.api")

__all__ = [
    "app",
    "create_app",
    "AdminAccessRequest",
    "ManualTelegramDispatchRequest",
    "ManualTelegramMessageRequest",
]


def create_app(
    service: MonitoringApiService | None = None,
    context_service: FacilityContextService | None = None,
    weather_layer_service: WeatherLayerService | None = None,
    alert_admin_service: AlertAdminService | None = None,
    admin_access_service: AdminAccessVerifier | None = None,
    operational_readiness_service: OperationalReadinessService | None = None,
    nearby_report_generator: NearbyReportGenerator | None = None,
) -> FastAPI:
    services = build_services(
        service,
        context_service,
        weather_layer_service,
        alert_admin_service,
        admin_access_service,
        operational_readiness_service,
        nearby_report_generator,
    )
    application = FastAPI(
        title="K-ECO Safety Monitoring API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
    )
    application.add_middleware(GZipMiddleware, minimum_size=1000)

    application.include_router(health_routes.build_router(services))
    application.include_router(admin_routes.build_router(services))
    application.include_router(monitoring_routes.build_router(services))
    application.include_router(context_routes.build_router(services))
    application.include_router(notifications_routes.build_router(services))
    application.include_router(reports_routes.build_router(services))
    application.include_router(policy_routes.build_router(services))

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


app = create_app()
