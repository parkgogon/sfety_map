"""Read-only facility name/administrative-address queries for the message agent."""
from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

PROVINCES = {"대구광역시": "대구", "부산광역시": "부산", "울산광역시": "울산",
             "경상북도": "경북", "경상남도": "경남"}


class FacilityQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    area_text: Annotated[str, Field(min_length=2, max_length=100)] | None
    facility_name: Annotated[str, Field(min_length=2, max_length=160)] | None
    evidence: str = Field(min_length=2, max_length=1000)


def area_tokens(text: str) -> tuple[str, ...]:
    tokens = text.split()
    if not tokens:
        return ()
    province = next((full for full, short in PROVINCES.items() if tokens[0] in (full, short)), None)
    if not province or len(tokens) > 3:
        return ()
    if any(not re.fullmatch(r"[가-힣]+[시군구]", token) for token in tokens[1:]):
        return ()
    return (province, *tokens[1:])


def target_region_in(text: str) -> bool:
    return any(re.search(r"(?<![가-힣])" + re.escape(name) + r"(?=\s|[.,·:：\[\]()의]|$)", text)
               for pair in PROVINCES.items() for name in pair)


def query_facilities(query: FacilityQuery, source_text: str, facilities, *, limit: int | None = 20) -> dict:
    if query.evidence not in source_text:
        raise ValueError("시설 조회 근거는 원문의 연속된 인용이어야 합니다.")
    if not query.area_text and not query.facility_name:
        raise ValueError("원문에 있는 지역 또는 시설명이 필요합니다.")
    for value in (query.area_text, query.facility_name):
        if value and value not in query.evidence:
            raise ValueError("지역과 시설명은 조회 근거에 그대로 포함되어야 합니다.")
    selected = tuple(f for f in facilities if f.is_monitored)
    if query.area_text:
        scope = area_tokens(query.area_text)
        if not scope:
            raise ValueError("광역지역부터 시·군·구 순서로 명시된 지역만 주소 대조할 수 있습니다.")
        # A province-wide result needs an explicit province-wide source statement.
        if len(scope) == 1 and not re.search(re.escape(query.area_text) + r"\s*(?:전역|전체)", query.evidence):
            raise ValueError("광역지역 전체 조회에는 원문의 전역/전체 범위가 필요합니다. 시·군·구가 있으면 함께 넣으세요.")
        selected = tuple(f for f in selected if area_tokens(" ".join(f.address.split()[:len(scope)])) == scope)
    if query.facility_name:
        key = re.sub(r"\s+", "", query.facility_name)
        selected = tuple(f for f in selected if re.sub(r"\s+", "", f.name) == key)
    ambiguous = bool(query.facility_name and len(selected) > 1)
    rows = sorted(selected, key=lambda f: f.id)
    shown = rows if limit is None else rows[:limit]
    return {"status": "needs_confirmation" if ambiguous else "ok" if rows else "not_found",
            "kind": "facility" if query.facility_name else "area", "query": query.model_dump(),
            "total_count": len(rows), "shown_count": len(shown),
            "facilities": [{"id": f.id, "name": f.name, "facility_type": f.facility_type, "address": f.address}
                           for f in shown]}
