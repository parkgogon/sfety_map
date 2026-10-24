from __future__ import annotations
from typing import Literal
from fastapi import Cookie, Header, Query, Response
from safety_dashboard.admin.session import AdminSessionManager
from safety_dashboard.monitoring.snapshot import (
    MONITORING_SNAPSHOT_SCHEMA_VERSION,
    dashboard_snapshot_to_document,
)

from fastapi import APIRouter
from safety_dashboard.api.dependencies import ApiServices
from safety_dashboard.api.authorization import _authorized_admin


def build_router(services: ApiServices) -> APIRouter:
    router = APIRouter()
    monitoring_service = services.monitoring_service
    session_manager = services.session_manager
    notification_admin = services.notification_admin

    @router.get("/api/v1/monitoring")
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

    @router.get("/internal/v1/monitoring/snapshot")
    def internal_monitoring_snapshot(
        response: Response,
        mode: Literal["live", "simulation"] = Query("live"),
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> dict[str, object]:
        """Streamlit 관제·PDF가 공개 지도와 같은 관제 결과를 읽는다."""

        response.headers["Cache-Control"] = "private, no-store"
        _authorized_admin(
            notification_admin(), x_alert_admin_token, cookie_session, session_manager
        )
        snapshot = monitoring_service.snapshot(simulation=mode == "simulation")
        return {
            "api_version": "v1",
            "snapshot_schema_version": MONITORING_SNAPSHOT_SCHEMA_VERSION,
            "snapshot": dashboard_snapshot_to_document(snapshot),
        }

    return router
