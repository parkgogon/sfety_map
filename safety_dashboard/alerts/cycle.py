"""한 번의 자동 관제 회차에서 영향 상태와 전파 변화를 계획합니다.

외부 조회와 저장은 담당하지 않습니다. 같은 snapshot·이전 상태·보류 전파를
입력하면 언제나 같은 계획을 반환하므로 변화 감지 규칙을 독립적으로 검증할 수
있습니다.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from safety_dashboard.alerts.domain import (
    AlertBatch,
    AlertTransition,
    AlertTransitionKind,
    FacilityImpact,
    make_batch_id,
)
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.alerts.transitions import (
    deduplicate_transitions,
    detect_transitions,
    filter_impacts_by_warning_type,
    impacts_from_snapshot,
    valid_pending_transitions,
)
from safety_dashboard.domain.models import DashboardSnapshot
from safety_dashboard.domain.risk_policy import RiskPolicy


@dataclass(frozen=True)
class AlertCyclePlan:
    """관제 회차의 순수 계산 결과."""

    state_key: str
    current_impacts: tuple[FacilityImpact, ...]
    baseline_required: bool
    new_transitions: tuple[AlertTransition, ...]
    transitions: tuple[AlertTransition, ...]
    stale_pending_ids: tuple[str, ...]


class AlertCyclePlanner:
    def __init__(self, policy: RiskPolicy, settings: AlertSettings) -> None:
        self.policy = policy
        self.settings = settings

    @property
    def state_key(self) -> str:
        return (
            f"{self.settings.automation_mode}|{self.policy.version}|"
            f"{warning_filter_fingerprint(self.settings)}"
        )

    def impacts(self, snapshot: DashboardSnapshot) -> tuple[FacilityImpact, ...]:
        return filter_impacts_by_warning_type(
            impacts_from_snapshot(snapshot, self.policy),
            self.settings.included_warning_types,
            self.settings.excluded_warning_types,
        )

    def plan(
        self,
        snapshot: DashboardSnapshot,
        *,
        initialized: bool,
        previous_mode: str,
        previous_impacts: Sequence[FacilityImpact],
        pending: Sequence[AlertTransition],
        now: dt.datetime,
    ) -> AlertCyclePlan:
        current_impacts = self.impacts(snapshot)
        state_key = self.state_key
        baseline_required = not initialized or previous_mode != state_key
        if baseline_required:
            return AlertCyclePlan(
                state_key=state_key,
                current_impacts=current_impacts,
                baseline_required=True,
                new_transitions=(),
                transitions=(),
                stale_pending_ids=tuple(item.id for item in pending),
            )

        new_transitions = detect_transitions(
            previous_impacts,
            current_impacts,
            now,
        )
        valid_pending = valid_pending_transitions(pending, current_impacts)
        valid_pending_ids = {item.id for item in valid_pending}
        return AlertCyclePlan(
            state_key=state_key,
            current_impacts=current_impacts,
            baseline_required=False,
            new_transitions=new_transitions,
            transitions=deduplicate_transitions(
                (*new_transitions, *valid_pending)
            ),
            stale_pending_ids=tuple(
                item.id for item in pending if item.id not in valid_pending_ids
            ),
        )

    def batch(
        self,
        transitions: tuple[AlertTransition, ...],
        now: dt.datetime,
    ) -> AlertBatch:
        return AlertBatch(
            id=make_batch_id(transitions),
            created_at=now,
            transitions=transitions,
            mode=self.settings.automation_mode,
            policy_version=self.policy.version,
        )


def warning_filter_fingerprint(settings: AlertSettings) -> str:
    """필터 변경 시 현재 상태를 다시 기준화해 거짓 해제를 막습니다."""

    included = ",".join(sorted(
        item.strip().casefold()
        for item in settings.included_warning_types
        if item.strip()
    ))
    excluded = ",".join(sorted(
        item.strip().casefold()
        for item in settings.excluded_warning_types
        if item.strip()
    ))
    digest = hashlib.sha256(
        f"include={included}|exclude={excluded}".encode("utf-8")
    ).hexdigest()[:12]
    return f"alerts-{digest}"


def transition_counters(
    transitions: tuple[AlertTransition, ...],
) -> dict[str, int]:
    counts = Counter(item.kind for item in transitions)
    warning_counts = {
        kind: len({
            item.impact.warning_key
            for item in transitions
            if item.kind is kind
        })
        for kind in AlertTransitionKind
    }
    return {
        "transition_activated": counts[AlertTransitionKind.ACTIVATED],
        "transition_escalated": counts[AlertTransitionKind.ESCALATED],
        "transition_cleared": counts[AlertTransitionKind.CLEARED],
        "warning_activated": warning_counts[AlertTransitionKind.ACTIVATED],
        "warning_escalated": warning_counts[AlertTransitionKind.ESCALATED],
        "warning_cleared": warning_counts[AlertTransitionKind.CLEARED],
        "affected_facility_events": len({
            item.impact.facility_id for item in transitions
        }),
    }


def poll_counter(mode: str) -> str:
    return "preview_poll_runs" if mode == "preview" else "poll_runs"
