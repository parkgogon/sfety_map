"""Durable preview-only decisions/jobs. No model calls, Telegram imports or delivery permission."""
from __future__ import annotations

import copy
import datetime as dt
import json

from safety_dashboard.application.message_notification import POLICY_VERSION, notification_preview
from safety_dashboard.application.message_notification_fallback import emergency_original_preview, unavailable_reason, REASONS, KST
from safety_dashboard.application.message_pipeline import UTC, moment, stamp
from safety_dashboard.application.message_records import RecordConflict, RecordNotFound, content_hash

CONFIG_KEY = "notification-preparation-config"
DELIVERY_CONTROL_KEY = "message-delivery-control"
PENDING_PREFIX = "NJ|"
NOTIFIABLE = {"notify_ready", "notify_source_only"}
INCIDENT_LABELS = {**REASONS, "attention_required": "의미·업무 관련성 확인 필요", "blocked": "최신 근거 확인 필요"}


def validate_writes(keys, writes):
    if set(writes) - set(keys):
        raise ValueError("notification_transaction_keys")
    if any(len(json.dumps(value, ensure_ascii=False).encode()) > 800_000 for value in writes.values()):
        raise ValueError("notification_document_size")


class MemoryNotificationStore:
    """Explicit tests/local backend, bound to the same record and pipeline instances."""
    def __init__(self, records, pipeline):
        self.records, self.pipeline = records, pipeline

    def get(self, key):
        return self.pipeline.get(key)

    def run(self, keys, update):
        return self.pipeline.run(keys, update)

    def scan(self, low, high, limit, *, reverse=False):
        return self.pipeline.scan(low, high, limit, **({"reverse": True} if reverse else {}))

    def run_record(self, identifier, keys, update):
        # One lock order across instances. Failed preparation never clears the marker.
        with self.records.lock, self.pipeline.lock:
            current = self.records.records.get(identifier)
            values = {key: copy.deepcopy(self.pipeline.values.get(key)) for key in keys}
            writes, acknowledge, result = update(copy.deepcopy(current), values)
            validate_writes(keys, writes)
            self.pipeline.values.update(copy.deepcopy(writes))
            if acknowledge and current:
                self.records.records[identifier] = {**current, "notification_dirty": False}
            return copy.deepcopy(result)


def head_key(identifier):
    return "notification-head-" + content_hash(identifier)


def source_key(record):
    return "notification-source-" + content_hash({"id": record["id"], "source_revision": record["source_revision"],
                                                 "content_hash": record["content_hash"]})


def job_key(record):
    return "notification-job-" + source_key(record).removeprefix("notification-source-")


def record_basis(record, digest, policy_version, base_url):
    # Semantic edits fence old jobs. Poll observations, dirty acknowledgement and version alone do not.
    keys = ("origin", "message", "source_revision", "content_hash", "analysis_revision", "analysis_source_revision",
            "analysis_state", "analysis", "facility_digest", "reference_radius_km", "note", "spatial_references",
            "review_state", "review_completion", "review_working_copy", "related_messages", "relation_epoch")
    return content_hash({"record": {k: record.get(k) for k in keys}, "catalog_digest": digest,
                         "policy_version": policy_version, "base_url": base_url})


def preview_hash(preview):
    return content_hash({k: v for k, v in preview.items() if k != "record_version"})


def _invalidate(job, reason, now):
    return {**job, "state": "invalidated", "detail": reason, "updated_at": stamp(now),
            "queue_key": "NI|" + stamp(now) + "|" + job["id"]}


