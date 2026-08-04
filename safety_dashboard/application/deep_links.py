"""시설 딥링크와 조회 범위 확장 규칙."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit, urlunsplit

from safety_dashboard.application.facility_groups import FacilityGroupCatalog
from safety_dashboard.domain.enums import RiskGrade
from safety_dashboard.domain.models import DashboardSnapshot


@dataclass(frozen=True)
class DeepLinkScope:
    facility_id: str
    group_ids: tuple[str, ...]
    grades: tuple[RiskGrade, ...]


def dashboard_home_url(base_url: str) -> str:
    """HTTPS 대시보드 기본 주소만 반환합니다."""

    try:
        parts = urlsplit(str(base_url or "").strip())
    except ValueError:
        return ""
    if parts.scheme.lower() != "https" or not parts.netloc:
        return ""
    if parts.username or parts.password:
        return ""
    path = parts.path or "/"
    return urlunsplit(("https", parts.netloc, path, "", ""))


def build_facility_url(base_url: str, facility_id: str) -> str:
    home = dashboard_home_url(base_url)
    if not home or not str(facility_id).strip():
        return ""
    parts = urlsplit(home)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode({"facility_id": str(facility_id).strip()}),
            "",
        )
    )


def expand_scope_for_facility(
    snapshot: DashboardSnapshot,
    catalog: FacilityGroupCatalog,
    current_group_ids: list[str],
    current_grades: list[RiskGrade],
    facility_id: str,
) -> DeepLinkScope | None:
    assessment = next(
        (
            item
            for item in snapshot.assessments
            if item.facility.id == str(facility_id)
        ),
        None,
    )
    if assessment is None:
        return None

    group_id = catalog.group_for_type(assessment.facility.facility_type).id
    group_set = set(current_group_ids)
    group_set.add(group_id)
    grade_set = set(current_grades)
    grade_set.add(assessment.grade)
    return DeepLinkScope(
        facility_id=assessment.facility.id,
        group_ids=tuple(item for item in catalog.ids if item in group_set),
        grades=tuple(item for item in RiskGrade if item in grade_set),
    )
