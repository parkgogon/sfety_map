"""Shared message-only composition for API and private scheduled worker."""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import os
import threading

from safety_dashboard.adapters.disaster_messages import SafetyDataDisasterMessageProvider
from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.adapters.firestore_message_pipeline import FirestoreMessagePipelineStore
from safety_dashboard.adapters.firestore_message_records import FirestoreMessageRecordStore
from safety_dashboard.adapters.kakao_places import KakaoPlaceSearch
from safety_dashboard.adapters.openai_messages import OpenAIResponsesClient
from safety_dashboard.application.message_analysis import AnalysisUnavailable, MessageAnalysisService
from safety_dashboard.application.message_automation import MessageAutomationSettings, MessageAutomationStatus
from safety_dashboard.application.message_pipeline import AnalysisRunGate, MemoryPipelineStore, MessageAnalysisQueue, UTC
from safety_dashboard.application.message_records import MemoryRecordStore, MessageRecordService
from safety_dashboard.application.message_feed_budget import OfficialRequestBudget
from safety_dashboard.application.message_spend_budget import MessageSpendBudget, SpendBudgetLimit
from safety_dashboard.application.message_notification_jobs import MessageNotificationPreparation, MemoryNotificationStore
from safety_dashboard.adapters.firestore_message_notifications import FirestoreMessageNotificationStore
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.adapters.telegram import TelegramNotifier
from safety_dashboard.application.message_delivery import MessageDelivery


@dataclass(frozen=True)
class MessageRuntime:
    analysis: object
    records: MessageRecordService
    provider: object
    automation: MessageAutomationStatus
    pipeline_factory: object
    settings: MessageAutomationSettings
    notification_preparation: MessageNotificationPreparation | None = None
    notification_delivery: MessageDelivery | None = None


def build_message_runtime(facility_path, project_id, store_mode, feed_key, *, analysis=None, records=None):
    settings = MessageAutomationSettings.from_environment()
    record_factory, pipeline_builder = None, None
    if store_mode == "memory" and not os.getenv("K_SERVICE"):
        record_factory, pipeline_builder = MemoryRecordStore, MemoryPipelineStore
    elif store_mode == "firestore" and project_id:
        record_factory = lambda: FirestoreMessageRecordStore(project_id)
        pipeline_builder = lambda: FirestoreMessagePipelineStore(project_id)
    else:
        store_mode = "disabled"
    pipeline, lock = None, threading.Lock()

    def pipeline_factory():
        nonlocal pipeline
        if not pipeline_builder:
            raise AnalysisUnavailable("분석 한도 저장소가 설정되지 않았습니다. 분석을 시작하지 않았습니다.")
        with lock:
            if pipeline is None:
                pipeline = pipeline_builder()
        return pipeline

    def spend_factory():
        return MessageSpendBudget(pipeline_factory(), daily_cents=settings.daily_budget_cents, monthly_cents=settings.monthly_budget_cents)

    analysis = analysis or MessageAnalysisService(
        OpenAIResponsesClient.from_environment(spend_factory=spend_factory if settings.spend_budget_enabled else None), KakaoPlaceSearch.from_environment(),
        CsvFacilityRepository(facility_path).list_monitored,
        gate_factory=lambda: AnalysisRunGate(pipeline_factory(), settings.daily_limit),
    )
    records = records or MessageRecordService(
        record_factory, analysis, storage_mode=store_mode,
        facility_digest=lambda: hashlib.sha256(facility_path.read_bytes()).hexdigest(),
        on_analysis_saved=lambda record: MessageAnalysisQueue(pipeline_factory()).sync_record(record, dt.datetime.now(UTC)),
    )
    provider = SafetyDataDisasterMessageProvider(feed_key,
                gate_factory=lambda: OfficialRequestBudget(pipeline_factory(), settings.request_limit, latest_reserve=289 if settings.latest_first_enabled else 0))
    status = MessageAutomationStatus(settings, pipeline_factory if pipeline_builder else None, provider.configured)
    notification_store, notification_lock = None, threading.Lock()
    def notification_store_factory():
        nonlocal notification_store
        with notification_lock:
            if notification_store is None:
                pipeline_store = pipeline_factory()
                if store_mode == "memory":
                    notification_store = MemoryNotificationStore(records.store, pipeline_store)
                elif store_mode == "firestore":
                    notification_store = FirestoreMessageNotificationStore(client=pipeline_store.client)
                else:
                    raise AnalysisUnavailable("알림 준비 저장소를 확인하지 못했습니다.")
        return notification_store
    def failure_check(record):
        try:
            if not AnalysisRunGate(pipeline_factory(), settings.daily_limit).status()["remaining"]:
                return "ai_daily_limit"
            if settings.spend_budget_enabled:
                spend_factory().check()
            client = getattr(analysis, "client", None)
            if client is not None and not client.configured:
                return "ai_unavailable"
        except SpendBudgetLimit:
            return "ai_spend_limit"
        except Exception:
            return "ai_unavailable"
        return None

    alert_settings = AlertSettings.from_environment()
    preparation = MessageNotificationPreparation(records, notification_store_factory,
        CsvFacilityRepository(facility_path).snapshot, enabled=settings.notification_preparation_enabled,
        base_url=alert_settings.dashboard_base_url,
        fallback_enabled=settings.emergency_fallback_enabled, failure_check=failure_check,
        delivery_tracking_enabled=settings.delivery_enabled)
    staff_id, admin_id = alert_settings.telegram_user_chat_id, alert_settings.telegram_admin_chat_id
    senders = {"staff_group": TelegramNotifier(alert_settings.telegram_bot_token, staff_id),
               "admin_group": TelegramNotifier(alert_settings.telegram_bot_token, admin_id)} if settings.delivery_enabled else {}
    binding = hashlib.sha256((alert_settings.telegram_bot_token+'\0'+staff_id+'\0'+admin_id).encode()).hexdigest() if senders and staff_id and admin_id and staff_id != admin_id else ''
    delivery = MessageDelivery(preparation, senders, enabled=settings.delivery_enabled,
        binding=binding, revision=alert_settings.app_revision,
        ready=bool(settings.enabled and settings.contract_verified and settings.latest_first_enabled and settings.spend_budget_enabled and settings.emergency_fallback_enabled))
    return MessageRuntime(analysis, records, provider, status, pipeline_factory, settings, preparation, delivery)
