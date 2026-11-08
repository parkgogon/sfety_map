"""재난문자 내부 검토 완료·재열기와 근거 기반 안내 초안. AI/발송 호출 없음."""
from __future__ import annotations

import copy
import datetime as dt
from typing import Literal
from pydantic import Field
from safety_dashboard.application.context_info import KST
from safety_dashboard.application.message_analysis import StrictModel
from safety_dashboard.application.message_records import RecordConflict, RecordVersion, content_hash, ensure_record_editable
from safety_dashboard.application.message_spatial import LocationKey, MessageSpatialService, message_locations
from safety_dashboard.application.nearby_report import NearbyReport, distance_meters
from safety_dashboard.domain.models import GeoPoint

TEMPLATE_VERSION = 1


class ReviewValidationError(ValueError):
    """관리자에게 표시할 수 있는 검토 입력 오류."""


class ExcludedLocation(StrictModel):
    location_key: LocationKey
    reason: str = Field(min_length=1, max_length=500)


class CompleteMessageReview(RecordVersion):
    outcome: Literal["facilities_selected", "no_action"]
    reason: str = Field(min_length=1, max_length=1000)
    follow_up_note: str = Field(default="", max_length=1000)
    excluded_locations: list[ExcludedLocation] = Field(default_factory=list, max_length=100)


class ReopenMessageReview(RecordVersion):
    reason: str = Field(min_length=1, max_length=1000)


class SaveMessageNotice(RecordVersion):
    draft_revision: int = Field(ge=1)
    manager_note: str = Field(default="", max_length=2000)


class CopyMessageNotice(RecordVersion):
    draft_revision: int = Field(ge=1)


def korean_time(value):
    if not value:
        return "명시되지 않음"
    return dt.datetime.fromisoformat(value).astimezone(KST).strftime("%Y-%m-%d %H:%M") + " (한국 시간)"


