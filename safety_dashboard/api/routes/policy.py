from __future__ import annotations
from fastapi import Cookie, Header, Response
from safety_dashboard.admin.session import AdminSessionManager

from fastapi import APIRouter
from safety_dashboard.api.dependencies import ApiServices
from safety_dashboard.api.authorization import _authorized_admin
from safety_dashboard.api.settings import ROOT


def build_router(services: ApiServices) -> APIRouter:
    router = APIRouter()
    session_manager = services.session_manager
    notification_admin = services.notification_admin

    @router.get("/internal/v1/policy")
    def internal_policy(
        response: Response,
        x_alert_admin_token: str = Header("", alias="X-Alert-Admin-Token"),
        cookie_session: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME),
    ) -> dict[str, object]:
        """기본 위험도 정책 및 특보별 매트릭스 정보를 반환합니다."""
        response.headers["Cache-Control"] = "private, no-store"
        _authorized_admin(
            notification_admin(), x_alert_admin_token, cookie_session, session_manager
        )

        from safety_dashboard.domain.risk_policy import RiskPolicy

        policy_path = ROOT / "safety_dashboard" / "config" / "risk_policy.toml"
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
                    level.value: grade.value for level, grade in levels.items()
                }
                for warning_type, levels in policy.warning_matrix.items()
            },
        }

    return router
