"""기상특보 구역과 시설 주소/지도 경계를 연결하는 규칙."""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Sequence


_ADMIN_SUFFIX = re.compile(r"(특별자치도|특별자치시|광역시|특별시|도|시|군|구)$")
_AMBIGUOUS_DISTRICTS = {"중구", "남구", "북구", "동구", "서구"}
_DAEGU_BOUNDARIES = (
    "중구",
    "남구",
    "북구",
    "동구",
    "서구",
    "수성구",
    "달서구",
    "달성군",
)


def _compact(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def _base_admin_name(value: object) -> str:
    return _ADMIN_SUFFIX.sub("", _compact(value))


def _parent_keywords(region_up: object) -> tuple[str, ...]:
    parent = _compact(region_up)
    if "대구" in parent:
        return ("대구",)
    if "경상북도" in parent or "경북" in parent:
        return ("경상북도", "경북")
    return (_base_admin_name(parent),) if parent else ()


def facility_matches_warning(
    address: object,
    region: object,
    region_up: object = "",
) -> bool:
    """시설 주소가 특보 구역에 포함되는지 보수적으로 판단합니다.

    KMA의 ``대구중부``처럼 행정구역명과 일치하지 않는 특보 구역은
    누락 방지를 위해 대구 소재 시설 전체에 적용합니다. 향후 KMA 특보구역
    코드가 확보되면 이 규칙을 코드 기반 매핑으로 교체할 수 있습니다.
    """

    address_text = _compact(address)
    region_text = _compact(region)
    if not address_text or not region_text:
        return False

    if region_text.startswith("대구") and region_text not in {
        "대구광역시",
        "대구시",
    }:
        return "대구" in address_text

    region_base = _base_admin_name(region_text)
    direct_match = region_text in address_text or (
        bool(region_base) and region_base in address_text
    )
    if not direct_match:
        return False

    if region_text in _AMBIGUOUS_DISTRICTS:
        parents = _parent_keywords(region_up)
        return not parents or any(keyword in address_text for keyword in parents)

    return True


def boundary_names_for_warning(
    region: object,
    available_names: Iterable[str],
) -> list[str]:
    """특보 구역에 해당하는 GeoJSON 경계 이름을 반환합니다."""

    region_text = _compact(region)
    available = set(available_names)

    if region_text in available:
        return [region_text]

    if region_text.startswith("대구"):
        return [name for name in _DAEGU_BOUNDARIES if name in available]

    region_base = _base_admin_name(region_text)
    return [
        name
        for name in available
        if _base_admin_name(name) == region_base
    ]


def warning_level_rank(level: object) -> int:
    """특보 단계 비교용 우선순위를 반환합니다."""

    text = _compact(level)
    if any(token in text for token in ("중대", "심각", "위급")):
        return 4
    if "경보" in text:
        return 3
    if "주의" in text:
        return 2
    return 1


def dominant_warning(
    warnings: Sequence[Mapping[str, object]],
    type_weights: Mapping[str, int],
) -> Mapping[str, object]:
    """동일 지역의 여러 특보 중 시각적으로 우선 표시할 특보를 선택합니다."""

    if not warnings:
        return {}
    return max(
        warnings,
        key=lambda item: (
            warning_level_rank(item.get("level")),
            type_weights.get(str(item.get("type", "")), 1),
        ),
    )

