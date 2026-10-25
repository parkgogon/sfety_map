from __future__ import annotations
from safety_dashboard.admin.access import AdminAccessSettings, AdminAccessVerifier
from safety_dashboard.admin.session import AdminSessionManager
from safety_dashboard.api.context_service import FacilityContextService
from safety_dashboard.api.service import MonitoringApiService
from safety_dashboard.api.settings import ApiSettings
from safety_dashboard.api.weather_layer_service import WeatherLayerService
from safety_dashboard.adapters.firestore_alerts import FirestoreAlertStore
from safety_dashboard.adapters.firestore_monitoring import (
    FirestoreMonitoringSnapshotStore,
)
from safety_dashboard.adapters.operational_health import HttpSystemHealthProbe
from safety_dashboard.adapters.telegram import TelegramNotifier
from safety_dashboard.alerts.admin import AlertAdminService
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.operations.readiness import OperationalReadinessService
from safety_dashboard.api.nearby_reports import NearbyReportGenerator
from safety_dashboard.adapters.kakao_report_capture import KakaoReportCapture
from safety_dashboard.api.settings import ROOT

from dataclasses import dataclass
from collections.abc import Callable


@dataclass(frozen=True)
class ApiServices:
    settings: ApiSettings
    alert_settings: AlertSettings
    monitoring_service: MonitoringApiService
    facility_context: FacilityContextService
    weather_layers: WeatherLayerService
    admin_access: AdminAccessVerifier
    session_manager: AdminSessionManager
    notification_admin: Callable[[], AlertAdminService]
    operational_readiness: Callable[[], OperationalReadinessService]
    nearby_reports: NearbyReportGenerator


def build_services(
    service: MonitoringApiService | None = None,
    context_service: FacilityContextService | None = None,
    weather_layer_service: WeatherLayerService | None = None,
    alert_admin_service: AlertAdminService | None = None,
    admin_access_service: AdminAccessVerifier | None = None,
    operational_readiness_service: OperationalReadinessService | None = None,
    nearby_report_generator: NearbyReportGenerator | None = None,
) -> ApiServices:
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
    try:
        capture = KakaoReportCapture(enabled=settings.nearby_map_capture_enabled, origin=settings.nearby_map_origin,
                                     executable=settings.nearby_chromium_executable, timeout=settings.nearby_map_timeout_seconds)
    except ValueError:
        capture = KakaoReportCapture(enabled=False, origin=ApiSettings.nearby_map_origin)

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

    return ApiServices(
        settings=settings,
        alert_settings=alert_settings,
        monitoring_service=monitoring_service,
        facility_context=facility_context,
        weather_layers=weather_layers,
        admin_access=admin_access,
        session_manager=session_manager,
        notification_admin=notification_admin,
        operational_readiness=operational_readiness,
        nearby_reports=nearby_report_generator or NearbyReportGenerator(capture, ROOT / "fonts/NotoSansKR.ttf"),
    )
