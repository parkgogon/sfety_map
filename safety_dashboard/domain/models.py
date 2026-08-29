"""관제 업무에서 공유하는 불변 데이터 모델."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Mapping

from safety_dashboard.domain.enums import (
    ContextStatus,
    DataHealth,
    KmaFailureCategory,
    RiskGrade,
    WeatherLayerKind,
    WarningLevel,
)


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
    diagnostic: KmaFailureDiagnostic | None = None


@dataclass(frozen=True)
class KmaFailureDiagnostic:
    """관리자 알림에만 사용하는 KMA 실패 진단."""

    category: KmaFailureCategory
    summary: str
    evidence: str
    cause_type: str = ""
    http_status: int | None = None


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
class WeatherGridPoint:
    """KMA 동네예보 격자 한 지점의 실황값."""

    grid_x: int
    grid_y: int
    location: GeoPoint
    value: float | None = None
    u_ms: float | None = None
    v_ms: float | None = None
    speed_ms: float | None = None
    direction_to_deg: float | None = None


@dataclass(frozen=True)
class WeatherLayerFeed:
    kind: WeatherLayerKind
    health: DataHealth
    observed_at: dt.datetime
    fetched_at: dt.datetime
    unit: str
    points: tuple[WeatherGridPoint, ...]
    message: str = ""
    scenario_id: str = ""
    scenario_label: str = ""


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


@dataclass(frozen=True)
class OutgoingTelegramMessage:
    text: str
    silent: bool = False
    action_label: str = ""
    action_url: str = ""


@dataclass(frozen=True)
class FacilityRegion:
    province: str
    district: str
    query_name: str


@dataclass(frozen=True)
class DisasterMessage:
    id: str
    created_at: dt.datetime
    emergency_step: str
    disaster_type: str
    content: str
    regions: tuple[str, ...]


@dataclass(frozen=True)
class DisasterMessageFeed:
    status: ContextStatus
    messages: tuple[DisasterMessage, ...]
    fetched_at: dt.datetime
    detail: str = ""


@dataclass(frozen=True)
class NearbyCctv:
    id: str
    name: str
    location: GeoPoint
    distance_km: float
    road_type: str
    video_url: str
    video_format: str = "MP4"
    updated_at: dt.datetime | None = None
    bearing_deg: float | None = None
    direction_verified_on: dt.date | None = None
    direction_source: str = ""


@dataclass(frozen=True)
class CctvFeed:
    status: ContextStatus
    cctvs: tuple[NearbyCctv, ...]
    fetched_at: dt.datetime
    detail: str = ""
