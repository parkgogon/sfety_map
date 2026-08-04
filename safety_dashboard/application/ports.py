"""외부 시스템과 맞닿는 포트. 구현 세부사항은 adapters에 둡니다."""

from __future__ import annotations

from typing import Protocol, Sequence

from safety_dashboard.domain.models import Facility, WarningFeed


class FacilityRepository(Protocol):
    def list_monitored(self) -> Sequence[Facility]: ...


class WarningProvider(Protocol):
    def fetch_active(self) -> WarningFeed: ...


class WarningMatcher(Protocol):
    def matches(self, facility: Facility, warning: object) -> bool: ...


class Notifier(Protocol):
    def send_batch(self, messages: Sequence[str]) -> object: ...


class ReportRenderer(Protocol):
    def render(self, snapshot: object) -> bytes: ...
