"""Cloud Scheduler만 호출하는 비공개 자동 알림 Cloud Run 진입점."""

from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from safety_dashboard.adapters.firestore_alerts import FirestoreAlertStore
from safety_dashboard.adapters.google_sheet_contacts import GoogleSheetContactProvider
from safety_dashboard.adapters.solapi import SolapiNotifier
from safety_dashboard.adapters.telegram import TelegramNotifier
from safety_dashboard.alerts.service import AlertDispatcher
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.api.service import MonitoringApiService
from safety_dashboard.api.settings import ApiSettings
from safety_dashboard.domain.risk_policy import RiskPolicy


LOGGER = logging.getLogger("safety_dashboard.alert_worker")


class _SnapshotProvider:
    def __init__(self, service: MonitoringApiService) -> None:
        self.service = service

    def fetch(self):
        return self.service.snapshot(simulation=False)


@lru_cache(maxsize=1)
def _dispatcher() -> AlertDispatcher:
    api_settings = ApiSettings.from_environment()
    alert_settings = AlertSettings.from_environment()
    policy = RiskPolicy.load(api_settings.policy_path)
    telegram = (
        TelegramNotifier(
            alert_settings.telegram_bot_token,
            alert_settings.telegram_chat_id,
        )
        if alert_settings.telegram_bot_token and alert_settings.telegram_chat_id
        else None
    )
    return AlertDispatcher(
        snapshot_provider=_SnapshotProvider(MonitoringApiService(api_settings)),
        contacts=GoogleSheetContactProvider(
            alert_settings.contact_sheet_id,
            alert_settings.contact_sheet_range,
        ),
        sms=SolapiNotifier(
            alert_settings.solapi_api_key,
            alert_settings.solapi_api_secret,
            alert_settings.solapi_sender_number,
        ),
        store=FirestoreAlertStore(alert_settings.project_id),
        policy=policy,
        settings=alert_settings,
        telegram=telegram,
    )


def create_worker_app(dispatcher: AlertDispatcher | None = None) -> FastAPI:
    application = FastAPI(
        title="K-ECO Safety Alert Worker",
        docs_url=None,
        redoc_url=None,
    )

    @application.get("/internal/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "safety-alert-worker"}

    @application.post("/internal/v1/dispatch")
    def dispatch() -> dict[str, object]:
        return (dispatcher or _dispatcher()).run().as_dict()

    @application.post("/internal/v1/test")
    def send_test() -> dict[str, object]:
        return (dispatcher or _dispatcher()).send_test().as_dict()

    @application.exception_handler(Exception)
    async def unhandled_error(_, error: Exception) -> JSONResponse:
        LOGGER.error(
            "alert_dispatch_failed type=%s",
            type(error).__name__,
        )
        return JSONResponse(
            status_code=503,
            content={
                "status": "ERROR",
                "detail": "자동 알림 작업을 완료하지 못했습니다.",
            },
        )

    return application


app = create_worker_app()
