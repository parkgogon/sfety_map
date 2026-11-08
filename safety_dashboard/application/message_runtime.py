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


@dataclass(frozen=True)
class MessageRuntime:
    analysis: object
    records: MessageRecordService
    provider: object
    automation: MessageAutomationStatus
    pipeline_factory: object
    settings: MessageAutomationSettings


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

    analysis = analysis or MessageAnalysisService(
        OpenAIResponsesClient.from_environment(), KakaoPlaceSearch.from_environment(),
        CsvFacilityRepository(facility_path).list_monitored,
        gate_factory=lambda: AnalysisRunGate(pipeline_factory(), settings.daily_limit),
    )
    records = records or MessageRecordService(
        record_factory, analysis, storage_mode=store_mode,
        facility_digest=lambda: hashlib.sha256(facility_path.read_bytes()).hexdigest(),
        on_analysis_saved=lambda record: MessageAnalysisQueue(pipeline_factory()).sync_record(record, dt.datetime.now(UTC)),
    )
    provider = SafetyDataDisasterMessageProvider(feed_key,
                gate_factory=lambda: OfficialRequestBudget(pipeline_factory(), settings.request_limit))
    status = MessageAutomationStatus(settings, pipeline_factory if pipeline_builder else None, provider.configured)
    return MessageRuntime(analysis, records, provider, status, pipeline_factory, settings)
