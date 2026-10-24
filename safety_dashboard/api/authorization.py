from __future__ import annotations
from fastapi import HTTPException
from safety_dashboard.admin.session import AdminSessionManager
from safety_dashboard.alerts.admin import (
    AlertAdminAuthorizationError,
    AlertAdminConfigurationError,
    AlertAdminService,
)


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
            raise HTTPException(
                status_code=503, detail="관리자 통계 연동 미설정"
            ) from exc

    if cookie_session and session_manager:
        try:
            session_manager.verify_token(cookie_session)
            return service
        except Exception:
            raise HTTPException(
                status_code=403, detail="관리자 세션이 만료되었거나 올바르지 않습니다."
            )

    raise HTTPException(status_code=403, detail="관리자 인증이 필요합니다.")
