from __future__ import annotations
from typing import Literal
from fastapi import HTTPException, Query, Response
from safety_dashboard.api.context_service import FacilityNotFoundError
from safety_dashboard.domain.enums import WeatherLayerKind

from fastapi import APIRouter
from safety_dashboard.api.dependencies import ApiServices


def build_router(services: ApiServices) -> APIRouter:
    router = APIRouter()
    facility_context = services.facility_context
    weather_layers = services.weather_layers

    @router.get("/api/v1/facilities/{facility_id}/weather")
    def facility_weather(facility_id: str, response: Response) -> dict:
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return facility_context.weather(facility_id)
        except FacilityNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="시설을 찾을 수 없습니다.",
            ) from exc

    @router.get("/api/v1/facilities/{facility_id}/cctv")
    def facility_cctv(facility_id: str, response: Response) -> dict:
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return facility_context.cctv(facility_id)
        except FacilityNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="시설을 찾을 수 없습니다.",
            ) from exc

    @router.get("/api/v1/weather/layers/{layer}")
    def weather_layer(
        layer: WeatherLayerKind,
        response: Response,
        mode: Literal["live", "simulation"] = Query("live"),
    ) -> dict:
        response.headers["Cache-Control"] = "private, no-store"
        return weather_layers.layer(layer, mode=mode)

    return router
