from __future__ import annotations
import logging
from fastapi import Cookie, Header, HTTPException, Request, Response
from safety_dashboard.admin.access import (
    AdminAccessConfigurationError,
    AdminAccessDeniedError,
    AdminAccessThrottledError,
)
from safety_dashboard.admin.session import AdminSessionManager

from fastapi import APIRouter
from safety_dashboard.api.dependencies import ApiServices
from safety_dashboard.api.schemas import AdminAccessRequest

LOGGER = logging.getLogger("safety_dashboard.api")


def build_router(services: ApiServices) -> APIRouter:
    router = APIRouter()
    admin_access = services.admin_access
    session_manager = services.session_manager

    @router.post("/internal/v1/admin/access")
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
            LOGGER.info(
                "admin_access_granted ip=%s expires_in=%s", client_ip, expires_in
            )
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

    @router.get("/internal/v1/admin/session")
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

    @router.post("/internal/v1/admin/logout")
    def admin_logout(response: Response, http_req: Request) -> dict[str, str]:
        response.headers["Cache-Control"] = "private, no-store"
        response.delete_cookie(key=AdminSessionManager.COOKIE_NAME, path="/")
        client_ip = http_req.client.host if http_req.client else "unknown"
        LOGGER.info("admin_logout ip=%s", client_ip)
        return {"status": "ok", "message": "logged_out"}

    return router
