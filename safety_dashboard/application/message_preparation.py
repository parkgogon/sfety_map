"""Read-only recommendations and one atomic, explicitly approved review commit."""
from __future__ import annotations

import copy
import re
from typing import Literal

from pydantic import Field

from safety_dashboard.application.message_analysis import StrictModel
from safety_dashboard.application.message_records import RecordConflict, RecordVersion, content_hash, ensure_record_editable
from safety_dashboard.application.message_review import CompleteMessageReview, ReviewValidationError, render_brief_notice
from safety_dashboard.application.message_spatial import (
    Digest, LocationKey, MessageSpatialService, ReferencePointInput, SelectedFacilityInput, message_locations,
)

REASONS = {
    "reference_only": "원문과 참고 자료를 검토하고 추가 업무 대상 없이 기록함",
    "outside_scope": "이번 업무 검토 대상에서 제외함",
    "other": "관리자가 별도 사유를 남김",
}


class PreparedLocationChoice(StrictModel):
    location_key: LocationKey
    point: ReferencePointInput | None = None
    radius_km: Literal[1, 3, 5, 10] | None = None
    facilities: list[SelectedFacilityInput] | None = Field(default=None, max_length=195)
    reference_acknowledged: bool = False
    excluded_reason: Literal["reference_only", "outside_scope", "other"] | None = None
    note: str = Field(default="", max_length=500)


class PrepareMessageReview(RecordVersion):
    choices: list[PreparedLocationChoice] = Field(default_factory=list, max_length=48)
    outcome: Literal["facilities_selected", "no_action"] | None = None
    no_action_reason: Literal["reference_only", "outside_scope", "other"] | None = None
    manager_note: str = Field(default="", max_length=2000)
    uncertainty_acknowledged: bool = False


class ApprovePreparedReview(PrepareMessageReview):
    proposal_hash: Digest
    confirmed: Literal[True]


