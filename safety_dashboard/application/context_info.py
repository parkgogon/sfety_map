"""선택 시설 관할의 재난문자·뉴스 참고정보를 만듭니다."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Mapping
from urllib.parse import urlencode

from safety_dashboard.domain.models import (
    DisasterMessage,
    Facility,
    FacilityRegion,
    NearbyCctv,
)


KST = dt.timezone(dt.timedelta(hours=9))
RELEVANT_DISASTER_TYPES = frozenset(
    {
        "강풍",
        "건조",
        "교통",
        "교통사고",
        "교통통제",
        "대설",
        "붕괴",
        "산불",
        "산사태",
        "정전",
        "지진",
        "지진해일",
        "조수",
        "태풍",
        "폭발",
        "폭염",
        "풍랑",
        "한파",
        "호우",
        "홍수",
        "해일",
        "화재",
        "환경오염사고",
    }
)

_PROVINCE_ALIASES = {
    "대구": "대구광역시",
    "대구시": "대구광역시",
    "대구광역시": "대구광역시",
    "경북": "경상북도",
    "경상북도": "경상북도",
    "부산": "부산광역시",
    "부산시": "부산광역시",
    "부산광역시": "부산광역시",
    "울산": "울산광역시",
    "울산시": "울산광역시",
    "울산광역시": "울산광역시",
    "경남": "경상남도",
    "경상남도": "경상남도",
}
_CITY_PROVINCES = {
    "포항": "경상북도",
    "포항시": "경상북도",
}
_DISTRICT_CORRECTIONS = {
    "울준군": "울주군",
    "진구": "부산진구",
}
_PROVINCE_SEARCH_ALIASES = {
    "대구광역시": ("대구광역시", "대구시", "대구"),
    "경상북도": ("경상북도", "경북"),
    "부산광역시": ("부산광역시", "부산시", "부산"),
    "울산광역시": ("울산광역시", "울산시", "울산"),
    "경상남도": ("경상남도", "경남"),
}
_METROPOLITAN_NEWS_NAMES = {
    "대구광역시": "대구",
    "부산광역시": "부산",
    "울산광역시": "울산",
}
_NEWS_FALLBACK_TERMS = ("재난", "사고", "통제", "대피")
_ADMIN_TOKEN = re.compile(r"^[가-힣]+(?:시|군|구)$")


def resolve_facility_region(address: str) -> FacilityRegion | None:
    tokens = str(address or "").replace("\u3000", " ").split()
    if not tokens:
        return None

    province = _PROVINCE_ALIASES.get(tokens[0])
    start = 1
    if province is None:
        province = _CITY_PROVINCES.get(tokens[0])
        start = 0
    if province is None:
        return None

    candidates: list[str] = []
    for token in tokens[start : start + 3]:
        cleaned = re.sub(r"[^0-9A-Za-z가-힣]", "", token)
        cleaned = _DISTRICT_CORRECTIONS.get(cleaned, cleaned)
        if _ADMIN_TOKEN.match(cleaned):
            candidates.append(cleaned)

    if start == 0 and tokens[0] in ("포항", "포항시"):
        candidates.insert(0, "포항시")
    district = " ".join(dict.fromkeys(candidates[:2]))
    if not district:
        return None
    return FacilityRegion(province=province, district=district, query_name=province)


def select_relevant_disaster_messages(
    messages: Iterable[DisasterMessage],
    region: FacilityRegion,
    since: dt.datetime,
    limit: int = 5,
) -> tuple[DisasterMessage, ...]:
    cutoff = _aware_kst(since)
    district_tokens = tuple(region.district.split())
    selected: dict[str, DisasterMessage] = {}
    for message in messages:
        if _aware_kst(message.created_at) < cutoff:
            continue
        if message.disaster_type not in RELEVANT_DISASTER_TYPES:
            continue
        region_text = " ".join(message.regions)
        local = _matches_local_district(region_text, district_tokens, region.province)
        province_wide = "전국" in region_text or any(
            alias in region_text
            for alias in _PROVINCE_SEARCH_ALIASES.get(
                region.province,
                (region.province,),
            )
        ) and any(
            marker in region_text for marker in ("전체", "전 지역", "전역")
        )
        if not (local or province_wide):
            continue
        previous = selected.get(message.id)
        if previous is None or message.created_at > previous.created_at:
            selected[message.id] = message
    return tuple(
        sorted(selected.values(), key=lambda item: item.created_at, reverse=True)[:limit]
    )


def build_news_search_url(
    facility: Facility,
    region: FacilityRegion | None,
    warning_types: Iterable[str],
    reference_date: dt.date | None = None,
) -> str:
    location = _news_location(region) if region else str(facility.name).strip()
    hazards = tuple(
        dict.fromkeys(
            cleaned
            for item in warning_types
            if (cleaned := str(item or "").strip())
        )
    )
    if not hazards:
        hazards = _NEWS_FALLBACK_TERMS

    today = reference_date or dt.datetime.now(KST).date()
    after_date = today - dt.timedelta(days=7)
    return "https://www.google.com/search?" + urlencode(
        {
            "tbm": "nws",
            "hl": "ko",
            "gl": "KR",
            "as_q": f"{location} after:{after_date:%Y-%m-%d}",
            "as_oq": " ".join(hazards),
        }
    )


def find_clicked_cctv(
    cctvs: Iterable[NearbyCctv],
    clicked: object,
    tolerance: float = 0.00001,
) -> NearbyCctv | None:
    if not isinstance(clicked, Mapping):
        return None
    try:
        latitude = float(clicked["lat"])
        longitude = float(clicked["lng"])
    except (KeyError, TypeError, ValueError):
        return None
    candidates = [
        item
        for item in cctvs
        if abs(item.location.latitude - latitude) <= tolerance
        and abs(item.location.longitude - longitude) <= tolerance
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            abs(item.location.latitude - latitude)
            + abs(item.location.longitude - longitude)
        ),
    )


def _news_location(region: FacilityRegion) -> str:
    metropolitan_name = _METROPOLITAN_NEWS_NAMES.get(region.province)
    if metropolitan_name:
        district = region.district.strip()
        if district.startswith(metropolitan_name + " "):
            return district
        return " ".join(item for item in (metropolitan_name, district) if item)

    district_tokens = region.district.split()
    if not district_tokens:
        return region.province
    parent = re.sub(r"(?:시|군)$", "", district_tokens[0])
    return " ".join((parent, *district_tokens[1:]))


def _aware_kst(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=KST)
    return value.astimezone(KST)


def _matches_local_district(
    region_text: str,
    district_tokens: tuple[str, ...],
    province: str,
) -> bool:
    if not district_tokens:
        return False
    if len(district_tokens) == 1:
        return district_tokens[0] in region_text

    parent, child = district_tokens[0], district_tokens[1]
    if parent in region_text and child in region_text:
        return True
    if child in region_text and any(
        alias in region_text
        for alias in _PROVINCE_SEARCH_ALIASES.get(province, (province,))
    ):
        return True
    if parent not in region_text:
        return False
    mentioned_subdistricts = {
        token
        for token in re.findall(r"[가-힣]+(?:군|구)", region_text)
        if token != child
    }
    return not mentioned_subdistricts