class MessageNotificationPreparation:
    def __init__(self, records, store_factory, catalog, *, enabled=False, base_url="",
                 now=lambda: dt.datetime.now(UTC), policy_version=POLICY_VERSION, fallback_enabled=False, failure_check=None,
                 delivery_tracking_enabled=False):
        self.records, self.store_factory, self.catalog = records, store_factory, catalog
        self.enabled, self.base_url, self.now, self.policy_version = enabled, base_url, now, policy_version
        self.fallback_enabled, self.failure_check = fallback_enabled, failure_check
        self.delivery_tracking_enabled = delivery_tracking_enabled

    def activate(self):
        if not self.enabled:
            return None
        now = self.now()
        def activate(values):
            config = values[CONFIG_KEY]
            if config:
                if config.get("phase") != "preview" or config.get("dispatch_enabled") is not False:
                    raise ValueError("notification_preparation_config")
                return {}, config
            config = {"phase": "preview", "dispatch_enabled": False, "started_at": stamp(now),
                      "delivery_started_at": None}
            return {CONFIG_KEY: config}, config
        return self.store_factory().run([CONFIG_KEY], activate)

    def _preview(self, record, catalog, previous=None):
        result = notification_preview(record, catalog, base_url=self.base_url, now=self.now())
        if self.fallback_enabled and result["decision"] == "analysis_unavailable":
            reason = unavailable_reason(record, self.failure_check)
            # Recovery of quota alone does not erase an already prepared original.
            if previous and previous["basis_hash"] == record_basis(record, catalog[0], self.policy_version, self.base_url):
                reason = previous.get("snapshot", {}).get("fallback_unavailable_reason") or reason
            fallback = emergency_original_preview(record, result, reason, now=self.now(), base_url=self.base_url)
            if fallback:
                result = fallback
            elif reason in REASONS:
                result = {**result, "unavailable_reason": reason}
        return {**result, "policy_version": self.policy_version}

    def auto_analysis_needed(self, record):
        if not self.enabled or not self.fallback_enabled:
            return True
        job = self.store_factory().get(job_key(record))
        # A source already finalized as a raw emergency must not incur later automatic AI costs.
        return not (job and job.get("snapshot", {}).get("preparation_kind") == "raw_emergency_fallback")

    def prepare_record(self, identifier):
        if not self.enabled:
            return {"state": "disabled"}
        store = self.store_factory()
        config = self.activate()
        for _ in range(3):
            record = self.records.get(identifier)
            if record.get("origin") != "official":
                def acknowledge(current, values):
                    if not current or current["version"] != record["version"]:
                        raise RecordConflict("알림 준비 중 기록이 변경됐습니다.")
                    return {}, True, {"state": "not_official"}
                try:
                    return store.run_record(identifier, [], acknowledge)
                except RecordConflict:
                    continue
            catalog = self.catalog()
            basis = record_basis(record, catalog[0], self.policy_version, self.base_url)
            slot, jid, hid = source_key(record), job_key(record), head_key(identifier)
            observed_job = store.get(jid)
            preview = self._preview(record, catalog, observed_job)
            issued = record["message"].get("issued_at")
            scope = "eligible" if issued and moment(issued) >= moment(config["started_at"]) else "before_activation" if issued else "unknown_time"
            semantic = preview_hash(preview)
            did = "notification-decision-" + content_hash({"source": slot, "basis": basis, "preview": semantic, "scope": scope})
            previous_head = store.get(hid)
            previous_job = (previous_head or {}).get("job_id")
            keys = list(dict.fromkeys([CONFIG_KEY, hid, slot, did, jid, *([previous_job] if previous_job else [])]))
            now = self.now()
            watch = "notification-watch-"+content_hash(identifier)
            reason = preview.get("unavailable_reason") or (preview["decision"] if preview["decision"] in {"attention_required", "blocked"} else None)
            incident = "notification-incident-"+now.astimezone(KST).date().isoformat()+"-"+str(reason)
            marker = incident+"-source-"+content_hash(slot)
            incident_needed = self.fallback_enabled and scope == "eligible" and reason in INCIDENT_LABELS
            if self.fallback_enabled:
                keys.append(watch)
            if incident_needed:
                keys.extend([incident, marker])
            if self.delivery_tracking_enabled:
                keys.append(DELIVERY_CONTROL_KEY)

            def persist(current, values):
                if (not current or current["version"] != record["version"]
                        or record_basis(current, catalog[0], self.policy_version, self.base_url) != basis
                        or values[CONFIG_KEY] != config or values[hid] != previous_head or values[jid] != observed_job):
                    raise RecordConflict("알림 판단의 근거가 변경됐습니다.")
                writes = {}
                delivery_control = values.get(DELIVERY_CONTROL_KEY) or {}
                delivery_generation = delivery_control.get("generation") if delivery_control.get("mode") == "active" else None
                if previous_job:
                    old = values[previous_job]
                    if old and old["state"] == "pending" and (
                            old["basis_hash"] != basis or old["preview_hash"] != semantic or old["source_key"] != slot):
                        writes[previous_job] = _invalidate(old, "source_or_basis_changed", now)
                first = values[slot] is None
                source_state = values[slot] or {"record_id": identifier, "source_revision": record["source_revision"],
                    "content_hash": record["content_hash"], "first_decision_id": did, "created_at": stamp(now), "finalized": False}
                finalizable = scope != "eligible" or preview.get("preparation_kind") == "raw_emergency_fallback" or (
                    record.get("analysis_state") == "completed" and record.get("analysis_source_revision") == record["source_revision"]
                    and record.get("facility_digest") == catalog[0] and preview.get("assessment") is not None)
                first_finalization = finalizable and not source_state["finalized"]
                if first:
                    writes[slot] = source_state
                if first_finalization:
                    writes[slot] = {**source_state, "finalized": True, "final_decision_id": did}
                    if scope == "eligible" and preview["decision"] in NOTIFIABLE:
                        if values[jid]:
                            raise ValueError("notification_source_ledger_missing")
                        writes[jid] = {"id": jid, "record_id": identifier, "source_key": slot,
                            "source_revision": record["source_revision"], "content_hash": record["content_hash"],
                            "basis_hash": basis, "preview_hash": semantic, "decision_id": did,
                            "phase": "preview", "dispatch_enabled": False, "destination": "staff_group",
                            "delivery_generation": delivery_generation,
                            "state": "pending", "detail": "prepared_unsent", "snapshot": preview,
                            "preparation_started_at": config["started_at"], "created_at": stamp(now),
                            "checked_at": stamp(now), "updated_at": stamp(now),
                            "queue_key": PENDING_PREFIX + stamp(now) + "|" + jid}
                if not values[did]:
                    writes[did] = {"id": did, "record_id": identifier, "source_key": slot, "basis_hash": basis,
                                   "scope": scope, "snapshot": preview, "created_at": stamp(now)}
                if self.fallback_enabled:
                    waiting = scope == "eligible" and not finalizable and record.get("analysis_state") in {"not_analyzed", "running"}
                    # Rotate unresolved records even after the initial dirty marker was acknowledged.
                    writes[watch] = {"record_id": identifier, "queue_key": ("NW|" if waiting else "NX|")+stamp(now)+"|"+watch}
                if incident_needed and not values[marker]:
                    old_incident = values[incident] or {"id": incident, "category": reason, "created_at": stamp(now),
                        "phase": "preview", "dispatch_enabled": False, "destination": "admin_group", "source_count": 0}
                    refs = [identifier, *[r for r in old_incident.get("recent_record_ids", []) if r != identifier]][:5]
                    writes[incident] = {**old_incident, "source_count": old_incident["source_count"]+1,
                        "recent_record_ids": refs, "latest_new_source_at": stamp(now), "updated_at": stamp(now), "queue_key": "NE|"+stamp(now)+"|"+incident,
                        "latest_new_source_generation": delivery_generation,
                        "preview_text": "[재난문자 자동 처리 확인 필요]\n"+INCIDENT_LABELS[reason]+" 항목이 있습니다. 저장된 원문과 판단 근거를 관리자 화면에서 확인해 주세요."}
                    writes[marker] = {"source_key": slot, "incident_id": incident}
                active_job = writes.get(jid) or values[jid]
                state = (active_job["state"] if active_job else scope if scope != "eligible"
                         else "reconsideration_required" if source_state["finalized"] and preview["decision"] in NOTIFIABLE
                         else preview["decision"])
                head = {"record_id": identifier, "source_key": slot, "decision_id": did, "basis_hash": basis,
                        "job_id": jid if active_job else None, "state": state, "updated_at": stamp(now)}
                if not previous_head or not previous_head.get("queue_key") or any(previous_head.get(k) != head[k] for k in head if k != "updated_at"):
                    head["queue_key"] = "NH|"+stamp(now)+"|"+hid
                    writes[hid] = head
                return writes, True, {"state": state, "decision_id": did, "job_id": head["job_id"],
                                     "first_evaluation": first, "first_finalization": first_finalization}

            try:
                return store.run_record(identifier, keys, persist)
            except RecordConflict:
                continue
        raise RecordConflict("알림 준비 중 변경이 이어져 다음 실행에서 다시 확인합니다.")

    def validate_pending(self, identifier):
        """Validate a stored preview job, never claim it for transport or authorize delivery."""
        if not self.enabled:
            return {"state": "disabled"}
        store = self.store_factory()
        for _ in range(3):
            job = store.get(identifier)
            if not job or job["state"] != "pending":
                return {"state": job["state"] if job else "missing"}
            rid = job["record_id"]
            try:
                record = self.records.get(rid)
            except RecordNotFound:
                record = None
            catalog = self.catalog()
            basis = record_basis(record, catalog[0], self.policy_version, self.base_url) if record else None
            preview = self._preview(record, catalog, job) if record else None
            now = self.now()
            hid = head_key(rid)
            def validate(current, values):
                current_job, head, config = values[identifier], values[hid], values[CONFIG_KEY]
                if current_job != job or (current is None) != (record is None):
                    raise RecordConflict("발송 대기 작업이 변경됐습니다.")
                if current and (current["version"] != record["version"]
                                or record_basis(current, catalog[0], self.policy_version, self.base_url) != basis):
                    raise RecordConflict("발송 대기 작업의 원문이 변경됐습니다.")
                valid = bool(current and config and config.get("phase") == "preview" and config.get("dispatch_enabled") is False
                    and config.get("started_at") == job["preparation_started_at"]
                    and job.get("phase") == "preview" and job.get("dispatch_enabled") is False
                    and head and head.get("job_id") == identifier and head.get("decision_id") == job["decision_id"]
                    and basis == job["basis_hash"] and preview["decision"] in NOTIFIABLE
                    and preview_hash(preview) == job["preview_hash"])
                updated = {**job, "checked_at": stamp(now), "queue_key": PENDING_PREFIX+stamp(now)+"|"+identifier} if valid else _invalidate(job, "current_basis_unavailable_or_changed", now)
                return {identifier: updated}, False, {"state": updated["state"], "dispatch_enabled": False}
            try:
                return store.run_record(rid, [identifier, hid, CONFIG_KEY], validate)
            except RecordConflict:
                continue
        raise RecordConflict("발송 대기 작업 확인 중 변경이 이어졌습니다.")

    def read_record(self, identifier):
        if not self.enabled:
            return {"state": "disabled", "dispatch_enabled": False}
        store = self.store_factory()
        head = store.get(head_key(identifier))
        if not head:
            return {"state": "unprepared", "dispatch_enabled": False}
        decision = store.get(head["decision_id"])
        job = store.get(head["job_id"]) if head.get("job_id") else None
        return {"state": job["state"] if job else head["state"],
                "dispatch_enabled": False, "decision": decision, "job": job}

    def run(self, limit=20):
        if not self.enabled:
            return {"state": "disabled"}
        if not 1 <= limit <= 50:
            raise ValueError("notification_batch_limit")
        self.activate()
        store = self.store_factory()
        pending = store.scan(PENDING_PREFIX, PENDING_PREFIX+"~", limit)
        for job in pending:
            self.validate_pending(job["id"])
        dirty = self.records.store.list_notification_dirty(limit)
        for record in dirty:
            self.prepare_record(record["id"])
        if self.fallback_enabled:
            visited = {r["id"] for r in dirty}
            for watch in store.scan("NW|", "NW|~", limit):
                if watch["record_id"] not in visited:
                    self.prepare_record(watch["record_id"])
        return {"state": "preview", "checked_pending": len(pending), "scanned_dirty": len(dirty), "dispatch_enabled": False}
