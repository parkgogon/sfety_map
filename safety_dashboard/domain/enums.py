"""관제 도메인의 표준 상태와 등급."""

from __future__ import annotations

from enum import Enum


class DataHealth(str, Enum):
    LIVE = "LIVE"
    FALLBACK = "FALLBACK"
    STALE = "STALE"
    ERROR = "ERROR"
    SIMULATION = "SIMULATION"


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

