"""Folium 클릭 결과를 안정적인 시설·CCTV ID로 변환합니다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from safety_dashboard.application.context_info import find_clicked_cctv
from safety_dashboard.domain.models import DashboardSnapshot, NearbyCctv


FACILITY_TOKEN = "시설 ID · "


@dataclass(frozen=True)
class MapSelection:
    kind: str
    facility_id: str = ""
    cctv_id: str = ""


def resolve_map_selection(
    snapshot: DashboardSnapshot,
    cctvs: Sequence[NearbyCctv],
    tooltip: object,
    clicked: Mapping[str, object] | None,
) -> MapSelection | None:
    """좌표가 겹쳐도 툴팁의 ID 토큰을 우선해 시설을 식별합니다."""

    text = str(tooltip or "").strip()
    if text.startswith("시설 · ") and FACILITY_TOKEN in text:
        facility_id = text.rsplit(FACILITY_TOKEN, 1)[-1].strip()
        if any(item.id == facility_id for item in snapshot.facilities):
            return MapSelection("facility", facility_id=facility_id)
        return None
    if text.startswith("CCTV · "):
        cctv = find_clicked_cctv(cctvs, clicked)
        if cctv is not None:
            return MapSelection("cctv", cctv_id=cctv.id)
    return None
