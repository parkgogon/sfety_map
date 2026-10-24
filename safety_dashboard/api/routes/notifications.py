from __future__ import annotations
import datetime as dt
from typing import Literal
from fastapi import Cookie, Header, HTTPException, Query, Response
from safety_dashboard.admin.session import AdminSessionManager
from safety_dashboard.adapters.firestore_alerts import KST
from safety_dashboard.alerts.admin import (
    AlertAdminAuthorizationError,
    AlertAdminConfigurationError,
    ManualDispatchDuplicateError,
    ManualDispatchValidationError,
)
from safety_dashboard.alerts.domain import ManualTelegramDispatch
from safety_dashboard.domain.models import OutgoingTelegramMessage

from fastapi import APIRouter
from safety_dashboard.api.dependencies import ApiServices
from safety_dashboard.api.authorization import _authorized_admin
from safety_dashboard.api.schemas import ManualTelegramDispatchRequest


def build_router(services: ApiServices) -> APIRouter:
    router = APIRouter()
    monitoring_service = services.monitoring_service
    session_manager = services.session_manager
    notification_admin = services.notification_admin

    @router.post("/api/v1/webhooks/solapi")
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

    @router.get("/internal/v1/notifications/status")
    def notification_status(
        response: Response,
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        service = _authorized_admin(
            notification_admin(), x_alert_admin_token, cookie_session, session_manager
        )
        return service.status()

    @router.get("/internal/v1/notifications/overview")
    def notification_overview(
        response: Response,
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        service = _authorized_admin(
            notification_admin(), x_alert_admin_token, cookie_session, session_manager
        )
        return service.overview()

    @router.get("/internal/v1/notifications/metrics")
    def notification_metrics(
        response: Response,
        start: dt.date = Query(alias="from"),
        end: dt.date = Query(alias="to"),
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        service = _authorized_admin(
            notification_admin(), x_alert_admin_token, cookie_session, session_manager
        )
        try:
            return service.metrics(start, end)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/internal/v1/notifications/events")
    def notification_events(
        response: Response,
        start: dt.date = Query(alias="from"),
        end: dt.date = Query(alias="to"),
        source: Literal["all", "automatic", "manual"] = Query("all"),
        status: str = Query("all"),
        limit: int = Query(100, ge=1, le=200),
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        service = _authorized_admin(
            notification_admin(), x_alert_admin_token, cookie_session, session_manager
        )
        start_at = dt.datetime.combine(start, dt.time.min, tzinfo=KST)
        end_at = dt.datetime.combine(
            end + dt.timedelta(days=1), dt.time.min, tzinfo=KST
        )
        try:
            events = service.events(
                start_at,
                end_at,
                source=source,
                status=status,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"events": events, "count": len(events)}

    @router.post("/internal/v1/notifications/manual")
    def notification_manual_dispatch(
        request: ManualTelegramDispatchRequest,
        response: Response,
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        service = _authorized_admin(
            notification_admin(), x_alert_admin_token, cookie_session, session_manager
        )
        now = dt.datetime.now(dt.timezone.utc)
        # 현재 관제 snapshot 기반 warning_keys 자동 보정

        effective_warning_keys = list(request.warning_keys)
        try:
            snapshot = monitoring_service.snapshot(
                simulation=request.mode == "simulation"
            )
            warnings_by_id = {
                item.id: f"{item.region_code}|{item.warning_type}"
                for item in snapshot.warning_feed.warnings
            }
            derived_keys: set[str] = set()
            for assessment in snapshot.assessments:
                if assessment.facility.id in request.facility_ids:
                    for reason in assessment.reasons:
                        if reason.warning_id in warnings_by_id:
                            derived_keys.add(warnings_by_id[reason.warning_id])
            if derived_keys:
                effective_warning_keys = sorted(derived_keys)
        except Exception:
            pass

        if not effective_warning_keys:
            effective_warning_keys = list(request.warning_keys) or ["MANUAL_SCOPE"]

        dispatch = ManualTelegramDispatch(
            id=request.request_id,
            created_at=now,
            category=request.category,
            operator_label="중앙관제 관리자",
            note=request.note,
            mode=request.mode,
            facility_ids=tuple(request.facility_ids),
            warning_keys=tuple(effective_warning_keys),
            messages=tuple(
                OutgoingTelegramMessage(
                    text=item.text,
                    silent=item.silent,
                    action_label=item.action_label,
                    action_url=item.action_url,
                )
                for item in request.messages
            ),
            policy_version=request.policy_version,
            temporary_policy=request.temporary_policy,
        )

        try:
            return service.dispatch_manual(
                dispatch,
                allow_duplicate=request.allow_duplicate,
            )
        except ManualDispatchDuplicateError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": str(exc),
                    "duplicate": exc.event.as_dict(),
                },
            ) from exc
        except ManualDispatchValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AlertAdminConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/internal/v1/notifications/export.csv")
    def notification_export(
        start: dt.date = Query(alias="from"),
        end: dt.date = Query(alias="to"),
        token: str = Query("", description="관리자 세션 토큰"),
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> Response:
        effective_token = x_alert_admin_token or token
        service = _authorized_admin(
            notification_admin(), effective_token, cookie_session, session_manager
        )

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

    return router
