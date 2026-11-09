"""At most one automatic paid attempt per source version; explicit retry is manual."""
from __future__ import annotations

import datetime as dt
import uuid

from safety_dashboard.application.message_analysis import AnalysisBusy, AnalysisBudgetBusy
from safety_dashboard.application.message_pipeline import AnalysisRunGate, MessageAnalysisQueue, PipelineLeases, UTC, moment
from safety_dashboard.application.message_records import AnalyzeRecord, RecordConflict, RecordNotFound


class MessageQueueProcessor:
    def __init__(self, records, store, settings, *, now=lambda: dt.datetime.now(UTC), on_analyzed=None, before_analysis=None):
        self.records, self.store, self.settings, self.now = records, store, settings, now
        self.queue, self.leases = MessageAnalysisQueue(store), PipelineLeases(store)
        self.on_analyzed = on_analyzed
        self.before_analysis = before_analysis

    @staticmethod
    def matches(record, task):
        return record["source_revision"] == task["source_revision"] and record["content_hash"] == task["content_hash"]

    def terminal(self, record, task):
        if not self.matches(record, task):
            return "obsolete", "source_changed"
        if record["analysis_state"] == "completed" and record["analysis_source_revision"] == record["source_revision"]:
            return "done", "analysis_saved"
        if record["review_state"] == "completed":
            return "deferred", "review_completed"
        if record["analysis_state"] == "failed":
            return "failed", "manual_retry_required"
        attempted = record.get("analysis_attempt_source_revision") == record["source_revision"]
        if attempted and record["analysis_state"] == "running":
            age = (self.now()-moment(record["analysis_started_at"])).total_seconds()
            if age < 120:
                return None
        if attempted:
            return "failed", "attempt_outcome_unknown"
        return None

    def settle(self, record, task, terminal, owner):
        if terminal[1] == "attempt_outcome_unknown" and record["analysis_state"] == "running":
            self.records.mark_analysis_interrupted(record["id"], record["analysis_operation"])
        self.queue.finish(task["id"], terminal[0], self.now(), terminal[1], owner=owner)

    def run(self):
        if not self.settings.enabled or not self.settings.contract_verified:
            return {"state": "disabled"}
        owner = uuid.uuid4().hex
        if not self.leases.acquire("processing-lease", owner, self.now()):
            return {"state": "busy"}
        try:
            for task in self.queue.expired(self.now(), 20):
                try:
                    record = self.records.get(task["record_id"])
                except RecordNotFound:
                    self.queue.finish(task["id"], "obsolete", self.now(), "record_missing", owner=task["owner"])
                    continue
                terminal = self.terminal(record, task)
                if terminal:
                    self.settle(record, task, terminal, task["owner"])
                else:
                    self.queue.finish(task["id"], "pending", self.now(), "lease_recovered", owner=task["owner"])
            gate = AnalysisRunGate(self.store, self.settings.daily_limit, now=self.now)
            budget = gate.status()
            if budget["active"] or not budget["remaining"]:
                return {"state": "busy" if budget["active"] else "daily_limit"}
            for task in self.queue.due(self.now(), 20):
                if not self.leases.owns("processing-lease", owner, self.now()):
                    return {"state": "lease_expired"}
                task = self.queue.claim(task["id"], owner, self.now())
                if not task:
                    continue
                try:
                    record = self.records.get(task["record_id"])
                    terminal = self.terminal(record, task)
                    if terminal:
                        self.settle(record, task, terminal, owner)
                        continue
                    if record["analysis_state"] == "running":
                        self.queue.finish(task["id"], "pending", self.now(), "analysis_in_progress", owner=owner, delay=60)
                        continue
                    if self.before_analysis and not self.before_analysis(record):
                        self.queue.finish(task["id"], "deferred", self.now(), "raw_fallback_prepared", owner=owner)
                        continue
                    if (self.now()-moment(task["enqueued_at"])).total_seconds() > self.settings.auto_max_age_hours*3600:
                        self.queue.finish(task["id"], "deferred", self.now(), "old_backlog_manual_review", owner=owner)
                        continue
                    saved = self.records.analyze(record["id"], AnalyzeRecord(expected_version=record["version"], reference_radius_km=record["reference_radius_km"]))
                except AnalysisBudgetBusy as error:
                    delay = max(60, (moment(error.retry_at)-self.now()).total_seconds())
                    self.queue.finish(task["id"], "pending", self.now(), "spend_limit", owner=owner, delay=delay)
                    return {"state": "spend_limit", "retry_at": error.retry_at}
                except AnalysisBusy:
                    self.queue.finish(task["id"], "pending", self.now(), "analysis_deferred", owner=owner, delay=60)
                    return {"state": "busy"}
                except RecordNotFound:
                    self.queue.finish(task["id"], "obsolete", self.now(), "record_missing", owner=owner)
                    continue
                except RecordConflict:
                    latest = self.records.get(task["record_id"])
                    terminal = self.terminal(latest, task)
                    self.queue.finish(task["id"], terminal[0] if terminal else "pending", self.now(),
                                      terminal[1] if terminal else "record_changed", owner=owner, delay=60)
                    return {"state": "changed"}
                except Exception:
                    self.queue.finish(task["id"], "failed", self.now(), "manual_retry_required", owner=owner)
                    if self.on_analyzed:
                        self.on_analyzed(self.records.get(task["record_id"]))
                    return {"state": "failed"}
                self.queue.finish(task["id"], "done", self.now(), "analysis_saved", owner=owner)
                if self.on_analyzed:
                    self.on_analyzed(saved)
                return {"state": "analyzed"}
            return {"state": "idle"}
        finally:
            self.leases.release("processing-lease", owner)
