"""외부 시스템과 맞닿는 포트. 구현 세부사항은 adapters에 둡니다."""

from __future__ import annotations

import datetime as dt
from typing import Protocol, Sequence

from safety_dashboard.domain.models import (
    CctvFeed,
    DisasterMessageFeed,
    Facility,
    FacilityRegion,
    GeoPoint,
    OutgoingTelegramMessage,
    WarningFeed,
    WeatherObservation,
)


class FacilityRepository(Protocol):
    def list_monitored(self) -> Sequence[Facility]: ...


class WarningProvider(Protocol):
    def fetch_active(self) -> WarningFeed: ...


class WarningMatcher(Protocol):
    def matches(self, facility: Facility, warning: object) -> bool: ...


class Notifier(Protocol):
    def send_batch(
        self,
        messages: Sequence[OutgoingTelegramMessage | str],
    ) -> object: ...


class DisasterMessageProvider(Protocol):
    def fetch_recent(
        self,
        region: FacilityRegion,
        since: dt.datetime,
    ) -> DisasterMessageFeed: ...


class CctvProvider(Protocol):
    def fetch_nearby(
        self,
        location: GeoPoint,
        radius_km: float = 20,
        limit: int = 5,
    ) -> CctvFeed: ...


class CurrentWeatherProvider(Protocol):
    def fetch(
        self,
        location: GeoPoint,
        now: dt.datetime | None = None,
    ) -> WeatherObservation: ...


class ReportRenderer(Protocol):
    def render(self, snapshot: object) -> bytes: ...
