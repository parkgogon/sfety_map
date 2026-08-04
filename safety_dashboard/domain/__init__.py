"""외부 API와 UI에 의존하지 않는 도메인 계층."""

from safety_dashboard.domain.enums import ContextStatus, DataHealth, RiskGrade, WarningLevel
from safety_dashboard.domain.models import (
    CctvFeed,
    DashboardSnapshot,
    DashboardSummary,
    DisasterMessage,
    DisasterMessageFeed,
    Facility,
    FacilityRegion,
    GeoPoint,
    NearbyCctv,
    OutgoingTelegramMessage,
    RiskAssessment,
    RiskReason,
    Warning,
    WarningFeed,
    WeatherObservation,
)

__all__ = [
    "CctvFeed",
    "DashboardSnapshot",
    "DashboardSummary",
    "ContextStatus",
    "DataHealth",
    "DisasterMessage",
    "DisasterMessageFeed",
    "Facility",
    "FacilityRegion",
    "GeoPoint",
    "NearbyCctv",
    "OutgoingTelegramMessage",
    "RiskAssessment",
    "RiskGrade",
    "RiskReason",
    "Warning",
    "WarningFeed",
    "WarningLevel",
    "WeatherObservation",
]
