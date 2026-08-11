"""관제 도메인의 표준 상태와 등급."""

from __future__ import annotations

from enum import Enum


class DataHealth(str, Enum):
    LIVE = "LIVE"
    FALLBACK = "FALLBACK"
    STALE = "STALE"
    ERROR = "ERROR"
    SIMULATION = "SIMULATION"


class ContextStatus(str, Enum):
    """핵심 관제와 독립적으로 로드되는 현장 참고정보의 상태."""

    LIVE = "LIVE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    ERROR = "ERROR"


class WeatherLayerKind(str, Enum):
    """사용자 지도에 한 번에 표시할 실황 기상 레이어."""

    TEMPERATURE = "temperature"
    RAINFALL = "rainfall"
    WIND = "wind"


class WarningLevel(str, Enum):
    ADVISORY = "ADVISORY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class RiskGrade(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNASSESSED = "UNASSESSED"
    NONE = "NONE"
