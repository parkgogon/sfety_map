"""One-off recovery of two known historical SafetyData records."""
from __future__ import annotations

import datetime as dt
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
import threading

from safety_dashboard.adapters.disaster_messages import SafetyDataDisasterMessageProvider
from safety_dashboard.adapters.firestore_message_pipeline import FirestoreMessagePipelineStore
from safety_dashboard.adapters.firestore_message_records import FirestoreMessageRecordStore
from safety_dashboard.application.message_automation import MessageAutomationSettings
from safety_dashboard.application.message_collection import OfficialMessageCollector, recipient_scope
from safety_dashboard.application.message_earthquake import earthquake_report
from safety_dashboard.application.message_feed_budget import (
    FeedRequestLimit, OfficialRequestBudget, recent_request_reserve,
)
from safety_dashboard.application.message_pipeline import UTC, moment, stamp
from safety_dashboard.application.message_records import MessageRecordService, MessageSource

PROJECT = "keco-safety-map"
DAY = dt.date(2026, 11, 17)
KST = dt.timezone(dt.timedelta(hours=9))
COLLECTION_START = dt.datetime.fromisoformat("2026-11-08T13:45:00.961104+00:00")
OCCURRED_AT = dt.datetime.fromisoformat("2026-11-17T23:10:00+09:00")
EXPECTED = {
    "initial": (dt.datetime.fromisoformat("2026-11-17T23:10:32+09:00"), "3.7"),
    "correction": (dt.datetime.fromisoformat("2026-11-17T23:16:52+09:00"), "3.6"),
}


def case(record):
    quake = earthquake_report(record)
    if quake and quake.location == "경북 상주시 북서쪽 22km 지역" and quake.occurred_at == OCCURRED_AT:
        key = "correction" if quake.is_correction else "initial"
        if (quake.issued_at, quake.magnitude) == EXPECTED[key]:
            return key
    return None


def restore(store, records, source, *, revision, limit, now):
    report = {"status": "blocked", "checked_at": stamp(now), "revision": revision,
              "api_calls": 0, "imported_records": 0, "model_calls": 0, "messages_sent": 0, "records": {}}
    worker = store.get("message-delivery-worker") or {}
    control = store.get("message-delivery-control") or {}
    collection = store.get("collection-state") or {}
    if (worker.get("revision") != revision or worker.get("state") != "paused_or_unconfigured"
            or not -10 <= (now-moment(worker["at"])).total_seconds() <= 180
            or (control.get("revision") == revision and control.get("mode") == "active")):
        return {**report, "reason": "wait_for_final_worker_before_resume"}
    if not collection.get("start_at") or moment(collection["start_at"]) != COLLECTION_START:
        return {**report, "reason": "collection_cutoff_mismatch"}
    # The deployed earthquake rule treats an event older than one hour as history.
    if any(now-issued <= dt.timedelta(hours=1) for issued, _ in EXPECTED.values()):
        return {**report, "reason": "source_is_not_historical"}

    def record_summary(record):
        return {"issued_at": record["message"]["issued_at"],
                "recipient_count": len(record["message"]["recipient_regions"]),
                "analysis_state": record["analysis_state"]}

    # Production records are deduplicated by official source ID by the standard importer.
    for record in records.store.list_page(None, 100):
        if (key := case(record)) and len(record["message"]["recipient_regions"]) == 60:
            report["records"][key] = record_summary(record)
    if set(report["records"]) == EXPECTED.keys():
        return {**report, "status": "passed", "method": "already_collected"}

    collector = OfficialMessageCollector(source, records, store, MessageAutomationSettings(request_limit=limit),
                                         now=lambda: now)
    report["api_calls"] = 1
    try:
        rows = source.fetch_page(None, DAY, 1, 100, priority="background")["messages"]
    except FeedRequestLimit:
        return {**report, "api_calls": 0, "reason": "official_feed_budget_wait"}
    except Exception as error:
        return {**report, "reason": "source_read_failed", "error_type": type(error).__name__}

    matched = {}
    for row in rows:
        if len(row.regions) != 60 or recipient_scope(row.regions) is not True:
            continue
        message = MessageSource(text=row.content, source="행정안전부 공개 재난문자 API",
                                issued_at=row.created_at, recipient_regions=list(row.regions)).canonical()
        key = case({"origin": "official", "message": message})
        if key:
            if key in matched:
                return {**report, "reason": "source_is_ambiguous"}
            matched[key] = row
    if set(matched) != EXPECTED.keys() or len({row.id for row in matched.values()}) != 2:
        return {**report, "reason": "could_not_match_both_official_sources"}

    # Use the same validation, source/version registration and idempotent queue as the scheduler.
    day = now.astimezone(KST).date()
    for key, row in matched.items():
        identifier = records.official_record_id(row.id)
        if records.store.get(identifier) is None:
            count, _ = collector._observe_row(row, DAY.isoformat(), day, stamp(now), collection["start_at"], lambda reason: None)
            report["imported_records"] += count
        saved = records.get(identifier)
        if case(saved) != key or len(saved["message"]["recipient_regions"]) != 60:
            return {**report, "reason": "stored_record_does_not_match"}
        report["records"][key] = record_summary(saved)
    return {**report, "status": "passed", "method": "historical_source_recovery"}


def run():
    now = dt.datetime.now(UTC)
    pipeline = FirestoreMessagePipelineStore(PROJECT)
    records = MessageRecordService(lambda: FirestoreMessageRecordStore(PROJECT, client=pipeline.client),
                                   analysis=None, now=lambda: now)
    limit = int(os.environ["VERIFY_FEED_LIMIT"])
    budget = OfficialRequestBudget(pipeline, limit, now=lambda: now, latest_reserve=recent_request_reserve(limit))
    provider = SafetyDataDisasterMessageProvider(os.environ["SAFETY_DATA_API_KEY"], gate_factory=lambda: budget)
    return restore(pipeline, records, provider, revision=os.environ["VERIFY_DEPLOYED_SHA"], limit=limit, now=now)


class Handler(BaseHTTPRequestHandler):
    report = None
    lock = threading.Lock()

    def log_message(self, *_args):
        pass

    def do_POST(self):
        if self.path != "/verify" or self.headers.get("Content-Length", "0") != "0":
            self.send_error(400)
            return
        with self.lock:
            if type(self).report is None:
                try:
                    type(self).report = run()
                except Exception as error:
                    type(self).report = {"status": "blocked", "error_type": type(error).__name__}
        data = json.dumps(self.report, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    HTTPServer(("0.0.0.0", int(os.getenv("PORT", "8080"))), Handler).serve_forever()
