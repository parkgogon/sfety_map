"""IAM-private scheduled entrypoints. Never imports or invokes alert dispatch."""
from __future__ import annotations

import os
from pathlib import Path
import threading

from fastapi import FastAPI, HTTPException

from safety_dashboard.application.message_collection import OfficialMessageCollector
from safety_dashboard.application.message_collection_latest import RecentWindowMessageCollector
from safety_dashboard.application.message_processing import MessageQueueProcessor
from safety_dashboard.application.message_runtime import build_message_runtime


def create_app(runtime=None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    lock = threading.Lock()

    def services():
        nonlocal runtime
        with lock:
            if runtime is None:
                runtime = build_message_runtime(
                    Path(__file__).resolve().parents[2]/"facilities_info.csv",
                    os.getenv("GOOGLE_CLOUD_PROJECT", ""), os.getenv("MESSAGE_REVIEW_STORE", "firestore"),
                    os.getenv("SAFETY_DATA_API_KEY", ""),
                )
        return runtime

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "message-worker"}

    def execute(kind):
        current = services()
        collection_ready = current.settings.enabled and current.settings.contract_verified and current.provider.configured
        prepare = kind == "analyze" and current.settings.notification_preparation_enabled
        if not collection_ready and not prepare:
            return {"state": "disabled"}
        try:
            store = current.pipeline_factory()
            if kind == "collect":
                collector = RecentWindowMessageCollector if current.settings.latest_first_enabled else OfficialMessageCollector
                return collector(current.provider, current.records, store, current.settings).run()
            preparation = current.notification_preparation if prepare else None
            recovery = preparation.run() if preparation else None
            delivery = current.notification_delivery if current.settings.delivery_enabled else None
            delivery_result = delivery.run() if delivery else None
            result = MessageQueueProcessor(current.records, store, current.settings,
                on_analyzed=(lambda record: preparation.prepare_record(record["id"])) if preparation else None,
                before_analysis=preparation.auto_analysis_needed if preparation else None,
                **({"now": preparation.now} if preparation else {})).run() if collection_ready else {"state": "disabled"}
            if delivery and result.get("state") in {"analyzed", "failed"}:
                delivery_result = delivery.run()
            if delivery:
                result = {**result, "notification_delivery": delivery_result}
            return {**result, "notification_preparation": recovery} if preparation else result
        except Exception:
            raise HTTPException(503, "문자 자동 처리를 완료하지 못했습니다. 저장 기록은 유지됩니다.") from None

    @app.post("/internal/v1/collect")
    def collect():
        return execute("collect")

    @app.post("/internal/v1/analyze-next")
    def analyze_next():
        return execute("analyze")

    return app


app = create_app()