class MessagePreparationService:
    def __init__(self, review):
        self.review, self.records, self.catalog = review, review.records, review.catalog

    def prepare(self, identifier, request: PrepareMessageReview):
        record = self.records.get(identifier)
        return self._build(record, request)[0]

    def _build(self, record, request):
        MessageSpatialService._ready(record, request.expected_version)
        ensure_record_editable(record)
        # A preview never writes confirmation timestamps or selected facilities.
        draft = copy.deepcopy(record)
        draft.pop("review_preparation", None)
        digest, facilities = self.catalog()
        spatial = MessageSpatialService(self.records, lambda: (digest, facilities))
        locations = [l for l in message_locations(record) if l["eligible"]]
        keys = {l["key"] for l in locations}
        overrides = {c.location_key: c for c in request.choices}
        if len(overrides) != len(request.choices) or set(overrides)-keys:
            raise ReviewValidationError("현재 사고·통제 장소를 중복 없이 지정해 주세요.")
        contexts, proposed_refs, recommendations, issues = [], {}, [], []
        for loc in locations:
            local_issues = []
            key = loc["key"]
            choice = overrides.get(key, PreparedLocationChoice(location_key=key))
            candidates = [c for c in record["analysis"].get("candidates", [])
                          if c["id"] in loc.get("candidate_ids", []) and c.get("role") == loc["role"]]
            matching = [c for c in candidates if c.get("scope_matches_source")]
            recommendation = {"location_key": key, "point": None, "radius_km": record["reference_radius_km"],
                              "facility_ids": [], "basis": "원문 장소 후보와 CSV 참고 거리 계산"}
            if len(matching) == 1:
                recommendation["point"] = self._candidate_point(matching[0])
                _, suggested_rows = spatial._rows(recommendation)
                recommendation["facility_ids"] = [r["id"] for r in suggested_rows if r["within_radius"]]
            recommendations.append(recommendation)
            saved = record.get("spatial_references", {}).get(key)
            valid_saved = bool(saved and saved["analysis_revision"] == record["analysis_revision"]
                               and saved["source_revision"] == record["source_revision"])
            point_input = choice.point
            position = None
            if point_input:
                if point_input.mode == "candidate":
                    candidate = next((c for c in candidates if c["id"] == point_input.candidate_id), None)
                    if not candidate or point_input.latitude is not None or point_input.longitude is not None or point_input.label:
                        raise ReviewValidationError("이 장소에 속하는 원본 후보를 선택해 주세요.")
                    position = self._candidate_point(candidate)
                else:
                    if point_input.candidate_id or point_input.latitude is None or point_input.longitude is None:
                        raise ReviewValidationError("관리자 지정 위치의 위도·경도를 확인해 주세요.")
                    position = {"latitude": point_input.latitude, "longitude": point_input.longitude,
                                "label": point_input.label or loc["text"][:80], "address": "", "source": point_input.manual_source,
                                "candidate_id": None, "scope_matches_source": False}
            elif valid_saved:
                position = copy.deepcopy(saved["point"])
            elif len(matching) == 1:
                position = self._candidate_point(matching[0])
            radius = choice.radius_km or (saved["radius_km"] if valid_saved else record["reference_radius_km"])
            if not position:
                local_issues.append(f"{loc['text']}: 조회할 위치를 선택하거나 지도에서 보완해 주세요.")
            candidate = next((c for c in candidates if position and c["id"] == position.get("candidate_id")), {})
            representative = candidate.get("place_kind") in {"industrial_complex", "mountain", "road"} or bool(re.search(r"인근|일대|일원|부근|구간", loc.get("evidence", "")))
            changed = not valid_saved or position != saved["point"] or radius != saved["radius_km"] or saved["catalog_digest"] != digest
            catalog_changed = bool(valid_saved and saved["catalog_digest"] != digest)
            needs_ack = bool(position and changed and (representative or catalog_changed or not position.get("scope_matches_source")))
            if needs_ack and not choice.reference_acknowledged:
                local_issues.append(f"{loc['text']}: "+("시설 자료가 바뀌었습니다. 재계산한 위치·대상을 확인해 주세요." if catalog_changed else "표시한 위치를 참고 조회 기준으로 사용할지 확인해 주세요."))
            rows, selected, removed = [], [], []
            if position:
                ref = {"location_key": key, "point": position, "radius_km": radius}
                _, rows = spatial._rows(ref)
                by_id = {row["id"]: row for row in rows}
                default_ids = [row["id"] for row in rows if row["within_radius"]]
                selected_input = choice.facilities
                if selected_input is None:
                    if valid_saved:
                        removed = [{"id":f["id"],"name":f["name"]} for f in saved["selected"] if f["id"] not in by_id]
                    selected_input = ([SelectedFacilityInput(facility_id=f["id"], reason=f.get("reason", "")) for f in saved["selected"]]
                                      if valid_saved and position == saved["point"] and radius == saved["radius_km"] else [SelectedFacilityInput(facility_id=id) for id in default_ids])
                    selected_input = [f for f in selected_input if f.facility_id in by_id]
                ids = [f.facility_id for f in selected_input]
                if len(ids) != len(set(ids)) or any(id not in by_id for id in ids):
                    raise ReviewValidationError("현재 시설 자료의 ID를 중복 없이 선택해 주세요.")
                for f in selected_input:
                    row = by_id[f.facility_id]
                    if not row["within_radius"] and not f.reason:
                        local_issues.append(f"{row['name']}: 반경 밖 추가 사유를 선택해 주세요.")
                    selected.append({**row, "reason": f.reason})
                proposed_refs[key] = {"location_key": key, "role": loc["role"], "evidence": loc["evidence"],
                    "point": position, "radius_km": radius, "analysis_revision": record["analysis_revision"],
                    "source_revision": record["source_revision"], "revision": (saved["revision"] if valid_saved else 0)+1,
                    "catalog_digest": digest, "nearby_count": len(default_ids), "selected": selected,
                    "confirmation_note": (saved["confirmation_note"] if valid_saved and not changed else "화면의 위치와 참고 거리를 확인하고 내부 검토에 사용"),
                    "selection_note": "CSV 참고 거리 안 시설 제안을 검토함" if choice.facilities is None else "관리자가 화면에서 확인 대상을 수정함",
                    "confirmed_at": None, "selection_saved_at": None, "selection_needs_review": False}
            elif choice.facilities:
                raise ReviewValidationError("위치를 정한 뒤 시설을 선택해 주세요.")
            excluded = REASONS.get(choice.excluded_reason)
            if choice.excluded_reason == "other":
                excluded = choice.note or None
            if not selected and not excluded:
                local_issues.append(f"{loc['text']}: 확인 대상을 추가하거나 이번 검토에서 제외할 사유를 선택해 주세요.")
            # A deliberate exclusion does not require inventing a point.
            if excluded and not selected:
                local_issues = []
                proposed_refs.pop(key, None)
            issues.extend(local_issues)
            contexts.append({"key": key, "text": loc["text"], "role": loc["role"], "evidence": loc["evidence"],
                "candidates": candidates, "point": position, "radius_km": radius, "facilities": rows,
                "selected": selected, "reference_required": needs_ack, "representative": representative,
                "excluded_reason": excluded, "saved_work": valid_saved, "removed_facilities": removed})
        if sum(len(c["selected"]) for c in contexts) > 300:
            issues.append("한 검토의 시설 선정은 장소별 합계 300개까지 가능합니다. 확인 대상을 줄여 주세요.")
        questions = record["analysis"]["analysis"].get("questions", [])
        uncertain = not record["message"]["issued_at"] and any(p["intent"] in {"scheduled_restriction", "active_restriction"} for p in record["analysis"]["analysis"].get("parts", []))
        if uncertain and not request.uncertainty_acknowledged:
            issues.append("발행 시각 미상입니다. 시점이 미확인인 참고 검토로 남길지 확인하거나 보류해 주세요.")
        selected_ids = {f["id"] for c in contexts for f in c["selected"]}
        outcome = request.outcome or ("facilities_selected" if selected_ids else "no_action")
        if outcome == "no_action" and selected_ids:
            issues.append("추가 조치 없이 완료하려면 선정한 시설을 먼저 해제해 주세요.")
        if outcome == "facilities_selected" and not selected_ids:
            issues.append("확인 대상 시설을 선택해 주세요.")
        no_action_reason = request.no_action_reason or ("reference_only" if not locations else None)
        if outcome == "no_action" and not no_action_reason:
            issues.append("추가 업무 대상 없이 완료할 사유를 선택해 주세요.")
        if no_action_reason == "other" and not request.manager_note:
            issues.append("별도 판단 사유를 추가 안내에 남겨 주세요.")
        related = self.review.related_context(record) if record.get("relation_epoch") or record.get("related_messages") else {}
        if related.get("links") and not request.manager_note:
            issues.append("연결한 후속 문자로 달라진 내용은 추가 안내에 남겨 주세요.")
        snapshot = {"origin": record["origin"], "message": copy.deepcopy(record["message"]),
                    "analysis": copy.deepcopy(record["analysis"]["analysis"]), "record_note": record["note"],
                    "locations": [{"key": c["key"], "text": c["text"], "role": c["role"],
                                   "reference": proposed_refs.get(c["key"]), "selected": c["selected"]} for c in contexts],
                    "related_context": related}
        normalized = request.model_dump(exclude={"proposal_hash", "confirmed"})
        notice = render_brief_notice(snapshot, request.manager_note,
                                     excluded_locations={c["key"]:c["excluded_reason"] for c in contexts if not c["selected"]})
        basis = content_hash({"preparation_version": 1, "request": normalized, "record_version": record["version"], "content_hash": record["content_hash"],
                              "analysis": record["analysis"], "analysis_revision": record["analysis_revision"],
                              "catalog_digest": digest, "related_context": related, "references": record.get("spatial_references", {}),
                              "note": record["note"], "proposal": proposed_refs, "recommendations": recommendations,
                              "outcome": outcome, "no_action_reason": no_action_reason, "notice_preview": notice})
        if len(notice) > 40000:
            issues.append("안내 초안 분량이 한도를 넘었습니다. 확인 대상을 줄여 주세요.")
            notice = notice[:40000]+"\n미리보기 일부만 표시했습니다."
        prepared = {"record_version": record["version"], "proposal_hash": basis, "catalog_digest": digest,
                    "related_context_hash": content_hash(related),
                    "locations": contexts, "questions": questions, "uncertain_time": uncertain,
                    "outcome": outcome, "selected_count": len(selected_ids), "issues": list(dict.fromkeys(issues)),
                    "ready": not issues, "notice_preview": notice, "recommendations": recommendations}
        draft["spatial_references"] = proposed_refs
        return prepared, draft, no_action_reason

    @staticmethod
    def _candidate_point(candidate):
        return {"latitude": candidate["latitude"], "longitude": candidate["longitude"], "label": candidate["name"],
                "address": candidate["address"], "source": "candidate", "candidate_id": candidate["id"],
                "scope_matches_source": candidate.get("scope_matches_source", False)}

    def approve(self, identifier, request: ApprovePreparedReview):
        record = self.records.get(identifier)
        completion = record.get("review_completion") or {}
        if (record["version"] == request.expected_version+1 and completion.get("approval_hash") == request.proposal_hash):
            if record["review_preparation"]["choices"] != request.model_dump(exclude={"proposal_hash", "confirmed"}):
                raise RecordConflict("이미 완료한 요청과 내용이 다릅니다. 현재 기록을 다시 확인해 주세요.")
            self.review._current_draft(identifier, record["version"], record["notice_draft"]["revision"])
            return record
        prepared, draft, reason = self._build(record, request)
        if prepared["proposal_hash"] != request.proposal_hash:
            raise RecordConflict("표시한 추천안의 근거가 바뀌었습니다. 미리보기를 다시 확인해 주세요.")
        if prepared["issues"]:
            raise ReviewValidationError(prepared["issues"][0])
        now = self.records.now().isoformat()
        for ref in draft["spatial_references"].values():
            ref.update(confirmed_at=now, selection_saved_at=now)
        selected = prepared["outcome"] == "facilities_selected"
        excluded = [{"location_key": c["key"], "reason": c["excluded_reason"]} for c in prepared["locations"] if not c["selected"]]
        # Existing completion validation is reused in memory, then persisted once.
        draft["review_preparation"] = {"proposal_hash": request.proposal_hash, "catalog_digest": prepared["catalog_digest"], "recommendations": prepared["recommendations"],
                                       "choices": request.model_dump(exclude={"proposal_hash", "confirmed"}), "prepared_from_version": request.expected_version}
        self.review.complete_record(draft, CompleteMessageReview(expected_version=request.expected_version,
            outcome=prepared["outcome"], reason="화면에 표시한 위치·시설·안내 내용을 검토함" if selected else REASONS[reason],
            follow_up_note=request.manager_note, excluded_locations=excluded if selected else []),brief=True,manager_note=request.manager_note)
        if content_hash(draft["review_completion"]["snapshot"].get("related_context", {})) != prepared["related_context_hash"]:
            raise RecordConflict("검토 중 후속 문자 근거가 바뀌었습니다. 추천안을 다시 확인해 주세요.")
        draft["review_completion"]["approval_hash"] = request.proposal_hash
        draft.pop("review_working_copy", None)
        return self.records._save(draft, request.expected_version, "review_completed")

    def hold(self, identifier, request: PrepareMessageReview):
        record = self.records.get(identifier)
        MessageSpatialService._ready(record, request.expected_version)
        ensure_record_editable(record)
        keys = {loc["key"] for loc in message_locations(record) if loc["eligible"]}
        requested_keys = [choice.location_key for choice in request.choices]
        if len(requested_keys) != len(set(requested_keys)) or set(requested_keys)-keys:
            raise ReviewValidationError("현재 장소에 대한 작업본만 보류할 수 있습니다.")
        if sum(len(choice.facilities or []) for choice in request.choices)>300:
            raise ReviewValidationError("보류할 시설 선택을 장소별 합계 300개 이하로 줄여 주세요.")
        record["review_working_copy"] = {"input": request.model_dump(), "source_revision": record["source_revision"],
            "analysis_revision": record["analysis_revision"], "saved_at_version": request.expected_version+1,
            "input_hash": content_hash(request.model_dump())}
        record["review_state"] = "needs_confirmation"
        return self.records._save(record, request.expected_version, "note_saved")