class MessageReviewService:
    def __init__(self, records, catalog):
        self.records, self.catalog = records, catalog

    def _snapshot(self, record):
        MessageSpatialService._ready(record)
        locations = [l for l in message_locations(record) if l["eligible"]]
        refs = record.get("spatial_references", {})
        eligible = {l["key"]: l for l in locations}
        if set(refs) - set(eligible):
            raise RecordConflict("분석 장소와 저장한 기준이 다릅니다. 검토 기준을 다시 확인해 주세요.")
        digest, facilities = self.catalog() if refs else (None, ())
        by_id = {f.id: f for f in facilities}
        contexts = []
        for key, location in eligible.items():
            ref = refs.get(key)
            context = {"key": key, "text": location["text"], "role": location["role"], "reference": None, "selected": []}
            if ref:
                if (ref["catalog_digest"] != digest or ref["analysis_revision"] != record["analysis_revision"]
                        or ref["source_revision"] != record["source_revision"]):
                    raise RecordConflict("조회 기준 또는 시설 자료가 바뀌었습니다. 기준점을 다시 조회하고 시설을 재선정해 주세요.")
                point = GeoPoint(ref["point"]["latitude"], ref["point"]["longitude"])
                report = NearbyReport.build(point, ref["point"]["label"], ref["point"]["address"], ref["radius_km"], facilities)
                ids = [f["id"] for f in ref["selected"]]
                if (len(ids) != len(set(ids)) or any(identifier not in by_id for identifier in ids)
                        or ids and (not ref["selection_saved_at"] or ref["selection_needs_review"] or not ref["selection_note"])):
                    raise RecordConflict("현재 기준의 시설 선정을 저장한 뒤 검토를 완료해 주세요.")
                for old in ref["selected"]:
                    facility = by_id[old["id"]]
                    distance = distance_meters(point, facility.location)
                    inside = distance <= ref["radius_km"] * 1000
                    if not inside and not old.get("reason"):
                        raise ReviewValidationError("반경 밖 시설의 추가 사유를 확인해 주세요.")
                    context["selected"].append({"id": facility.id, "name": facility.name, "facility_type": facility.facility_type,
                        "address": facility.address, "distance_m": round(distance), "within_radius": inside, "reason": old.get("reason", "")})
                context["reference"] = {"revision": ref["revision"], "point": copy.deepcopy(ref["point"]), "radius_km": ref["radius_km"],
                    "confirmation_note": ref["confirmation_note"], "selection_note": ref["selection_note"], "nearby_count": len(report.facilities)}
            contexts.append(context)
        snapshot = {"origin": record["origin"], "official_id": record.get("official_id"), "message": copy.deepcopy(record["message"]),
            "source_revision": record["source_revision"], "analysis_revision": record["analysis_revision"],
            "analysis": copy.deepcopy(record["analysis"]["analysis"]), "record_note": record["note"],
            "catalog_digest": digest, "locations": contexts}
        basis = content_hash({"snapshot": snapshot, "content_hash": record["content_hash"], "references": refs})
        return snapshot, basis

    def detail(self, identifier):
        record = self.records.get(identifier)
        completion, draft = record.get("review_completion"), record.get("notice_draft")
        error, basis = "", None
        try:
            _, basis = self._snapshot(record)
        except (ValueError, RecordConflict) as reason:
            error = str(reason) if isinstance(reason, (RecordConflict, ReviewValidationError)) else "현재 분석·조회 기준·시설 자료를 확인해 주세요."
        except Exception:
            error = "검토 근거를 조회하지 못했습니다. 다시 불러온 뒤 진행해 주세요."
        current = bool(record["review_state"] == "completed" and completion and basis == completion["basis_hash"])
        draft_current = bool(current and draft and draft["basis_hash"] == basis and draft["template_version"] == TEMPLATE_VERSION)
        if record["review_state"] == "completed" and not current and not error:
            error = "검토 근거가 변경됐습니다. 다시 열어 검토해 주세요."
        return {"record_version": record["version"], "review_state": record["review_state"], "completion": completion,
            "completion_current": current, "draft": draft, "draft_current": draft_current, "stale_reason": error,
            "locations": [{"key": l["key"], "text": l["text"], "selected_count": len(record.get("spatial_references", {}).get(l["key"], {}).get("selected", []))}
                          for l in message_locations(record) if l["eligible"]]}

    def complete(self, identifier, request: CompleteMessageReview):
        record = self.records.get(identifier)
        if record["version"] != request.expected_version:
            raise RecordConflict("기록이 변경됐습니다. 최신 기록을 다시 불러와 주세요.")
        ensure_record_editable(record)
        snapshot, basis = self._snapshot(record)
        selected_ids = {f["id"] for loc in snapshot["locations"] for f in loc["selected"]}
        exclusions = {item.location_key: item.reason for item in request.excluded_locations}
        if len(exclusions) != len(request.excluded_locations):
            raise ReviewValidationError("장소별 미선정 사유를 중복 없이 입력해 주세요.")
        if request.outcome == "facilities_selected":
            if not selected_ids:
                raise ReviewValidationError("업무 대상 시설을 1개소 이상 선정·저장해 주세요.")
            missing = {l["key"] for l in snapshot["locations"] if not l["selected"]}
            if set(exclusions) != missing:
                raise ReviewValidationError("다른 사고·통제 장소를 선정하지 않은 사유도 입력해 주세요.")
        elif selected_ids:
            raise ReviewValidationError("선정 시설이 남아 있습니다. 선정을 해제하거나 확인 대상 선정으로 완료해 주세요.")
        elif exclusions:
            raise ReviewValidationError("추가 조치 없음의 사유는 전체 검토 사유에 입력해 주세요.")
        now = self.records.now().isoformat()
        record["review_completion"] = {"outcome": request.outcome, "reason": request.reason, "follow_up_note": request.follow_up_note,
            "excluded_locations": exclusions, "completed_at": now, "basis_hash": basis,
            "selected_unique_count": len(selected_ids), "snapshot": snapshot}
        record["review_state"] = "completed"
        record["review_reset_reason"] = ""
        self._set_draft(record, "")
        return self.records._save(record, request.expected_version, "review_completed")

    def reopen(self, identifier, request: ReopenMessageReview):
        record = self.records.get(identifier)
        if record["version"] != request.expected_version or record["review_state"] != "completed":
            raise RecordConflict("현재 완료된 검토를 다시 불러온 뒤 열어 주세요.")
        record.update(review_state="needs_confirmation", review_completion=None, notice_draft=None,
                      review_reset_reason="reopened", review_reopen_reason=request.reason, review_reopened_at=self.records.now().isoformat())
        return self.records._save(record, request.expected_version, "review_reopened")

    def _current_draft(self, identifier, expected_version, draft_revision):
        record = self.records.get(identifier)
        if record["version"] != expected_version:
            raise RecordConflict("기록이 변경됐습니다. 초안을 다시 불러와 주세요.")
        completion, draft = record.get("review_completion"), record.get("notice_draft")
        if record["review_state"] != "completed" or not completion or not draft:
            raise RecordConflict("검토를 완료한 뒤 현재 초안을 확인해 주세요.")
        _, basis = self._snapshot(record)
        if (completion["basis_hash"] != basis or draft["basis_hash"] != basis
                or draft["revision"] != draft_revision or draft["template_version"] != TEMPLATE_VERSION):
            raise RecordConflict("초안의 근거 또는 버전이 바뀌었습니다. 다시 검토한 뒤 초안을 확인해 주세요.")
        return record

    def save_draft(self, identifier, request: SaveMessageNotice):
        record = self._current_draft(identifier, request.expected_version, request.draft_revision)
        if request.manager_note == record["notice_draft"]["manager_note"]:
            return record
        self._set_draft(record, request.manager_note)
        return self.records._save(record, request.expected_version, "notice_updated")

    def copy_draft(self, identifier, request: CopyMessageNotice):
        record = self._current_draft(identifier, request.expected_version, request.draft_revision)
        # This validates a copy request; browser clipboard success and actual delivery are separate.
        draft = record["notice_draft"]
        return {"text": draft["text"], "draft_revision": draft["revision"], "record_version": record["version"]}

    def _set_draft(self, record, manager_note):
        revision = record.get("notice_draft_revision", 0) + 1
        text = render_notice(record["review_completion"], manager_note, revision)
        if len(text) > 40000:
            raise ReviewValidationError("초안 분량이 한도를 넘었습니다. 선정 범위와 안내 내용을 검토해 주세요.")
        record["notice_draft_revision"] = revision
        record["notice_draft"] = {"revision": revision, "template_version": TEMPLATE_VERSION,
            "basis_hash": record["review_completion"]["basis_hash"], "manager_note": manager_note,
            "text": text, "updated_at": self.records.now().isoformat()}


