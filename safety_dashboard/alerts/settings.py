"""자동 알림 작업자와 관리자 API 설정."""

from __future__ import annotations

import os
from dataclasses import dataclass

from safety_dashboard.api.settings import _secret


@dataclass(frozen=True)
class AlertSettings:
    automation_mode: str = "preview"
    solapi_api_key: str = ""
    solapi_api_secret: str = ""
    solapi_sender_number: str = ""
    solapi_webhook_secret: str = ""
    contact_sheet_id: str = ""
    contact_sheet_range: str = "Recipients!A:E"
    recipient_hmac_secret: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    dashboard_base_url: str = "https://keco-safety-map.web.app"
    admin_token: str = ""
    test_phone: str = ""
    project_id: str = ""
    daily_cap: int = 500
    cap_warning: int = 400
    pending_seconds: int = 1800

    @classmethod
    def from_environment(cls) -> "AlertSettings":
        mode = os.getenv("ALERT_AUTOMATION_MODE", "preview").strip().lower()
        if mode not in {"preview", "live", "paused"}:
            mode = "preview"

        def integer(name: str, default: int, minimum: int) -> int:
            try:
                return max(minimum, int(os.getenv(name, str(default))))
            except ValueError:
                return default

        daily_cap = integer("ALERT_DAILY_CAP", 500, 1)
        cap_warning = min(
            daily_cap,
            integer("ALERT_CAP_WARNING", 400, 1),
        )
        return cls(
            automation_mode=mode,
            solapi_api_key=_secret("SOLAPI_API_KEY", "solapi", "api_key"),
            solapi_api_secret=_secret(
                "SOLAPI_API_SECRET", "solapi", "api_secret"
            ),
            solapi_sender_number=_secret(
                "SOLAPI_SENDER_NUMBER", "solapi", "sender_number"
            ),
            solapi_webhook_secret=_secret(
                "SOLAPI_WEBHOOK_SECRET", "solapi", "webhook_secret"
            ),
            contact_sheet_id=_secret(
                "CONTACT_SHEET_ID", "alerting", "contact_sheet_id"
            ),
            contact_sheet_range=(
                os.getenv("CONTACT_SHEET_RANGE", "").strip()
                or "Recipients!A:E"
            ),
            recipient_hmac_secret=_secret(
                "ALERT_HMAC_SECRET", "alerting", "hmac_secret"
            ),
            telegram_bot_token=_secret(
                "TELEGRAM_BOT_TOKEN", "telegram", "bot_token"
            ),
            telegram_chat_id=_secret(
                "TELEGRAM_CHAT_ID", "telegram", "chat_id"
            ),
            dashboard_base_url=(
                os.getenv("DASHBOARD_BASE_URL", "").strip()
                or _secret("DASHBOARD_BASE_URL", "dashboard", "base_url")
                or cls.dashboard_base_url
            ),
            admin_token=_secret(
                "ALERT_ADMIN_TOKEN", "alerting", "admin_token"
            ),
            test_phone=_secret(
                "ALERT_TEST_PHONE", "alerting", "test_phone"
            ),
            project_id=(
                os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
                or os.getenv("GCP_PROJECT_ID", "").strip()
            ),
            daily_cap=daily_cap,
            cap_warning=cap_warning,
            pending_seconds=integer("ALERT_PENDING_SECONDS", 1800, 60),
        )
