"""관제 snapshot을 시설-특보 영향 상태와 변화로 변환합니다."""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Iterable, Sequence

from safety_dashboard.alerts.domain import (
    AlertTransition,
    AlertTransitionKind,
    FacilityImpact,
)
from safety_dashboard.domain.enums import RiskGrade, WarningLevel
from safety_dashboard.domain.models import DashboardSnapshot
from safety_dashboard.domain.risk_policy import RiskPolicy


_WARNING_RANK = {
    WarningLevel.UNKNOWN: 0,
    WarningLevel.ADVISORY: 1,
    WarningLevel.WARNING: 2,
    WarningLevel.CRITICAL: 3,
}
_GRADE_RANK = {
    RiskGrade.NONE: 0,
    RiskGrade.UNASSESSED: 1,
    RiskGrade.LOW: 2,
    RiskGrade.MEDIUM: 3,
    RiskGrade.HIGH: 4,
}


def impacts_from_snapshot(
    snapshot: DashboardSnapshot,
    policy: RiskPolicy,
) -> tuple[FacilityImpact, ...]:
    warnings = {item.id: item for item in snapshot.warning_feed.warnings}
    result: list[FacilityImpact] = []
    for assessment in snapshot.assessments:
        for reason in assessment.reasons:
            warning = warnings.get(reason.warning_id)
            if warning is None:
                continue
            warning_key = f"{warning.region_code}|{warning.warning_type}"
            impact_key = f"{assessment.facility.id}|{warning_key}"
            result.append(
                FacilityImpact(
                    key=impact_key,
                    facility_id=assessment.facility.id,
                    facility_name=assessment.facility.name,
                    warning_key=warning_key,
                    warning_id=warning.id,
                    region_code=warning.region_code,
                    region=warning.region,
                    warning_type=warning.warning_type,
                    raw_level=warning.raw_level,
                    warning_level=warning.level,
                    risk_grade=reason.grade,
                    issued_at=warning.issued_at,
                    effective_at=warning.effective_at,
                    recommended_action=policy.definition(reason.grade).action,
                )
            )
    return tuple(sorted(result, key=lambda item: item.key))


def detect_transitions(
    previous: Sequence[FacilityImpact],
    current: Sequence[FacilityImpact],
    now: dt.datetime,
) -> tuple[AlertTransition, ...]:
    before = {item.key: item for item in previous}
    after = {item.key: item for item in current}
    result: list[AlertTransition] = []
    for key in sorted(before.keys() | after.keys()):
        old = before.get(key)
        new = after.get(key)
        kind: AlertTransitionKind | None = None
        if old is None and new is not None:
            kind = AlertTransitionKind.ACTIVATED
        elif old is not None and new is None:
            kind = AlertTransitionKind.CLEARED
        elif old is not None and new is not None and _is_escalation(old, new):
            kind = AlertTransitionKind.ESCALATED
        if kind is None:
            continue
        result.append(
            AlertTransition(
                id=_transition_id(kind, old, new),
                kind=kind,
                detected_at=now,
                previous=old,
                current=new,
            )
        )
    return tuple(result)


def valid_pending_transitions(
    pending: Iterable[AlertTransition],
    current: Sequence[FacilityImpact],
) -> tuple[AlertTransition, ...]:
    """30분 이내 보류 알림 중 현재 상태와 모순되지 않는 항목만 복구합니다."""

    current_by_key = {item.key: item for item in current}
    result = []
    for item in pending:
        current_impact = current_by_key.get(item.impact.key)
        if item.kind is AlertTransitionKind.CLEARED:
            valid = current_impact is None
        elif item.kind is AlertTransitionKind.ESCALATED:
            target = item.current
            valid = bool(
                current_impact is not None
                and target is not None
                and _WARNING_RANK[current_impact.warning_level]
                >= _WARNING_RANK[target.warning_level]
                and _GRADE_RANK[current_impact.risk_grade]
                >= _GRADE_RANK[target.risk_grade]
            )
        else:
            valid = current_impact is not None
        if valid:
            result.append(
                AlertTransition(
                    id=item.id,
                    kind=item.kind,
                    detected_at=item.detected_at,
                    previous=item.previous,
                    current=current_impact or item.current,
                    delayed=True,
                )
            )
    return tuple(result)


def deduplicate_transitions(
    transitions: Iterable[AlertTransition],
) -> tuple[AlertTransition, ...]:
    values = {item.id: item for item in transitions}
    return tuple(sorted(values.values(), key=lambda item: item.id))


def _is_escalation(previous: FacilityImpact, current: FacilityImpact) -> bool:
    return (
        _WARNING_RANK[current.warning_level] > _WARNING_RANK[previous.warning_level]
        or _GRADE_RANK[current.risk_grade] > _GRADE_RANK[previous.risk_grade]
    )


def _transition_id(
    kind: AlertTransitionKind,
    previous: FacilityImpact | None,
    current: FacilityImpact | None,
) -> str:
    impact = current or previous
    if impact is None:  # pragma: no cover - 내부 호출 방어
        raise ValueError("영향 상태가 없습니다.")
    values = [kind.value, impact.key]
    if kind is AlertTransitionKind.ESCALATED:
        values.extend(
            (
                previous.fingerprint if previous else "",
                current.fingerprint if current else "",
            )
        )
    elif kind is AlertTransitionKind.ACTIVATED:
        values.append(current.fingerprint if current else "")
    else:
        values.append(previous.fingerprint if previous else "")
    return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()[:24]
