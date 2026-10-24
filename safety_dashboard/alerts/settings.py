"""자동 알림 작업자와 관리자 API 설정."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from safety_dashboard.config.environment import env_text


@dataclass(frozen=True)
class AlertSettings:
    automation_mode: str = "preview"
    user_delivery_mode: str = "telegram"
    solapi_api_key: str = ""
    solapi_api_secret: str = ""
    solapi_sender_number: str = ""
    solapi_webhook_secret: str = ""
    contact_sheet_id: str = ""
    contact_sheet_range: str = "Recipients!A:E"
    recipient_hmac_secret: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_admin_chat_id: str = ""
    telegram_user_chat_id: str = ""
    dashboard_base_url: str = "https://keco-safety-map.web.app"
    admin_token: str = ""
    test_phone: str = ""
    project_id: str = ""
    app_revision: str = "local"
    daily_cap: int = 100
    cap_warning: int = 80
    monthly_cap: int = 500
    monthly_cap_warning: int = 400
    balance_warning: int = 10000
    balance_critical: int = 3000
    pending_seconds: int = 1800
    telegram_retry_seconds: int = 1800
    included_warning_types: tuple[str, ...] = ()
    excluded_warning_types: tuple[str, ...] = ("열대야",)

    @classmethod
    def from_environment(cls) -> "AlertSettings":
        mode = os.getenv("ALERT_AUTOMATION_MODE", "preview").strip().lower()
        if mode not in {"preview", "live", "paused"}:
            mode = "preview"
        delivery_mode = (
            os.getenv("ALERT_USER_DELIVERY_MODE", "telegram").strip().lower()
        )
        if delivery_mode not in {"telegram", "sms"}:
            delivery_mode = "telegram"

        def integer(name: str, default: int, minimum: int) -> int:
            try:
                return max(minimum, int(os.getenv(name, str(default))))
            except ValueError:
                return default

        def warning_types(name: str, default: str = "") -> tuple[str, ...]:
            raw = os.getenv(name, default)
            if raw.strip().casefold() in {"", "-", "none", "없음"}:
                return ()
            return tuple(
                dict.fromkeys(
                    item.strip() for item in re.split(r"[,|;\n]+", raw) if item.strip()
                )
            )

        daily_cap = integer("ALERT_DAILY_CAP", 100, 1)
        cap_warning = min(
            daily_cap,
            integer("ALERT_CAP_WARNING", 80, 1),
        )
        monthly_cap = integer("ALERT_MONTHLY_CAP", 500, 1)
        monthly_cap_warning = min(
            monthly_cap,
            integer("ALERT_MONTHLY_CAP_WARNING", 400, 1),
        )
        legacy_chat_id = env_text("TELEGRAM_CHAT_ID")
        admin_chat_id = env_text("TELEGRAM_ADMIN_CHAT_ID") or legacy_chat_id
        return cls(
            automation_mode=mode,
            user_delivery_mode=delivery_mode,
            solapi_api_key=env_text("SOLAPI_API_KEY"),
            solapi_api_secret=env_text("SOLAPI_API_SECRET"),
            solapi_sender_number=env_text("SOLAPI_SENDER_NUMBER"),
            solapi_webhook_secret=env_text("SOLAPI_WEBHOOK_SECRET"),
            contact_sheet_id=env_text("CONTACT_SHEET_ID"),
            contact_sheet_range=(
                os.getenv("CONTACT_SHEET_RANGE", "").strip() or "Recipients!A:E"
            ),
            recipient_hmac_secret=env_text("ALERT_HMAC_SECRET"),
            telegram_bot_token=env_text("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=legacy_chat_id,
            telegram_admin_chat_id=admin_chat_id,
            telegram_user_chat_id=env_text("TELEGRAM_USER_CHAT_ID"),
            dashboard_base_url=(
                env_text("DASHBOARD_BASE_URL") or cls.dashboard_base_url
            ),
            admin_token=env_text("ALERT_ADMIN_TOKEN"),
            test_phone=env_text("ALERT_TEST_PHONE"),
            project_id=(
                os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
                or os.getenv("GCP_PROJECT_ID", "").strip()
            ),
            app_revision=(os.getenv("APP_REVISION", "").strip() or "local")[:40],
            daily_cap=daily_cap,
            cap_warning=cap_warning,
            monthly_cap=monthly_cap,
            monthly_cap_warning=monthly_cap_warning,
            balance_warning=integer("SOLAPI_BALANCE_WARNING", 10000, 0),
            balance_critical=integer("SOLAPI_BALANCE_CRITICAL", 3000, 0),
            pending_seconds=integer("ALERT_PENDING_SECONDS", 1800, 60),
            telegram_retry_seconds=integer("ALERT_TELEGRAM_RETRY_SECONDS", 1800, 300),
            included_warning_types=warning_types("ALERT_INCLUDED_WARNING_TYPES"),
            excluded_warning_types=warning_types(
                "ALERT_EXCLUDED_WARNING_TYPES", "열대야"
            ),
        )
