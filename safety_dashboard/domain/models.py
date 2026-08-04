"""관제 업무에서 공유하는 불변 데이터 모델."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Mapping

from safety_dashboard.domain.enums import DataHealth, RiskGrade, WarningLevel


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Facility:
    id: str
    name: str
    facility_type: str
    location: GeoPoint
    address: str
    department: str = "-"
    manager: str = "-"
    region_code: str = ""
    is_monitored: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Warning:
    id: str
    source: str
    region_up_code: str
    region_code: str
    region_up: str
    region: str
    warning_type: str
    raw_level: str
    level: WarningLevel
    command: str = ""
    issued_at: dt.datetime | None = None
    effective_at: dt.datetime | None = None


@dataclass(frozen=True)
class WarningFeed:
    warnings: tuple[Warning, ...]
    health: DataHealth
    fetched_at: dt.datetime
    message: str = ""


@dataclass(frozen=True)
class WeatherObservation:
    observed_at: dt.datetime
    health: DataHealth
    temperature_c: float | None = None
    rainfall_1h_mm: float | None = None
    wind_speed_ms: float | None = None
    wind_direction_deg: float | None = None
    message: str = ""


@dataclass(frozen=True)
class RiskReason:
    warning_id: str
    warning_type: str
    raw_level: str
    grade: RiskGrade
    region: str
    policy_key: str


@dataclass(frozen=True)
class RiskAssessment:
    facility: Facility
    grade: RiskGrade
    reasons: tuple[RiskReason, ...]
    policy_version: str
    assessed_at: dt.datetime


@dataclass(frozen=True)
class DashboardSummary:
    active_warning_count: int
    affected_facility_count: int
    high_risk_count: int
    unassessed_count: int
    highest_warning_level: WarningLevel


@dataclass(frozen=True)
class DashboardSnapshot:
    generated_at: dt.datetime
    warning_feed: WarningFeed
    facilities: tuple[Facility, ...]
    assessments: tuple[RiskAssessment, ...]
    summary: DashboardSummary
    policy_version: str
    notices: tuple[str, ...] = ()

