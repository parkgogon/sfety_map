"""Grounded notification recommendations and previews. No writes, model calls or sends."""
from __future__ import annotations

import datetime as dt
import math
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from safety_dashboard.application.deep_links import build_facility_url, dashboard_home_url
from safety_dashboard.application.message_facility_queries import FacilityQuery, query_facilities, target_region_in
from safety_dashboard.application.nearby_report import NearbyReport
from safety_dashboard.domain.models import GeoPoint

KST = dt.timezone(dt.timedelta(hours=9))
POLICY_VERSION = "message-notification-preview-v3"


class NotificationAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    need: Literal["notify", "record_only", "uncertain"]
    urgency: Literal["immediate", "scheduled", "reference", "unknown"]
    relevance: Literal["facility", "nearby", "area_operations", "general", "outside_scope", "unknown"]
    reason: str = Field(min_length=1, max_length=400)
    evidence: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(min_length=1, max_length=8)
    basis_refs: list[Annotated[str, Field(pattern=r"^(?:P|FQ)[1-9][0-9]{0,2}$")]] = Field(max_length=20)


def validate_assessment(assessment, text, candidates, queries):
    """Also used during tool submission, so the agent can correct invalid evidence."""
    if any(evidence not in text for evidence in assessment.evidence):
        raise ValueError("전파 판단 근거는 원문 그대로의 연속된 인용이어야 합니다.")
    if len(set(assessment.basis_refs)) != len(assessment.basis_refs):
        raise ValueError("전파 판단 근거 ID가 중복되었습니다.")
    if set(assessment.basis_refs) - (set(candidates) | set(queries)):
        raise ValueError("전파 판단에는 실제로 조회한 장소/시설 조회 ID만 사용할 수 있습니다.")


def record_only_rejection(assessment, parts, source_text):
    """The same suppression checks are used at agent submission and saved-result replay."""
    if assessment.urgency == 'immediate' or assessment.relevance in {'facility','nearby','area_operations'}:
        return '업무 관련성·긴급성과 기록만 하겠다는 판단이 맞지 않아 확인이 필요합니다.'
    if assessment.relevance == 'general' and any(p.intent not in {'prevention','advisory'} for p in parts):
        return '사고·통제·해제 내용이 있어 일반 안내로만 처리할 수 없습니다.'
    if assessment.relevance == 'outside_scope':
        from safety_dashboard.application.message_analysis import REGION_ALIASES
        outside_names = [name for full,short in REGION_ALIASES.items() if not target_region_in(full) for name in (full,short)]
        cited_outside = any(re.search(r'(?<![가-힣])'+re.escape(name)+r'(?=\s|[.,\[\]()]|$)', ' '.join(assessment.evidence)) for name in outside_names)
        if target_region_in(source_text) or not cited_outside:
            return '범위 밖이라는 원문 지역 근거가 부족하거나 소관 지역 정보가 섞여 있습니다.'
    return None


def _instant(value):
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("발행 시각의 시간대가 필요합니다.")
    return parsed


def _same_source(record, result):
    original, analyzed = record["message"], result["input"]
    return (analyzed["text"] == original["text"] and analyzed["source"] == original["source"]
            and analyzed["input_kind"] == record["origin"]
            and sorted(analyzed.get("recipient_regions", [])) == sorted(original.get("recipient_regions", []))
            and (not original.get("issued_at") and not analyzed.get("issued_at")
                 or bool(original.get("issued_at") and analyzed.get("issued_at")
                         and _instant(original["issued_at"]) == _instant(analyzed["issued_at"]))))


def _map_url(base_url, facilities):
    home = dashboard_home_url(base_url)
    if not home:
        return ""
    parts = urlsplit(home)
    # Staff links always point to the public map, even if a configured base has a control path.
    home = urlunsplit((parts.scheme, parts.netloc, "/", "", ""))
    return build_facility_url(home, facilities[0]["id"]) if len(facilities) == 1 else home