def render_notice(completion, manager_note, revision):
    snapshot = completion["snapshot"]
    message, analysis = snapshot["message"], snapshot["analysis"]
    origin = {"example": "창작 예문 · 실제 재난/업무 실적 아님", "manual": "수동 입력 문자", "official": "공식 API에서 불러온 문자"}[snapshot["origin"]]
    outcome = "확인 대상 선정" if completion["outcome"] == "facilities_selected" else "추가 조치 없음 (관리자 검토 판단)"
    lines = ["[재난문자 검토 안내 초안]", f"초안 {revision}판 · 원문 {snapshot['source_revision']}판 · 분석 {snapshot['analysis_revision']}판", f"입력 구분: {origin}", f"출처: {message['source']}",
        f"문자 발행: {korean_time(message['issued_at'])}", f"수신지역: {', '.join(message['recipient_regions']) or '미상'}",
        f"내부 검토 완료: {korean_time(completion['completed_at'])}", f"검토 결과: {outcome}", f"검토 사유: {completion['reason']}",
        "", "■ 문자 원문", message["text"], "", "■ 문자 발행 시점의 구간별 해석"]
    if snapshot.get("official_id"):
        lines.insert(4, f"공식 문자 ID: {snapshot['official_id']}")
    labels = {"event": "발생", "prevention": "예방", "advisory": "안내", "scheduled_restriction": "예정 통제",
        "active_restriction": "통제 유지", "release": "해제", "correction": "정정", "unknown": "판단 보류"}
    roles = {"incident_site": "발생 장소", "restricted_area": "통제 장소", "evacuation_destination": "대피 목적지",
        "evacuation_area": "대피 대상 지역", "reference": "참고 장소"}
    for index, part in enumerate(analysis.get("parts", []), 1):
        lines += [f"{index}. {labels.get(part['intent'], part['intent'])}: {part.get('evidence', '')}"]
        if part.get("starts_at"): lines.append(f"   시작: {korean_time(part['starts_at'])}")
        if part.get("ends_at"): lines.append(f"   종료/해제: {korean_time(part['ends_at'])}")
        for loc in part.get("locations", []): lines.append(f"   {roles.get(loc['role'], loc['role'])}: {loc['text']}")
    lines += ["", f"■ 업무 확인 대상 (중복 제외 {completion['selected_unique_count']}개소)"]
    for loc in snapshot["locations"]:
        if not loc["selected"]:
            if loc["key"] in completion["excluded_locations"]:
                lines.append(f"미선정 장소: {loc['text']} · {completion['excluded_locations'][loc['key']]}")
            continue
        ref = loc["reference"]
        lines += [f"조회 기준: {ref['point']['label']} · 참고 거리 {ref['radius_km']}km",
                  f"기준점 확인 근거: {ref['confirmation_note']}", f"시설 선정 사유: {ref['selection_note']}"]
        for f in loc["selected"]:
            lines.append(f"- {f['name']} [{f['id']}] · {f['facility_type']} · 직선 {f['distance_m'] / 1000:.2f}km · {f['address']}")
            if not f["within_radius"]: lines.append(f"  반경 밖 추가 사유: {f['reason']}")
    if completion["outcome"] == "no_action": lines.append("이 검토에서 업무 확인 대상으로 선정한 시설은 없습니다.")
    lines += ["", "■ 확인 질문·관리자 보완 기록"]
    questions = analysis.get("questions", [])
    lines += [f"- 분석 시 제시된 질문: {q}" for q in questions]
    if not questions: lines.append("분석에서 별도 질문이 제시되지 않았습니다.")
    if snapshot["record_note"]: lines.append(f"검토 메모: {snapshot['record_note']}")
    default_follow_up = "별도 보완 기록 없음." + (" 질문의 해결 여부는 추가 확인이 필요합니다." if questions else "")
    lines.append(f"관리자 보완: {completion['follow_up_note'] or default_follow_up}")
    if manager_note: lines += ["", "■ 관리자 추가 안내", manager_note]
    lines += ["", "※ 내부 검토 완료는 재난 종료·시설 안전·현장 확인 완료를 뜻하지 않습니다.",
        "※ 조회 거리는 참고용이며 피해 범위가 아닙니다. 현재 상황과 후속 정정·해제는 별도로 확인해 주세요.",
        "※ 이 문서는 전달 전 검토용 초안이며 실제 발송·수신 기록이 아닙니다."]
    return "\n".join(lines)
