"""재난문자의 장소별 조회 기준점과 업무 대상 선정. AI/기상/발송 호출 없음."""
from __future__ import annotations

from typing import Annotated, Literal
from pydantic import Field
from safety_dashboard.application.message_analysis import StrictModel
from safety_dashboard.application.message_records import RecordConflict, RecordVersion, ensure_record_editable
from safety_dashboard.application.nearby_report import NearbyReport, distance_meters
from safety_dashboard.domain.models import GeoPoint

class SpatialValidationError(ValueError):
    """관리자에게 표시할 수 있는 기준점/선정 입력 오류."""


Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
LocationKey = Annotated[str, Field(pattern=r"^\d{1,2}:\d{1,2}$")]


class ReferencePointInput(StrictModel):
    mode: Literal["candidate", "manual"]
    candidate_id: str | None = Field(default=None, max_length=40)
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    label: str = Field(default="", max_length=80)
    manual_source: Literal["map", "coordinate"] = "map"


class SaveMessageReference(RecordVersion):
    location_key: LocationKey
    point: ReferencePointInput
    radius_km: Literal[1, 3, 5, 10]
    confirmation_note: str = Field(min_length=1, max_length=500)
    confirmed: Literal[True]


class SelectedFacilityInput(StrictModel):
    facility_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(default="", max_length=500)


class SaveMessageSelection(RecordVersion):
    location_key: LocationKey
    reference_revision: int = Field(ge=1)
    catalog_digest: Digest
    facilities: list[SelectedFacilityInput] = Field(max_length=300)
    note: str = Field(default="", max_length=1000)


def message_locations(record):
    result = []
    for pi, part in enumerate((record.get("analysis") or {}).get("analysis", {}).get("parts", [])):
        for li, location in enumerate(part.get("locations", [])):
            eligible = location["role"] in {"incident_site", "restricted_area"} and part["intent"] in {
                "event", "active_restriction", "scheduled_restriction"}
            result.append({"key": f"{pi}:{li}", "intent": part["intent"], "eligible": eligible, **location})
    return result


