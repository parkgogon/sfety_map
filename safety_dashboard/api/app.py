"""FastAPI/Cloud Run 진입점."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Literal

from fastapi import Cookie, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field

from safety_dashboard.admin.access import (
    AdminAccessConfigurationError,
    AdminAccessDeniedError,
    AdminAccessSettings,
    AdminAccessThrottledError,
    AdminAccessVerifier,
)
from safety_dashboard.admin.session import (
    AdminSession,
    AdminSessionError,
    AdminSessionExpiredError,
    AdminSessionManager,
)
from safety_dashboard.api.context_service import (
    FacilityContextService,
    FacilityNotFoundError,
)
from safety_dashboard.api.service import MonitoringApiService
from safety_dashboard.api.settings import ApiSettings
from safety_dashboard.api.weather_layer_service import WeatherLayerService
from safety_dashboard.adapters.firestore_alerts import FirestoreAlertStore, KST
from safety_dashboard.adapters.firestore_monitoring import (
    FirestoreMonitoringSnapshotStore,
)
from safety_dashboard.adapters.operational_health import HttpSystemHealthProbe
from safety_dashboard.adapters.telegram import TelegramNotifier
from safety_dashboard.alerts.admin import (
    AlertAdminAuthorizationError,
    AlertAdminConfigurationError,
    AlertAdminService,
    ManualDispatchDuplicateError,
    ManualDispatchValidationError,
)
from safety_dashboard.alerts.domain import (
    ManualTelegramCategory,
    ManualTelegramDispatch,
)
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.domain.enums import WeatherLayerKind
from safety_dashboard.domain.models import OutgoingTelegramMessage
from safety_dashboard.monitoring.snapshot import (
    MONITORING_SNAPSHOT_SCHEMA_VERSION,
    dashboard_snapshot_to_document,
)
from safety_dashboard.operations.readiness import OperationalReadinessService


LOGGER = logging.getLogger("safety_dashboard.api")


class ManualTelegramMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3900)
    silent: bool = True
    action_label: str = Field(default="", max_length=80)
    action_url: str = Field(default="", max_length=500)


class AdminAccessRequest(BaseModel):
    password: str


class ManualTelegramDispatchRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=80)
    category: ManualTelegramCategory
    mode: Literal["live", "simulation"]
    note: str = Field(default="", max_length=200)
    facility_ids: list[str] = Field(min_length=1, max_length=103)
    warning_keys: list[str] = Field(min_length=1, max_length=200)
    messages: list[ManualTelegramMessageRequest] = Field(min_length=1, max_length=30)
    policy_version: str = Field(default="", max_length=80)
    temporary_policy: bool = False
    allow_duplicate: bool = False


def create_app(
    service: MonitoringApiService | None = None,
    context_service: FacilityContextService | None = None,
    weather_layer_service: WeatherLayerService | None = None,
    alert_admin_service: AlertAdminService | None = None,
    admin_access_service: AdminAccessVerifier | None = None,
    operational_readiness_service: OperationalReadinessService | None = None,
) -> FastAPI:
    settings = ApiSettings.from_environment()
    alert_settings = AlertSettings.from_environment()
    monitoring_service = service or MonitoringApiService(
        settings,
        monitoring_snapshot_store_factory=lambda: (
            FirestoreMonitoringSnapshotStore(alert_settings.project_id)
        ),
    )
    facility_context = context_service or FacilityContextService(settings)
    weather_layers = weather_layer_service or WeatherLayerService(settings)
    alert_admin = alert_admin_service
    readiness = operational_readiness_service
    admin_access = admin_access_service or AdminAccessVerifier(
        AdminAccessSettings.from_environment()
    )
    session_manager = AdminSessionManager(
        secret_key=admin_access.settings.password or "keco-session-secret",
        default_lifetime_seconds=admin_access.settings.session_seconds,
    )

    def notification_admin() -> AlertAdminService:
        nonlocal alert_admin
        if alert_admin is None:
            user_telegram = (
                TelegramNotifier(
                    alert_settings.telegram_bot_token,
                    alert_settings.telegram_user_chat_id,
                )
                if alert_settings.telegram_bot_token
                and alert_settings.telegram_user_chat_id
                else None
            )
            admin_telegram = (
                TelegramNotifier(
                    alert_settings.telegram_bot_token,
                    alert_settings.telegram_admin_chat_id
                    or alert_settings.telegram_chat_id,
                )
                if alert_settings.telegram_bot_token
                and (
                    alert_settings.telegram_admin_chat_id
                    or alert_settings.telegram_chat_id
                )
                else None
            )
            alert_admin = AlertAdminService(
                FirestoreAlertStore(alert_settings.project_id),
                alert_settings,
                user_telegram=user_telegram,
                admin_telegram=admin_telegram,
                health_probe=HttpSystemHealthProbe(
                    alert_settings.dashboard_base_url,
                    user_telegram,
                ),
                manual_snapshot_provider=monitoring_service.snapshot,
            )
        return alert_admin

    def operational_readiness() -> OperationalReadinessService:
        nonlocal readiness
        if readiness is None:
            store = FirestoreAlertStore(alert_settings.project_id)
            readiness = OperationalReadinessService(store.notification_status)
        return readiness
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

    @application.get("/api/v1/health/operations")
    def operations_health(response: Response) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        result = operational_readiness().check()
        if not result.healthy:
            response.status_code = 503
        return result.as_dict()

    @application.post("/internal/v1/admin/access")
    def verify_admin_access(
        request: AdminAccessRequest,
        response: Response,
        http_req: Request,
    ) -> dict[str, object]:
        client_ip = http_req.client.host if http_req.client else "unknown"
        response.headers["Cache-Control"] = "private, no-store"
        if not request.password or len(request.password) > 256:
            LOGGER.warning("admin_access_rejected_empty ip=%s", client_ip)
            raise HTTPException(
                status_code=403,
                detail="관리자 인증에 실패했습니다.",
            )
        try:
            expires_in = admin_access.verify(request.password)
            session_token = session_manager.create_token(expires_in)
            response.set_cookie(
                key=AdminSessionManager.COOKIE_NAME,
                value=session_token,
                max_age=expires_in,
                httponly=True,
                samesite="lax",
                secure=False,
                path="/",
            )
            LOGGER.info("admin_access_granted ip=%s expires_in=%s", client_ip, expires_in)
            return {"status": "ok", "token": session_token, "expires_in": expires_in}
        except AdminAccessDeniedError as exc:
            LOGGER.warning("admin_access_denied ip=%s", client_ip)
            raise HTTPException(
                status_code=403,
                detail="관리자 인증에 실패했습니다.",
            ) from exc
        except AdminAccessThrottledError as exc:
            LOGGER.warning("admin_access_throttled ip=%s", client_ip)
            raise HTTPException(
                status_code=429,
                detail="인증 실패가 반복되어 잠시 후 다시 시도해 주세요.",
                headers={"Retry-After": "300"},
            ) from exc
        except AdminAccessConfigurationError as exc:
            LOGGER.error("admin_access_unconfigured ip=%s", client_ip)
            raise HTTPException(
                status_code=503,
                detail="관리자 잠금이 아직 설정되지 않았습니다.",
            ) from exc

    @application.get("/internal/v1/admin/session")
    def admin_session_status(
        http_req: Request,
        response: Response,
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        token_to_check = x_alert_admin_token or cookie_session
        if not token_to_check:
            return {"authenticated": False}
        try:
            session = session_manager.verify_token(token_to_check)
            return {
                "authenticated": True,
                "created_at": session.created_at,
                "expires_at": session.expires_at,
            }
        except Exception:
            return {"authenticated": False}

    @application.post("/internal/v1/admin/logout")
    def admin_logout(response: Response, http_req: Request) -> dict[str, str]:
        response.headers["Cache-Control"] = "private, no-store"
        response.delete_cookie(key=AdminSessionManager.COOKIE_NAME, path="/")
        client_ip = http_req.client.host if http_req.client else "unknown"
        LOGGER.info("admin_logout ip=%s", client_ip)
        return {"status": "ok", "message": "logged_out"}


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
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        service = _authorized_admin(notification_admin(), x_alert_admin_token, cookie_session, session_manager)
        return service.status()

    @application.get("/internal/v1/monitoring/snapshot")
    def internal_monitoring_snapshot(
        response: Response,
        mode: Literal["live", "simulation"] = Query("live"),
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> dict[str, object]:
        """Streamlit 관제·PDF가 공개 지도와 같은 관제 결과를 읽는다."""

        response.headers["Cache-Control"] = "private, no-store"
        _authorized_admin(notification_admin(), x_alert_admin_token, cookie_session, session_manager)
        snapshot = monitoring_service.snapshot(simulation=mode == "simulation")
        return {
            "api_version": "v1",
            "snapshot_schema_version": MONITORING_SNAPSHOT_SCHEMA_VERSION,
            "snapshot": dashboard_snapshot_to_document(snapshot),
        }

    @application.get("/internal/v1/monitoring/report.pdf")
    def internal_monitoring_report_pdf(
        mode: Literal["live", "simulation"] = Query("live"),
        facility_ids: str = Query("", description="콤마로 구분된 시설 ID 목록"),
        scope_label: str = Query("전체 소관시설", max_length=100),
        token: str = Query("", description="관리자 세션 토큰"),
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> Response:
        """관제 snapshot 기반 A4 가로형 PDF 초동보고서를 생성하여 다운로드합니다."""
        effective_token = x_alert_admin_token or token
        _authorized_admin(notification_admin(), effective_token, cookie_session, session_manager)
        snapshot = monitoring_service.snapshot(simulation=mode == "simulation")


        target_snapshot = snapshot
        if facility_ids.strip():
            selected_ids = [fid.strip() for fid in facility_ids.split(",") if fid.strip()]
            if selected_ids:
                selected_set = frozenset(selected_ids)
                assessments = tuple(
                    item for item in snapshot.assessments if item.facility.id in selected_set
                )
                from safety_dashboard.application.selection import _subset_snapshot
                target_snapshot = _subset_snapshot(snapshot, assessments)

        from pathlib import Path
        from safety_dashboard.adapters.pdf_report import PdfReportRenderer

        font_path = Path(__file__).resolve().parent.parent.parent / "fonts" / "NotoSansKR.ttf"
        try:
            renderer = PdfReportRenderer(font_path)
            pdf_bytes = renderer.render(target_snapshot, scope_label=scope_label)
        except Exception as exc:
            LOGGER.error("pdf_report_generation_failed", exc_info=True)
            raise HTTPException(status_code=500, detail="PDF 보고서를 생성하지 못했습니다.") from exc

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

    @application.get("/internal/v1/policy")
    def internal_policy(
        response: Response,
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> dict[str, object]:
        """기본 위험도 정책 및 특보별 매트릭스 정보를 반환합니다."""
        response.headers["Cache-Control"] = "private, no-store"
        _authorized_admin(notification_admin(), x_alert_admin_token, cookie_session, session_manager)

        from pathlib import Path
        from safety_dashboard.domain.risk_policy import RiskPolicy
        policy_path = Path(__file__).resolve().parent.parent / "config" / "risk_policy.toml"
        policy = RiskPolicy.load(policy_path)

        return {
            "version": policy.version,
            "description": policy.description,
            "default_grade": policy.default_grade.value,
            "grades": {
                grade.value: {
                    "rank": defn.rank,
                    "label": defn.label,
                    "meaning": defn.meaning,
                    "action": defn.action,
                    "color": defn.color,
                }
                for grade, defn in policy.grades.items()
            },
            "warning_types": {
                warning_type: {
                    level.value: grade.value
                    for level, grade in levels.items()
                }
                for warning_type, levels in policy.warning_matrix.items()
            },
        }

    @application.get("/internal/v1/notifications/overview")
    def notification_overview(
        response: Response,
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        service = _authorized_admin(notification_admin(), x_alert_admin_token, cookie_session, session_manager)
        return service.overview()

    @application.get("/internal/v1/notifications/metrics")
    def notification_metrics(
        response: Response,
        start: dt.date = Query(alias="from"),
        end: dt.date = Query(alias="to"),
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        service = _authorized_admin(notification_admin(), x_alert_admin_token, cookie_session, session_manager)
        try:
            return service.metrics(start, end)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.get("/internal/v1/notifications/events")
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
        service = _authorized_admin(notification_admin(), x_alert_admin_token, cookie_session, session_manager)
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

    @application.post("/internal/v1/notifications/manual")
    def notification_manual_dispatch(
        request: ManualTelegramDispatchRequest,
        response: Response,
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        service = _authorized_admin(notification_admin(), x_alert_admin_token, cookie_session, session_manager)
        now = dt.datetime.now(dt.timezone.utc)
        dispatch = ManualTelegramDispatch(
            id=request.request_id,
            created_at=now,
            category=request.category,
            operator_label="중앙관제 관리자",
            note=request.note,
            mode=request.mode,
            facility_ids=tuple(request.facility_ids),
            warning_keys=tuple(request.warning_keys),
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

    @application.get("/internal/v1/notifications/export.csv")
    def notification_export(
        start: dt.date = Query(alias="from"),
        end: dt.date = Query(alias="to"),
        token: str = Query("", description="관리자 세션 토큰"),
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> Response:
        effective_token = x_alert_admin_token or token
        service = _authorized_admin(notification_admin(), effective_token, cookie_session, session_manager)

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
    token: str = "",
    cookie_session: str = "",
    session_manager: AdminSessionManager | None = None,
) -> AlertAdminService:
    if token:
        try:
            service.authorize_admin(token)
            return service
        except AlertAdminAuthorizationError:
            if session_manager:
                try:
                    session_manager.verify_token(token)
                    return service
                except Exception:
                    pass
            raise HTTPException(status_code=403, detail="관리자 인증 실패")
        except AlertAdminConfigurationError as exc:
            raise HTTPException(status_code=503, detail="관리자 통계 연동 미설정") from exc

    if cookie_session and session_manager:
        try:
            session_manager.verify_token(cookie_session)
            return service
        except Exception:
            raise HTTPException(status_code=403, detail="관리자 세션이 만료되었거나 올바르지 않습니다.")

    raise HTTPException(status_code=403, detail="관리자 인증이 필요합니다.")


app = create_app()

