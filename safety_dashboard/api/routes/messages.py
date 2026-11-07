from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, HTTPException, Response

from safety_dashboard.admin.session import AdminSessionManager
from safety_dashboard.api.dependencies import ApiServices
from safety_dashboard.application.message_analysis import AnalysisBusy, AnalysisUnavailable, MessageAnalysisInput

NO_STORE = {"Cache-Control": "private, no-store"}


def build_router(services: ApiServices) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/message-analysis")

    def authorize(header: str, cookie: str):
        # Do not initialize notification/Firestore services for this read-only workspace.
        # Also reject tokens signed with the development fallback when admin is unconfigured.
        if services.admin_access.settings.password:
            for token in (header, cookie):
                if not token:
                    continue
                try:
                    services.session_manager.verify_token(token)
                    return
                except Exception:
                    continue
        raise HTTPException(403, "관리자 인증이 필요합니다. 다시 로그인해 주세요.", headers=NO_STORE)

    @router.get("/status")
    def status(response: Response,
               token: str = Header("", alias="X-Alert-Admin-Token"),
               cookie: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME)):
        authorize(token, cookie)
        response.headers.update(NO_STORE)
        return services.message_analysis.availability()

    @router.post("")
    def analyze(request: MessageAnalysisInput, response: Response,
                token: str = Header("", alias="X-Alert-Admin-Token"),
                cookie: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME)):
        authorize(token, cookie)
        response.headers.update(NO_STORE)
        try:
            return services.message_analysis.analyze(request)
        except AnalysisBusy as error:
            raise HTTPException(429, str(error), headers={**NO_STORE, "Retry-After": "20"}) from None
        except AnalysisUnavailable as error:
            raise HTTPException(503, str(error), headers=NO_STORE) from None
        except Exception:
            # Neither input text nor upstream error details are written to logs/responses.
            raise HTTPException(503, "문자 분석을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.", headers=NO_STORE) from None

    return router
