"""외부로 노출할 수 있는 시설 담당 정보를 만듭니다."""

from __future__ import annotations

import re

from safety_dashboard.domain.models import Facility


_MOBILE_PHONE = re.compile(
    r"(?<!\d)(?:\+?82[-.\s]?\(?10\)?|\(?01[016789]\)?)"
    r"(?:[-.\s]?\d{3,4})(?:[-.\s]?\d{4})\)?(?!\d)"
)
_EMPTY_BRACKETS = re.compile(r"\(\s*\)|\[\s*\]")
_EXTRA_SEPARATORS = re.compile(r"\s*(?:[|,/]·?|[·])\s*$")
_MULTISPACE = re.compile(r"\s{2,}")


def public_contact(facility: Facility) -> str:
    """개인 휴대전화를 제외한 `담당부서 · 이름/직책`을 반환합니다."""

    department = _clean_part(facility.department)
    manager = _clean_part(_MOBILE_PHONE.sub("", str(facility.manager or "")))
    values = [item for item in (department, manager) if item and item != "-"]
    return " · ".join(values) if values else "-"


def _clean_part(value: object) -> str:
    text = _EMPTY_BRACKETS.sub("", str(value or "").strip())
    text = _EXTRA_SEPARATORS.sub("", text)
    return _MULTISPACE.sub(" ", text).strip(" ·,/-")
