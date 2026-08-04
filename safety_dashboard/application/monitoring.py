"""한 번의 조회 결과를 모든 화면과 출력물이 공유하도록 구성합니다."""

from __future__ import annotations

import datetime as dt

from safety_dashboard.application.ports import FacilityRepository, WarningMatcher, WarningProvider
from safety_dashboard.domain.enums import RiskGrade, WarningLevel
from safety_dashboard.domain.models import DashboardSnapshot, DashboardSummary
from safety_dashboard.domain.risk_policy import RiskPolicy


class MonitoringService:
    def __init__(
        self,
        facilities: FacilityRepository,
        warnings: WarningProvider,
        matcher: WarningMatcher,
        policy: RiskPolicy,
    ) -> None:
        self._facilities = facilities
        self._warnings = warnings
        self._matcher = matcher
        self._policy = policy

    def get_snapshot(self, now: dt.datetime | None = None) -> DashboardSnapshot:
        generated_at = now or dt.datetime.now()
        facilities = tuple(self._facilities.list_monitored())
        warning_feed = self._warnings.fetch_active()
        assessments = tuple(
            self._policy.assess(
                facility,
                (
                    warning
                    for warning in warning_feed.warnings
                    if self._matcher.matches(facility, warning)
                ),
                assessed_at=generated_at,
            )
            for facility in facilities
        )

        affected = tuple(item for item in assessments if item.grade is not RiskGrade.NONE)
        highest_level = max(
            (item.level for item in warning_feed.warnings),
            key=_warning_level_rank,
            default=WarningLevel.UNKNOWN,
        )
        summary = DashboardSummary(
            active_warning_count=len(warning_feed.warnings),
            affected_facility_count=len(affected),
            high_risk_count=sum(item.grade is RiskGrade.HIGH for item in affected),
            unassessed_count=sum(item.grade is RiskGrade.UNASSESSED for item in affected),
            highest_warning_level=highest_level,
        )
        notices = tuple(filter(None, (warning_feed.message,)))
        return DashboardSnapshot(
            generated_at=generated_at,
            warning_feed=warning_feed,
            facilities=facilities,
            assessments=assessments,
            summary=summary,
            policy_version=self._policy.version,
            notices=notices,
        )


def _warning_level_rank(level: WarningLevel) -> int:
    return {
        WarningLevel.UNKNOWN: 0,
        WarningLevel.ADVISORY: 1,
        WarningLevel.WARNING: 2,
        WarningLevel.CRITICAL: 3,
    }[level]
