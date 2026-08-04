"""조회 범위와 화면 표시를 위한 가벼운 UI helper."""

from __future__ import annotations

import hashlib

import streamlit as st

from safety_dashboard.application.facility_groups import FacilityGroupCatalog
from safety_dashboard.domain.enums import RiskGrade
from safety_dashboard.domain.models import DashboardSnapshot, RiskAssessment


GRADE_ORDER = (
    RiskGrade.HIGH,
    RiskGrade.MEDIUM,
    RiskGrade.LOW,
    RiskGrade.UNASSESSED,
    RiskGrade.NONE,
)
GRADE_RANK = {
    RiskGrade.HIGH: 0,
    RiskGrade.MEDIUM: 1,
    RiskGrade.LOW: 2,
    RiskGrade.UNASSESSED: 3,
    RiskGrade.NONE: 4,
}


def grade_label(grade: RiskGrade) -> str:
    return {
        RiskGrade.HIGH: "상",
        RiskGrade.MEDIUM: "중",
        RiskGrade.LOW: "하",
        RiskGrade.UNASSESSED: "미판정",
        RiskGrade.NONE: "영향 없음",
    }[grade]


def render_metric(label: str, value: int | str, note: str) -> None:
    st.markdown(
        f'<div class="metric-card"><div class="metric-label">{label}</div>'
        f'<div class="metric-value">{value}</div><div class="metric-note">{note}</div></div>',
        unsafe_allow_html=True,
    )


def scope_fingerprint(
    snapshot: DashboardSnapshot,
    simulation: bool,
    group_ids: list[str],
    grades: list[RiskGrade],
    configuration_revision: str,
) -> str:
    values = (
        [
            "simulation" if simulation else "live",
            snapshot.policy_version,
            configuration_revision,
        ]
        + sorted(group_ids)
        + sorted(item.value for item in grades)
        + sorted(item.id for item in snapshot.warning_feed.warnings)
        + sorted(
            f"{item.id}:{item.facility_type}" for item in snapshot.facilities
        )
    )
    return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()[:16]


def action_fingerprint(scope_key: str, facility_ids: list[str]) -> str:
    value = "|".join([scope_key, *sorted(facility_ids)])
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def make_scope_label(
    catalog: FacilityGroupCatalog,
    group_ids: list[str],
    grades: list[RiskGrade],
) -> str:
    if not group_ids:
        group_text = "선택한 시설 유형 없음"
    elif set(group_ids) == set(catalog.ids):
        group_text = "전체 시설 유형"
    else:
        group_text = " · ".join(catalog.definition(item).label for item in group_ids)
    if not grades:
        grade_text = "선택한 위험도 없음"
    elif set(grades) == set(GRADE_ORDER):
        grade_text = "전체 등급"
    else:
        grade_text = " · ".join(grade_label(item) for item in grades)
    return f"{group_text} / {grade_text}"


def warning_text(assessment: RiskAssessment) -> str:
    return ", ".join(
        dict.fromkeys(
            f"{reason.warning_type} {reason.raw_level}"
            for reason in assessment.reasons
        )
    ) or "-"
