"""IAM-private scheduled entrypoints. Never imports or invokes alert dispatch."""
from __future__ import annotations

import os
from pathlib import Path
import threading

from fastapi import FastAPI, HTTPException

from safety_dashboard.application.message_collection import OfficialMessageCollector
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
        if not current.settings.enabled or not current.settings.contract_verified or not current.provider.configured:
            return {"state": "disabled"}
        try:
            store = current.pipeline_factory()
            if kind == "collect":
                return OfficialMessageCollector(current.provider, current.records, store, current.settings).run()
            return MessageQueueProcessor(current.records, store, current.settings).run()
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