def notification_preview(record, catalog, *, base_url="", now=None):
    """Revalidate the current record/catalog; returning notify_ready never enables dispatch."""
    now = now or dt.datetime.now(dt.timezone.utc)
    digest, facilities = catalog
    result = record.get("analysis")
    output = {"policy_version": POLICY_VERSION, "phase": "preview", "dispatch_enabled": False,
              "record_version": record["version"], "source_revision": record["source_revision"],
              "analysis_revision": record.get("analysis_revision", 0), "catalog_digest": digest,
              "input_kind": record["origin"], "decision": "attention_required", "reason": "",
              "assessment": None, "facilities": [], "limitations": [], "preview_text": None, "map_url": ""}

    def finish(decision, reason):
        return {**output, "decision": decision, "reason": reason}

    if not result or record.get("analysis_state") != "completed":
        return finish("analysis_unavailable", "현재 원문의 분석을 완료하지 못했습니다. 자동 준비 상태에서 긴급 원문 대체 가능 여부를 따로 확인합니다.")
    if record.get("analysis_source_revision") != record["source_revision"]:
        return finish("blocked", "원문 버전이 바뀌었습니다. 최신 분석이 필요합니다.")
    if record.get("facility_digest") != digest:
        return finish("blocked", "시설 자료가 바뀌었습니다. 현재 자료로 근거를 다시 확인해야 합니다.")
    try:
        if not _same_source(record, result):
            return finish("blocked", "분석에 사용한 원문·출처·지역·발행 시각이 현재 기록과 다릅니다.")
        if not result["analysis"].get("notification_assessment"):
            return finish("attention_required", "이전 분석에는 전파 판단이 없습니다. 이 화면 조회는 AI를 다시 호출하지 않습니다.")
        # Local import keeps the shared tool model independent of the analysis runner.
        from safety_dashboard.application.message_analysis import AnalysisDraft, MessageAnalysisInput, MessageAnalysisService, REGION_ALIASES
        source = MessageAnalysisInput.model_validate(result["input"])
        draft = AnalysisDraft.model_validate(result["analysis"])
        assessment = draft.notification_assessment
        candidates = {p["id"]: p for p in result.get("candidates", [])}
        nearby = {p["candidate_id"]: p for p in result.get("nearby", [])}
        queries = {q["id"]: q for q in result.get("facility_queries", [])}
        eligible = MessageAnalysisService._validate(draft, source, candidates, nearby)
        validate_assessment(assessment, source.text, candidates, queries)
    except (ValidationError, ValueError, TypeError, KeyError):
        return finish("attention_required", "전파 판단의 원문·시각·장소·조회 근거를 검증하지 못했습니다.")
    output["assessment"] = assessment.model_dump()
    if assessment.need == "uncertain" or assessment.relevance == "unknown":
        return finish("attention_required", assessment.reason)

    if assessment.need == "record_only":
        reason = record_only_rejection(assessment, draft.parts, source.text)
        if reason:
            return finish('attention_required', reason)
        return finish("record_only", assessment.reason)

    if assessment.relevance not in {"facility", "nearby", "area_operations"} or assessment.urgency == "unknown":
        return finish("attention_required", "전달할 업무 관련성과 시점을 먼저 확인해야 합니다.")
    if not source.issued_at or source.issued_at > now + dt.timedelta(minutes=5):
        return finish("attention_required", "발행 시각이 미상이거나 미래입니다. 현재 상황으로 전달하지 않습니다.")
    if record["origin"] == "official" and now-source.issued_at > dt.timedelta(hours=24):
        return finish("attention_required", "발행 후 24시간이 지난 원문입니다. 현재 상황을 다시 확인해야 합니다.")
    if record["origin"] == "official" and assessment.urgency == "immediate" and now-source.issued_at > dt.timedelta(hours=1):
        return finish("attention_required", "발행 후 1시간이 지난 원문입니다. 현재 긴급 상황으로 자동 전달하지 않습니다.")
    if assessment.urgency == "scheduled" and not any(p.starts_at and _instant(p.starts_at) > now for p in draft.parts):
        return finish("attention_required", "예정 상황의 유효한 시작 시각을 확인하지 못했습니다.")

    selected = {}
    limits = []
    verified_basis = False
    try:
        for ref in assessment.basis_refs:
            if ref in queries:
                query = queries[ref]
                checked = query_facilities(FacilityQuery.model_validate(query["query"]), source.text, facilities, limit=None)
                # The query must be linked to an actual situation/evidence, not a different passage.
                evidence = checked["query"]["evidence"]
                if not any(evidence in e or e in evidence for e in assessment.evidence):
                    raise ValueError("조회 근거가 판단 인용과 다릅니다.")
                if checked["status"] == "ok":
                    verified_basis = True
                    for facility in checked["facilities"]:
                        selected[facility["id"]] = {**facility, "basis": checked["query"]["area_text"] or "원문 시설명", "distance_m": None}
                    limits.append("시설 주소/명칭 대조이며 피해·운영 중단 확인이 아닙니다.")
                else:
                    limits.append("원문 지역/시설 조회 결과를 확정하지 못했습니다.")
                continue
            if ref not in eligible or ref not in nearby:
                raise ValueError("해당 사고·통제 장소의 주변 조회 근거가 없습니다.")
            mentions = [loc for p in draft.parts for loc in p.locations if ref in loc.candidate_ids]
            if any(len(loc.candidate_ids) != 1 for loc in mentions):
                limits.append("동명 후보가 여러 곳이므로 시설과 거리를 표시하지 않습니다.")
                continue
            place = candidates[ref]
            lat, lon = place["latitude"], place["longitude"]
            if not (math.isfinite(lat) and math.isfinite(lon) and 33 <= lat <= 39.5 and 124 <= lon <= 132):
                raise ValueError("유효한 국내 조회 좌표가 아닙니다.")
            if not any(place["location_text"] in e for e in assessment.evidence):
                raise ValueError("장소 조회가 판단 인용과 다릅니다.")
            report = NearbyReport.build(GeoPoint(place["latitude"], place["longitude"]), place["name"],
                                        place["address"], source.reference_radius_km, facilities)
            if report.facilities:
                verified_basis = True
                for row in report.facilities:
                    f = row.facility
                    selected.setdefault(f.id, {"id": f.id, "name": f.name, "address": f.address,
                        "facility_type": f.facility_type, "distance_m": round(row.meters), "basis": place["name"] + " 검색 기준점"})
            limits.append(f"{place['name']} 검색 기준점의 직선거리이며 실제 발생 위치·위험 범위와 다를 수 있습니다.")
    except (ValueError, TypeError, KeyError):
        return finish("attention_required", "판단에 연결한 시설·위치 조회 근거가 맞지 않습니다.")

    if not verified_basis:
        if not target_region_in(" ".join(assessment.evidence)):
            return finish("attention_required", "업무 관련 위치/지역의 근거를 확인하지 못했습니다. 수신지역으로 사고 도시를 추정하지 않습니다.")
        if assessment.urgency != "immediate":
            return finish("attention_required", "확인된 업무 관련 조회 근거가 없어 추가 확인이 필요합니다.")
        decision = "notify_source_only"
        selected.clear()
        limits.append("정확한 위치·관련 시설이 미확인되어 원문 중심으로 안내합니다.")
    else:
        decision = "notify_ready"

    output["facilities"] = sorted(selected.values(), key=lambda f: (f["distance_m"] is None, f["distance_m"] or 0, f["id"]))
    output["limitations"] = list(dict.fromkeys(limits))
    output["map_url"] = _map_url(base_url, output["facilities"])
    heading = "[재난문자 기반 시설 참고 안내]" if record["origin"] == "official" else "[재난문자 알림 미리보기 · 미발송]"
    lines = [heading, f"발행 {source.issued_at.astimezone(KST):%Y-%m-%d %H:%M} (한국 시간)"]
    if record["origin"] != "official":
        lines.append("창작 예문" if record["origin"] == "example" else "수동 입력 · 공식 자동전파 대상 아님")
    # Exact source excerpts prevent invented summaries, distances and whole-area releases.
    excerpts = list(dict.fromkeys([*assessment.evidence, *(p.evidence for p in draft.parts)]))
    excerpts = [e for e in excerpts if not any(e != other and e in other for other in excerpts)]
    excerpts.sort(key=source.text.index)
    if decision == "notify_source_only" or sum(map(len, excerpts)) > len(source.text):
        excerpts = [source.text]
    lines.extend(["예정 상황" if assessment.urgency == "scheduled" else "원문 핵심 내용", *excerpts])
    for f in output["facilities"][:3]:
        distance = f" · 직선 {f['distance_m']/1000:.2f}km" if f["distance_m"] is not None else ""
        label = "주변 참고시설" if f["distance_m"] is not None else "관련 참고시설"
        lines.append(f"{label}: {f['name']}{distance} ({f['basis']})")
    if len(output["facilities"]) > 3:
        lines.append(f"그 외 참고시설 {len(output['facilities'])-3}개소")
    lines.extend(output["limitations"])
    if output["map_url"]:
        lines.append("현장 지도: " + output["map_url"])
    output["preview_text"] = "\n".join(lines)
    if len(output["preview_text"]) > 3900:
        output["preview_text"] = None
        return finish("attention_required", "핵심 문안이 길어 추가 정리가 필요합니다. 구간별 상태를 잘라서 전달하지 않습니다.")
    return finish(decision, assessment.reason)
