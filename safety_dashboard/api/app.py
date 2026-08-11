"""FastAPI/Cloud Run 진입점."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.gzip import GZipMiddleware

from safety_dashboard.api.context_service import (
    FacilityContextService,
    FacilityNotFoundError,
)
from safety_dashboard.api.service import MonitoringApiService
from safety_dashboard.api.settings import ApiSettings
from safety_dashboard.api.weather_layer_service import WeatherLayerService
from safety_dashboard.domain.enums import WeatherLayerKind


LOGGER = logging.getLogger("safety_dashboard.api")


def create_app(
    service: MonitoringApiService | None = None,
    context_service: FacilityContextService | None = None,
    weather_layer_service: WeatherLayerService | None = None,
) -> FastAPI:
    settings = ApiSettings.from_environment()
    monitoring_service = service or MonitoringApiService(settings)
    facility_context = context_service or FacilityContextService(settings)
    weather_layers = weather_layer_service or WeatherLayerService(settings)
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
