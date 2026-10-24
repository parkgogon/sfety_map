from __future__ import annotations
from fastapi import Response

from fastapi import APIRouter
from safety_dashboard.api.dependencies import ApiServices


def build_router(services: ApiServices) -> APIRouter:
    router = APIRouter()
    operational_readiness = services.operational_readiness

    @router.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "api_version": "v1"}

    @router.get("/api/v1/health/operations")
    def operations_health(response: Response) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        result = operational_readiness().check()
        if not result.healthy:
            response.status_code = 503
        return result.as_dict()

    return router
