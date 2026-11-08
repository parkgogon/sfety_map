"""관리자 재난문자 원본·분석 기록. 기상/발송 상태와 독립된 저장 경계."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import threading
import uuid
import logging
from collections.abc import Callable
from typing import Annotated, Literal, Protocol

from pydantic import AwareDatetime, Field

from safety_dashboard.application.context_info import KST
from safety_dashboard.application.message_analysis import AnalysisBusy, MessageAnalysisInput, StrictModel


class RecordConflict(ValueError):
    pass


def ensure_record_editable(record):
    if record["review_state"] == "completed":
        raise RecordConflict("완료한 검토입니다. 사유를 적어 다시 연 뒤 수정해 주세요.")


def invalidate_review(record, reason):
    record.pop("review_preparation", None)
    if record.get("review_completion") or record.get("notice_draft"):
        record.update(review_completion=None, notice_draft=None, review_reset_reason=reason)
        if record["review_state"] == "completed":
            record["review_state"] = "needs_confirmation"


class RecordNotFound(KeyError):
    pass


class RecordStorageUnavailable(RuntimeError):
    pass


class MessageSource(StrictModel):
    text: str = Field(min_length=10, max_length=2000)
    source: str = Field(min_length=1, max_length=80)
    issued_at: AwareDatetime | None = None
    recipient_regions: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(default_factory=list, max_length=30)

    def canonical(self):
        if any(not value.strip() or len(value) > 120 for value in self.recipient_regions):
            raise ValueError("수신지역은 항목당 1~120자로 입력해 주세요.")
        value = self.model_dump(mode="json")
        value["issued_at"] = self.issued_at.astimezone(KST).isoformat() if self.issued_at else None
        value["recipient_regions"] = list(dict.fromkeys(r.strip() for r in self.recipient_regions))
        return value


class RegisterMessage(MessageSource):
    registration_key: uuid.UUID
    input_kind: Literal["manual", "example"] = "manual"
    reference_radius_km: Literal[1, 3, 5, 10] = 3

    def canonical(self):
        return MessageSource(**{key: getattr(self, key) for key in MessageSource.model_fields}).canonical()


class RecordVersion(StrictModel):
    expected_version: int = Field(ge=1)


class SaveRecordNote(RecordVersion):
    review_state: Literal["unreviewed", "needs_confirmation"]
    note: str = Field(default="", max_length=1000)


class AnalyzeRecord(RecordVersion):
    reference_radius_km: Literal[1, 3, 5, 10] = 3


class RecordStore(Protocol):
    def get(self, identifier: str) -> dict | None: ...
    def get_many(self, identifiers: list[str]) -> dict[str, dict]: ...
    def list_page(self, before: str | None, limit: int) -> list[dict]: ...
    def commit(self, record: dict, expected: int, event: str) -> dict: ...
    def history(self, identifier: str, before: int | None, limit: int) -> list[dict]: ...
    def observe_official(self, identifier: str, digest: str, fetched_at: str) -> dict | None: ...


def content_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def newer_observation(left, right):
    return bool(left and (not right or dt.datetime.fromisoformat(left) > dt.datetime.fromisoformat(right)))


def preserve_observation(record, current):
    """Non-versioned poll metadata must survive concurrent semantic writes."""
    saved = copy.deepcopy(record)
    if current and newer_observation(current.get("official_fetched_at"), record.get("official_fetched_at")):
        if current["content_hash"] != record["content_hash"]:
            raise RecordConflict("더 오래된 조회 결과입니다. 공식 문자를 다시 조회해 주세요.")
        saved["official_fetched_at"] = current["official_fetched_at"]
    return saved


class MemoryRecordStore:
    """명시적인 로컬/테스트용. 운영 Firestore 실패 시 대체하지 않는다."""
    def __init__(self):
        self.records, self.versions = {}, {}
        self.lock = threading.RLock()

    def get(self, identifier):
        with self.lock:
            return copy.deepcopy(self.records.get(identifier))

    def get_many(self, identifiers):
        with self.lock:
            return copy.deepcopy({key: self.records[key] for key in identifiers if key in self.records})

    def list_page(self, before, limit):
        with self.lock:
            rows = sorted(self.records.values(), key=lambda r: r["sort_key"], reverse=True)
            return copy.deepcopy([r for r in rows if not before or r["sort_key"] < before][:limit])

    def commit(self, record, expected, event):
        with self.lock:
            current = self.records.get(record["id"])
            if (current["version"] if current else 0) != expected:
                raise RecordConflict("기록이 변경됐습니다. 다시 불러온 뒤 진행해 주세요.")
            saved = preserve_observation(record, current)
            saved["version"] = expected + 1
            self.records[saved["id"]] = saved
            self.versions.setdefault(saved["id"], []).append({"event": event, "record": copy.deepcopy(saved)})
            return copy.deepcopy(saved)

    def observe_official(self, identifier, digest, fetched_at):
        with self.lock:
            current = self.records.get(identifier)
            if not current or current["content_hash"] != digest:
                return None
            if newer_observation(fetched_at, current.get("official_fetched_at")):
                current["official_fetched_at"] = fetched_at
            return copy.deepcopy(current)

    def history(self, identifier, before, limit):
        with self.lock:
            return copy.deepcopy([v for v in reversed(self.versions.get(identifier, []))
                                  if before is None or v["record"]["version"] < before][:limit])


class MessageRecordService:
    def __init__(self, store_factory: Callable[[], RecordStore] | None, analysis, *,
                 storage_mode="disabled", now=lambda: dt.datetime.now(KST), facility_digest=lambda: "",
                 on_analysis_saved=None):
        self.store_factory, self.analysis = store_factory, analysis
        self.storage_mode, self.now, self.facility_digest = storage_mode, now, facility_digest
        self.on_analysis_saved = on_analysis_saved
        self._store = None
        self._store_lock = threading.Lock()

    @property
    def store(self):
        if not self.store_factory:
            raise RecordStorageUnavailable("검토 기록 저장소가 설정되지 않았습니다.")
        with self._store_lock:
            if self._store is None:
                self._store = self.store_factory()
        return self._store

    def availability(self):
        return {"storage_configured": self.store_factory is not None, "storage_mode": self.storage_mode}

    def get(self, identifier):
        record = self.store.get(identifier)
        if record is None:
            raise RecordNotFound(identifier)
        return record

    def list_page(self, before=None, limit=20):
        rows = self.store.list_page(before, limit + 1)
        return {"records": [self.summary(r) for r in rows[:limit]],
                "next_cursor": rows[limit - 1]["sort_key"] if len(rows) > limit else None}

    @staticmethod
    def summary(record):
        return {key: record[key] for key in ("id", "version", "origin", "message", "created_at", "updated_at",
                                            "source_revision", "analysis_state", "review_state", "note")}

    def register_manual(self, request: RegisterMessage):
        return self._register("manual-" + request.registration_key.hex, request.input_kind, request.canonical(),
                              request.reference_radius_km)

    def register_official(self, message: dict, official_id: str, fetched_at: str):
        # Only trusted server feed content enters this path.
        return self._register(self.official_record_id(official_id), "official", message, 3,
                              official_id=official_id, fetched_at=fetched_at)

    @staticmethod
    def official_record_id(official_id):
        return "official-" + hashlib.sha256(official_id.encode()).hexdigest()

    def _register(self, identifier, origin, message, radius, *, official_id=None, fetched_at=None):
        digest = content_hash(message)
        for _ in range(3):
            existing = self.store.get(identifier)
            if existing and existing["content_hash"] == digest:
                # Observing identical content later must also prevent a stale feed token
                # from rolling the source back to an older, different snapshot.
                if fetched_at:
                    existing = self.store.observe_official(identifier, digest, fetched_at)
                    if existing is None:
                        continue
                return {"record": existing, "registration": "unchanged"}
            if existing and origin != "official":
                raise RecordConflict("같은 등록 요청의 내용이 다릅니다. 새 문자로 등록해 주세요.")
            if existing and newer_observation(existing.get("official_fetched_at"), fetched_at):
                raise RecordConflict("더 오래된 조회 결과입니다. 공식 문자 목록을 새로 불러와 주세요.")
            now = self.now().isoformat()
            record = {"id": identifier, "origin": origin, "official_id": official_id, "message": message,
                      "content_hash": digest, "official_fetched_at": fetched_at, "source_revision": existing["source_revision"] + 1 if existing else 1,
                      "version": 0, "created_at": existing["created_at"] if existing else now, "updated_at": now,
                      "sort_key": existing["sort_key"] if existing else f"{now}|{identifier}", "reference_radius_km": radius,
                      "analysis_state": "not_analyzed", "analysis": None, "analysis_revision": existing["analysis_revision"] if existing else 0,
                      "analysis_source_revision": None, "analysis_error": "", "analysis_operation": None,
                      "analysis_started_at": None, "review_state": "needs_confirmation" if existing else "unreviewed",
                      "analysis_attempt_source_revision": None, "analysis_attempted_at": None,
                      "note": existing["note"] if existing else "", "spatial_references": {},
                      "spatial_reset_reason": "source_changed" if existing and existing.get("spatial_references") else "",
                      "review_completion": None, "notice_draft": None, "notice_draft_revision": existing.get("notice_draft_revision", 0) if existing else 0,
                      "review_reset_reason": "source_changed" if existing and existing.get("review_completion") else ""}
            record["relation_order"] = existing.get("relation_order", [existing["created_at"], existing["id"]]) if existing else [
                dt.datetime.fromisoformat(message["issued_at"] or now).astimezone(dt.timezone.utc).isoformat(), now, identifier]
            for key, default in (("related_messages", {}), ("relation_epoch", 0), ("relation_last_change", None)):
                record[key] = copy.deepcopy(existing.get(key, default) if existing else default)
            try:
                saved = self.store.commit(record, existing["version"] if existing else 0,
                                          "source_changed" if existing else "registered")
                return {"record": saved, "registration": "updated" if existing else "created"}
            except RecordConflict:
                continue
        raise RecordConflict("등록 중 다른 변경이 있었습니다. 다시 불러와 주세요.")

    def _save(self, record, expected, event):
        if event in {"note_saved", "analysis_started", "reference_saved", "reference_confirmed", "facilities_selected",
                     "message_linked", "message_reconfirmed", "message_unlinked"}:
            invalidate_review(record, event)
        record["updated_at"] = self.now().isoformat()
        # Creation order is stable while paging; updates do not move records between pages.
        return self.store.commit(record, expected, event)

    def save_note(self, identifier, request: SaveRecordNote):
        record = self.get(identifier)
        ensure_record_editable(record)
        if record["version"] != request.expected_version:
            raise RecordConflict("기록이 변경됐습니다. 다시 불러온 뒤 저장해 주세요.")
        record.update(review_state=request.review_state, note=request.note)
        return self._save(record, request.expected_version, "note_saved")

    def analyze(self, identifier, request: AnalyzeRecord):
        record = self.get(identifier)
        ensure_record_editable(record)
        if record["version"] != request.expected_version:
            raise RecordConflict("기록이 변경됐습니다. 다시 불러온 뒤 분석해 주세요.")
        if record["analysis_state"] == "running" and record["analysis_started_at"]:
            age = (self.now() - dt.datetime.fromisoformat(record["analysis_started_at"])).total_seconds()
            if age < 120:
                raise AnalysisBusy("이미 분석 중입니다. 잠시 후 기록을 다시 불러와 주세요.")
        operation = uuid.uuid4().hex
        previous = {key: copy.deepcopy(record.get(key)) for key in (
            "analysis_state", "analysis_error", "analysis_operation", "analysis_started_at",
            "analysis_attempt_source_revision", "analysis_attempted_at", "reference_radius_km")}
        record.update(analysis_state="running", analysis_operation=operation,
                      analysis_started_at=self.now().isoformat(), reference_radius_km=request.reference_radius_km,
                      analysis_error="", analysis_attempt_source_revision=record["source_revision"],
                      analysis_attempted_at=self.now().isoformat())
        started = self._save(record, request.expected_version, "analysis_started")
        try:
            digest = self.facility_digest()
            result = self.analysis.analyze(MessageAnalysisInput(**started["message"],
                reference_radius_km=request.reference_radius_km, input_kind=started["origin"]))
        except AnalysisBusy:
            self._restore_rejected_analysis(identifier, operation, previous)
            raise
        except Exception:
            self._finish_analysis(identifier, operation, None, "", "분석을 완료하지 못했습니다. 마지막 저장 결과는 유지됩니다.")
            raise
        return self._finish_analysis(identifier, operation, result, digest, "")

    def _restore_rejected_analysis(self, identifier, operation, previous):
        for _ in range(3):
            record = self.get(identifier)
            if record["analysis_operation"] != operation:
                return
            expected = record["version"]
            record.update(previous)
            try:
                self._save(record, expected, "analysis_deferred")
                return
            except RecordConflict:
                continue
        raise RecordConflict("분석 대기 상태 저장 중 변경이 있었습니다.")

    def mark_analysis_interrupted(self, identifier, operation):
        for _ in range(3):
            record = self.get(identifier)
            if record["analysis_state"] != "running" or record["analysis_operation"] != operation:
                return
            expected = record["version"]
            record.update(analysis_state="failed", analysis_operation=None, analysis_started_at=None,
                          analysis_error="중단된 분석의 결과를 확인하지 못했습니다. 자동 재시도하지 않으며, 내용을 확인한 뒤 직접 다시 분석할 수 있습니다.")
            try:
                self._save(record, expected, "analysis_interrupted")
                return
            except RecordConflict:
                continue
        raise RecordConflict("중단된 분석 상태 저장 중 변경이 있었습니다.")

    def _finish_analysis(self, identifier, operation, result, digest, error):
        for _ in range(3):
            record = self.get(identifier)
            if record["analysis_operation"] != operation:
                raise RecordConflict("분석 도중 원문 또는 실행이 변경됐습니다. 최신 기록을 확인해 주세요.")
            expected = record["version"]
            record.update(analysis_state="failed" if error else "completed", analysis_error=error,
                          analysis_operation=None, analysis_started_at=None)
            if result is not None:
                if record.get("spatial_references"):
                    record.update(spatial_references={}, spatial_reset_reason="analysis_changed")
                record.update(analysis=result, analysis_revision=record["analysis_revision"] + 1,
                              analysis_source_revision=record["source_revision"], facility_digest=digest,
                              review_state="needs_confirmation" if record["analysis_revision"] else record["review_state"])
            try:
                saved = self._save(record, expected, "analysis_failed" if error else "analysis_completed")
                if result is not None and self.on_analysis_saved:
                    try:
                        self.on_analysis_saved(saved)
                    except Exception:
                        logging.getLogger(__name__).warning("message_analysis_queue_sync_failed")
                return saved
            except RecordConflict:
                continue
        raise RecordConflict("분석 결과 저장 중 변경이 있었습니다. 기록을 다시 불러와 주세요.")
