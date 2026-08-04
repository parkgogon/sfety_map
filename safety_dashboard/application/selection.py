"""전체 관제 결과에서 조회 범위와 후속 작업 범위를 일관되게 만듭니다."""

from __future__ import annotations

from collections.abc import Iterable

from safety_dashboard.application.facility_groups import FacilityGroupCatalog
from safety_dashboard.domain.enums import RiskGrade, WarningLevel
from safety_dashboard.domain.models import (
    DashboardSnapshot,
    DashboardSummary,
    RiskAssessment,
    Warning,
    WarningFeed,
)


def filter_snapshot(
    snapshot: DashboardSnapshot,
    catalog: FacilityGroupCatalog,
    group_ids: Iterable[str],
    grades: Iterable[RiskGrade],
) -> DashboardSnapshot:
    """시설 그룹과 등급을 모두 만족하는 조회 snapshot을 반환합니다."""

    facility_ids = catalog.facility_ids_for_groups(snapshot.facilities, group_ids)
    selected_grades = frozenset(grades)
    assessments = tuple(
        item
        for item in snapshot.assessments
        if item.facility.id in facility_ids and item.grade in selected_grades
    )
    return _subset_snapshot(snapshot, assessments)


def action_snapshot(
    filtered_snapshot: DashboardSnapshot,
    selected_facility_ids: Iterable[str],
) -> DashboardSnapshot:
    """체크한 영향 시설만 Telegram·PDF에 전달할 snapshot을 만듭니다."""

    selected = frozenset(str(item) for item in selected_facility_ids)
    assessments = tuple(
        item
        for item in filtered_snapshot.assessments
        if item.facility.id in selected and item.grade is not RiskGrade.NONE
    )
    return _subset_snapshot(filtered_snapshot, assessments)


def _subset_snapshot(
    source: DashboardSnapshot,
    assessments: tuple[RiskAssessment, ...],
) -> DashboardSnapshot:
    facility_ids = {item.facility.id for item in assessments}
    warning_ids = {
        reason.warning_id
        for item in assessments
        for reason in item.reasons
    }
    facilities = tuple(
        facility for facility in source.facilities if facility.id in facility_ids
    )
    warnings = tuple(
        warning
        for warning in source.warning_feed.warnings
        if warning.id in warning_ids
    )
    warning_feed = WarningFeed(
        warnings=warnings,
        health=source.warning_feed.health,
        fetched_at=source.warning_feed.fetched_at,
        message=source.warning_feed.message,
    )
    return DashboardSnapshot(
        generated_at=source.generated_at,
        warning_feed=warning_feed,
        facilities=facilities,
        assessments=assessments,
        summary=_summary(assessments, warnings),
        policy_version=source.policy_version,
        notices=source.notices,
    )


def _summary(
    assessments: tuple[RiskAssessment, ...],
    warnings: tuple[Warning, ...],
) -> DashboardSummary:
    affected = tuple(item for item in assessments if item.grade is not RiskGrade.NONE)
    highest_level = max(
        (item.level for item in warnings),
        key=_warning_level_rank,
        default=WarningLevel.UNKNOWN,
    )
    return DashboardSummary(
        active_warning_count=len(warnings),
        affected_facility_count=len(affected),
        high_risk_count=sum(item.grade is RiskGrade.HIGH for item in affected),
        unassessed_count=sum(item.grade is RiskGrade.UNASSESSED for item in affected),
        highest_warning_level=highest_level,
    )


def _warning_level_rank(level: WarningLevel) -> int:
    return {
        WarningLevel.UNKNOWN: 0,
        WarningLevel.ADVISORY: 1,
        WarningLevel.WARNING: 2,
        WarningLevel.CRITICAL: 3,
    }[level]