class MessageSpatialService:
    def __init__(self, records, catalog):
        self.records, self.catalog = records, catalog

    @staticmethod
    def _ready(record, expected=None):
        if expected is not None and record["version"] != expected:
            raise RecordConflict("기록이 변경됐습니다. 최신 기록을 다시 불러와 주세요.")
        if (not record.get("analysis") or record.get("analysis_source_revision") != record["source_revision"]):
            raise RecordConflict("현재 원문의 분석 결과가 필요합니다. 문자를 먼저 분석해 주세요.")
        if record["analysis_state"] == "running":
            raise RecordConflict("분석 중입니다. 완료 후 기록을 다시 불러와 주세요.")

    @staticmethod
    def _location(record, key):
        location = next((loc for loc in message_locations(record) if loc["key"] == key), None)
        if not location or not location["eligible"]:
            raise SpatialValidationError("사고·진행/예정 통제 장소만 기준점으로 선택할 수 있습니다.")
        return location

    def _reference(self, record, key):
        self._location(record, key)
        ref = record.get("spatial_references", {}).get(key)
        if not ref or ref["analysis_revision"] != record["analysis_revision"] or ref["source_revision"] != record["source_revision"]:
            raise RecordConflict("이 장소의 조회 기준점을 먼저 확인해 주세요.")
        return ref

    def detail(self, identifier):
        record = self.records.get(identifier)
        self._ready(record)
        digest, _ = self.catalog()
        contexts = []
        candidates = {c["id"]: c for c in record["analysis"].get("candidates", [])}
        for location in message_locations(record):
            ref = record.get("spatial_references", {}).get(location["key"])
            if ref and (ref["analysis_revision"] != record["analysis_revision"] or ref["source_revision"] != record["source_revision"]):
                ref = None
            contexts.append({**location, "candidates": [candidates[key] for key in location.get("candidate_ids", []) if key in candidates],
                             "reference": ref, "catalog_current": bool(ref and ref["catalog_digest"] == digest)})
        return {"record_version": record["version"], "analysis_revision": record["analysis_revision"],
                "catalog_digest": digest, "locations": contexts, "reset_reason": record.get("spatial_reset_reason", "")}

    def save_reference(self, identifier, request: SaveMessageReference):
        record = self.records.get(identifier)
        self._ready(record, request.expected_version)
        ensure_record_editable(record)
        location = self._location(record, request.location_key)
        point = request.point
        if point.mode == "candidate":
            candidate = next((row for row in record["analysis"].get("candidates", []) if row["id"] == point.candidate_id), None)
            if (point.candidate_id not in location.get("candidate_ids", []) or not candidate
                    or candidate.get("role") != location["role"]):
                raise SpatialValidationError("이 사고·통제 장소에 속하는 후보를 선택해 주세요.")
            if point.latitude is not None or point.longitude is not None or point.label:
                raise SpatialValidationError("원본 후보의 좌표/이름은 바꿀 수 없습니다. 위치 수정은 지도 지정을 사용해 주세요.")
            position = {"latitude": candidate["latitude"], "longitude": candidate["longitude"],
                        "label": candidate["name"], "address": candidate["address"], "source": "candidate",
                        "candidate_id": candidate["id"], "scope_matches_source": candidate.get("scope_matches_source", False)}
        else:
            if point.candidate_id or point.latitude is None or point.longitude is None:
                raise SpatialValidationError("관리자가 지정한 좌표를 확인해 주세요.")
            position = {"latitude": point.latitude, "longitude": point.longitude, "label": point.label or location["text"][:80],
                        "address": "", "source": point.manual_source, "candidate_id": None, "scope_matches_source": False}
        digest, facilities = self.catalog()
        report = NearbyReport.build(GeoPoint(position["latitude"], position["longitude"]), position["label"], position["address"], request.radius_km, facilities)
        refs = record.setdefault("spatial_references", {})
        old = refs.get(request.location_key)
        if (old and old["analysis_revision"] == record["analysis_revision"] and old["source_revision"] == record["source_revision"]
                and old["point"] == position and old["radius_km"] == request.radius_km and old["catalog_digest"] == digest):
            old.update(confirmation_note=request.confirmation_note, confirmed_at=self.records.now().isoformat())
            return self.records._save(record, request.expected_version, "reference_confirmed")
        refs[request.location_key] = {"location_key": request.location_key, "role": location["role"], "evidence": location["evidence"],
            "analysis_revision": record["analysis_revision"], "source_revision": record["source_revision"],
            "revision": (old["revision"] + 1 if old else 1), "point": position, "radius_km": request.radius_km,
            "confirmation_note": request.confirmation_note, "confirmed_at": self.records.now().isoformat(),
            "catalog_digest": digest, "nearby_count": len(report.facilities), "selected": [], "selection_note": "",
            "selection_saved_at": None, "selection_needs_review": bool(old)}
        record["review_state"] = "needs_confirmation"
        return self.records._save(record, request.expected_version, "reference_saved")

    def _rows(self, ref):
        digest, facilities = self.catalog()
        point = GeoPoint(ref["point"]["latitude"], ref["point"]["longitude"])
        # Validate every ID/coordinate through the existing shared calculation first.
        NearbyReport.build(point, ref["point"]["label"], "", ref["radius_km"], facilities)
        rows = []
        for facility in facilities:
            distance = distance_meters(point, facility.location)
            rows.append({"id": facility.id, "name": facility.name, "facility_type": facility.facility_type,
                         "address": facility.address, "latitude": facility.location.latitude, "longitude": facility.location.longitude,
                         "distance_m": round(distance), "within_radius": distance <= ref["radius_km"] * 1000})
        rows.sort(key=lambda row: (row["distance_m"], row["id"]))
        return digest, rows

    def facilities_page(self, identifier, key, expected_version, *, offset=0, limit=20, scope="nearby", query="", catalog_digest=None):
        record = self.records.get(identifier)
        self._ready(record, expected_version)
        ref = self._reference(record, key)
        digest, rows = self._rows(ref)
        if catalog_digest and catalog_digest != digest:
            raise RecordConflict("시설 자료가 바뀌었습니다. 기준점을 다시 조회하고 시설을 선택해 주세요.")
        filtered = [r for r in rows if (scope == "all" or r["within_radius"]) and
                    (not query or query.casefold() in f'{r["id"]} {r["name"]} {r["address"]} {r["facility_type"]}'.casefold())]
        page = filtered[offset:offset + limit]
        return {"facilities": page, "total_count": len(filtered), "offset": offset,
                "next_offset": offset + limit if offset + limit < len(filtered) else None,
                "catalog_digest": digest, "catalog_current": ref["catalog_digest"] == digest,
                "reference_revision": ref["revision"], "record_version": record["version"],
                "map_facilities": [r for r in rows if r["within_radius"]]}

    def save_selection(self, identifier, request: SaveMessageSelection):
        record = self.records.get(identifier)
        self._ready(record, request.expected_version)
        ensure_record_editable(record)
        ref = self._reference(record, request.location_key)
        if ref["revision"] != request.reference_revision:
            raise RecordConflict("조회 기준점이 바뀌었습니다. 시설을 다시 선택해 주세요.")
        digest, rows = self._rows(ref)
        if digest != request.catalog_digest or digest != ref["catalog_digest"]:
            raise RecordConflict("시설 자료가 바뀌었습니다. 기준점을 다시 조회하고 시설을 선택해 주세요.")
        by_id = {row["id"]: row for row in rows}
        ids = [item.facility_id for item in request.facilities]
        if len(set(ids)) != len(ids) or any(key not in by_id for key in ids):
            raise SpatialValidationError("등록된 시설 ID를 중복 없이 선택해 주세요.")
        if ids and not request.note:
            raise SpatialValidationError("시설 선정 사유를 입력해 주세요.")
        selected = []
        for item in request.facilities:
            row = by_id[item.facility_id]
            if not row["within_radius"] and not item.reason:
                raise SpatialValidationError("조회 반경 밖 시설은 개별 추가 사유가 필요합니다.")
            selected.append({**row, "reason": item.reason})
        ref.update(selected=selected, selection_note=request.note, selection_saved_at=self.records.now().isoformat(), selection_needs_review=False)
        record["review_state"] = "needs_confirmation"
        return self.records._save(record, request.expected_version, "facilities_selected")
